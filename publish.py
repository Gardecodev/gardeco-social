#!/usr/bin/env python3
"""
Auto-publisher Beatbot (Instagram + Facebook) — campagne été 2026.

Lit schedule.json, publie les posts dont l'heure est arrivée et qui ne sont
pas déjà publiés (state/published.json), sur IG et FB via la Graph API.

Idempotent : chaque plateforme est marquée séparément. Un post déjà publié
est ignoré. Sûr à relancer (les horaires cron redondants ne double-postent pas).

Variables d'environnement :
  META_TOKEN      token de Page (Gardeco) — n'expire pas
  IG_USER_ID      id du compte IG business (@gardecoch)
  FB_PAGE_ID      id de la Page FB Gardeco
  PUSHOVER_TOKEN  (optionnel) app token Pushover
  PUSHOVER_USER   (optionnel) user key Pushover
  DRY             "1" = simulation (n'appelle pas l'API de publication)
  ONLY_POST       (optionnel) ne traiter que ce post (ex "02"), ignore l'heure
"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone

GRAPH = "https://graph.facebook.com/v21.0"
TOKEN   = os.environ["META_TOKEN"]
IG_USER = os.environ["IG_USER_ID"]
FB_PAGE = os.environ["FB_PAGE_ID"]
PUSH_TOKEN = os.environ.get("PUSHOVER_TOKEN", "").strip()
PUSH_USER  = os.environ.get("PUSHOVER_USER", "").strip()
DRY  = os.environ.get("DRY", "0") == "1"
ONLY = os.environ.get("ONLY_POST", "").strip()

ROOT = os.path.dirname(os.path.abspath(__file__))
SCHED = json.load(open(os.path.join(ROOT, "schedule.json"), encoding="utf-8"))
STATE_PATH = os.path.join(ROOT, "state", "published.json")
state = json.load(open(STATE_PATH, encoding="utf-8")) if os.path.exists(STATE_PATH) else {}


def api(method, path, data=None):
    url = GRAPH + "/" + path
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s -> HTTP %s %s" % (method, path.split("?")[0], e.code, e.read().decode()[:400]))


def push(msg, title="Beatbot social"):
    if not (PUSH_TOKEN and PUSH_USER):
        return
    try:
        urllib.request.urlopen("https://api.pushover.net/1/messages.json",
            data=urllib.parse.urlencode({"token": PUSH_TOKEN, "user": PUSH_USER,
                                         "title": title, "message": msg}).encode(), timeout=30)
    except Exception as e:
        print("  (pushover KO: %s)" % e)


# ---------- Instagram ----------
def ig_container(params):
    params["access_token"] = TOKEN
    return api("POST", "%s/media" % IG_USER, params)["id"]


def ig_wait(container_id, tries=40):
    for _ in range(tries):
        st = api("GET", "%s?fields=status_code&access_token=%s" % (container_id, TOKEN))
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise RuntimeError("IG container %s -> ERROR" % container_id)
        time.sleep(5)
    raise RuntimeError("IG container %s pas prêt après %d essais" % (container_id, tries))


def publish_instagram(post):
    media, caption = post["media"], post["caption"]
    if len(media) == 1:
        cid = ig_container({"image_url": media[0], "caption": caption})
        ig_wait(cid)
    else:
        children = [ig_container({"image_url": u, "is_carousel_item": "true"}) for u in media]
        for ch in children:
            ig_wait(ch)
        cid = ig_container({"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
        ig_wait(cid)
    return api("POST", "%s/media_publish" % IG_USER, {"creation_id": cid, "access_token": TOKEN})["id"]


# ---------- Facebook ----------
def publish_facebook(post):
    media, caption = post["media"], post["caption"]
    if len(media) == 1:
        r = api("POST", "%s/photos" % FB_PAGE,
                {"url": media[0], "caption": caption, "access_token": TOKEN})
        return r.get("post_id") or r.get("id")
    ids = []
    for u in media:
        r = api("POST", "%s/photos" % FB_PAGE, {"url": u, "published": "false", "access_token": TOKEN})
        ids.append(r["id"])
    # attached_media en clés indexées (forme fiable, validée en prod le 03-07)
    data = {"message": caption, "access_token": TOKEN}
    for idx, pid in enumerate(ids):
        data["attached_media[%d]" % idx] = json.dumps({"media_fbid": pid})
    r = api("POST", "%s/feed" % FB_PAGE, data)
    return r.get("id")


def is_due(post, now):
    t = datetime.fromisoformat(post["publish_at_utc"].replace("Z", "+00:00"))
    return now >= t


def main():
    now = datetime.now(timezone.utc)
    changed = False
    for post in SCHED:
        pid = post["post"]
        if ONLY and pid != ONLY:
            continue
        st = dict(state.get(pid, {}))
        plats = post["platforms"]
        done = all(st.get(p) for p in plats)
        if done:
            continue
        if not ONLY and not is_due(post, now):
            continue
        print("== post %s (%s) — %s, %d visuel(s) ==" % (pid, post["local"], post["type"], len(post["media"])))
        if DRY:
            print("   plateformes:", plats)
            for m in post["media"]:
                print("   ", m)
            continue
        try:
            if "instagram" in plats and not st.get("instagram"):
                st["instagram"] = publish_instagram(post)
                print("   IG  ->", st["instagram"])
            if "facebook" in plats and not st.get("facebook"):
                st["facebook"] = publish_facebook(post)
                print("   FB  ->", st["facebook"])
            st["published_at"] = now.isoformat()
            state[pid] = st
            changed = True
            push("Post %s publié sur %s ✅" % (pid, " + ".join(p for p in plats if st.get(p))))
        except Exception as e:
            state[pid] = st  # garde ce qui a réussi (ex IG ok, FB échoue)
            changed = changed or bool(st)
            print("   ERREUR:", e)
            push("Post %s ÉCHEC ⚠️\n%s" % (pid, str(e)[:300]))
    if changed and not DRY:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        json.dump(state, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("state/published.json mis à jour")
    else:
        print("(rien à publier)" if not DRY else "(dry-run terminé)")


if __name__ == "__main__":
    main()
