#!/usr/bin/env python3
"""
Auth + QA TikTok API v2 — app « Gardeco Social » (App ID 7667511326537975815).

Le `login` déroule le flow OAuth complet : c'est ce flow qu'on filme (en sandbox)
pour la review de l'app TikTok (exigence : démo de bout en bout, OAuth + action
API, tournée en sandbox tant que l'app n'a jamais été approuvée).

  python3 tiktok_auth.py login      # navigateur → consentement → code à coller → tokens
  python3 tiktok_auth.py whoami     # vérifie le token (GET /v2/user/info/)
  python3 tiktok_auth.py refresh    # renouvelle l'access token (24 h)
  python3 tiktok_auth.py post-test  # photo de démo via Content Posting API (SELF_ONLY)
  python3 tiktok_auth.py secrets    # commandes gh pour les secrets GitHub Actions

Environnements — TIKTOK_ENV choisit la conf (défaut : prod) :
  prod     credentials Production de l'app   tokens → tiktok-social.json
  sandbox  credentials du Sandbox (portail)  tokens → tiktok-social.sandbox.json
⚠️ Contrairement à Pinterest, le host API est LE MÊME dans les deux cas
(open.tiktokapis.com) : c'est le client_key qui détermine l'environnement.
Un sandbox a ses PROPRES client key/secret (portail → onglet Sandbox), n'accepte
que les comptes ajoutés en « Target users » (max 10) et ne publie jamais
réellement. Chaque env fournit donc ses credentials au premier login :
  TIKTOK_ENV=sandbox TIKTOK_CLIENT_KEY=… TIKTOK_CLIENT_SECRET=… python3 tiktok_auth.py login

⚠️ Pas de redirect localhost chez TikTok (rejeté, contrairement à Pinterest) :
le redirect est https://gardeco.ch/tiktok-callback/ (domaine vérifié par TXT DNS,
la page affiche le code) — on colle le code, ou l'URL de retour entière, dans le
terminal. Le même redirect doit être déclaré dans le portail (prod ET sandbox).

Tokens : access 24 h, refresh 365 j. TikTok PEUT réémettre un refresh token au
refresh — on garde toujours le dernier reçu ; si le secret GitHub Actions est
posé, le re-poser après (cf. `secrets`). Après un an : re-consentir (login).

Restriction pré-audit : tant que l'app n'a pas passé l'audit Content Posting,
tout post direct est forcé SELF_ONLY (visible du seul compte) — côté serveur.

Client key / secret : portail dev TikTok → Gardeco Social (copie 1Password :
« Gardeco - TikTok App Secret »). À fournir en env au premier login ; ensuite
relus depuis le fichier de conf (0600).
"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error, webbrowser
from datetime import datetime, timedelta, timezone

ENV_LABEL = "sandbox" if os.environ.get("TIKTOK_ENV", "prod").strip() == "sandbox" else "prod"
SANDBOX = ENV_LABEL == "sandbox"
API = "https://open.tiktokapis.com/v2"
AUTHORIZE = "https://www.tiktok.com/v2/auth/authorize/"
REDIRECT = "https://gardeco.ch/tiktok-callback/"
SCOPES = "user.info.basic,video.publish"
CONF = os.path.expanduser("~/.config/claude-seo/tiktok-social%s.json" % (".sandbox" if SANDBOX else ""))

# PULL_FROM_URL n'accepte que les domaines vérifiés dans le portail (gardeco.ch ✓,
# jsDelivr ✗) — l'image de démo vit donc sur le site.
TEST_IMAGE = os.environ.get("TIKTOK_TEST_IMAGE", "https://gardeco.ch/images/home/sora-p7-hero.webp")
TEST_POST = {"title": "Beatbot Sora P7 — robot de piscine sans fil",
             "description": "Nettoyage fond, parois et ligne d'eau + skimmer de surface. "
                            "Livré depuis la Suisse. gardeco.ch"}


def load_conf():
    return json.load(open(CONF, encoding="utf-8")) if os.path.exists(CONF) else {}


def save_conf(conf):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    json.dump(conf, open(CONF, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.chmod(CONF, 0o600)


def creds(conf):
    # ⚠️ pas de fallback prod↔sandbox : les credentials sont DIFFÉRENTS par env
    key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip() or conf.get("client_key", "")
    secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip() or conf.get("client_secret", "")
    if not (key and secret):
        sys.exit("Client key / secret %s manquants. Portail dev TikTok → Gardeco Social%s, puis :\n"
                 "  TIKTOK_ENV=%s TIKTOK_CLIENT_KEY=… TIKTOK_CLIENT_SECRET=… python3 tiktok_auth.py login"
                 % (ENV_LABEL, " → onglet Sandbox" if SANDBOX else "", ENV_LABEL))
    return key, secret


def token_call(data):
    req = urllib.request.Request(API + "/oauth/token/",
                                 data=urllib.parse.urlencode(data).encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("POST /oauth/token/ (%s) -> HTTP %s %s" % (ENV_LABEL, e.code, e.read().decode()[:400]))
    if tok.get("error"):
        sys.exit("POST /oauth/token/ (%s) -> %s : %s (log_id %s)"
                 % (ENV_LABEL, tok["error"], tok.get("error_description"), tok.get("log_id")))
    return tok


def bearer_call(method, path, body=None):
    conf = load_conf()
    tok = conf.get("access_token")
    if not tok:
        sys.exit("Pas d'access token %s — lancer d'abord : python3 tiktok_auth.py login" % ENV_LABEL)
    req = urllib.request.Request(API + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method=method)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Content-Type", "application/json; charset=UTF-8")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("%s %s (%s) -> HTTP %s %s" % (method, path, ENV_LABEL, e.code, e.read().decode()[:400]))
    err = out.get("error") or {}
    if err.get("code") not in (None, "ok"):
        sys.exit("%s %s (%s) -> %s : %s (log_id %s)"
                 % (method, path, ENV_LABEL, err.get("code"), err.get("message"), err.get("log_id")))
    return out.get("data", out)


def store_tokens(conf, key, secret, tok):
    now = datetime.now(timezone.utc)
    conf.update({
        "client_key": key, "client_secret": secret, "env": ENV_LABEL,
        "open_id": tok.get("open_id", conf.get("open_id", "")),
        "access_token": tok["access_token"],
        "access_expires_at": (now + timedelta(seconds=tok.get("expires_in", 0))).isoformat(),
    })
    if tok.get("refresh_token"):
        conf["refresh_token"] = tok["refresh_token"]
        conf["refresh_expires_at"] = (now + timedelta(seconds=tok.get("refresh_expires_in", 0))).isoformat()
    save_conf(conf)


def cmd_login():
    conf = load_conf()
    key, secret = creds(conf)
    import secrets as pysecrets
    state = pysecrets.token_urlsafe(16)
    url = AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_key": key, "scope": SCOPES, "response_type": "code",
        "redirect_uri": REDIRECT, "state": state})
    print("1/4  [%s] Ouverture du navigateur (consentement TikTok)…" % ENV_LABEL)
    print("     " + url)
    if SANDBOX:
        print("     ⚠️ sandbox : seuls les comptes ajoutés en Target users peuvent consentir.")
    webbrowser.open(url)
    print("2/4  Après consentement, la page %s affiche le code." % REDIRECT)
    raw = input("     Collez le code (ou l'URL de retour complète) : ").strip()
    if raw.startswith("http"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
        if q.get("state", [state])[0] != state:
            sys.exit("state OAuth inattendu — on arrête (anti-CSRF).")
        if "error" in q:
            sys.exit("Refusé : %s (%s)" % (q["error"][0], q.get("error_description", [""])[0]))
        code = q.get("code", [""])[0]
    else:
        code = urllib.parse.unquote(raw)
    if not code:
        sys.exit("Pas de code dans ce qui a été collé.")
    print("3/4  Échange du code contre les tokens (%s)…" % ENV_LABEL)
    tok = token_call({"client_key": key, "client_secret": secret, "code": code,
                      "grant_type": "authorization_code", "redirect_uri": REDIRECT})
    store_tokens(conf, key, secret, tok)
    print("     Tokens enregistrés dans %s (scopes : %s)" % (CONF, tok.get("scope")))
    me = bearer_call("GET", "/user/info/?fields=open_id,display_name")
    print("4/4  Authentifié : %s (open_id %s…)" % (me["user"].get("display_name"),
                                                   me["user"].get("open_id", "")[:12]))


def cmd_refresh():
    conf = load_conf()
    key, secret = creds(conf)
    if not conf.get("refresh_token"):
        sys.exit("Pas de refresh token %s — lancer d'abord : python3 tiktok_auth.py login" % ENV_LABEL)
    old = conf["refresh_token"]
    tok = token_call({"client_key": key, "client_secret": secret,
                      "grant_type": "refresh_token", "refresh_token": old})
    store_tokens(conf, key, secret, tok)
    print("Access token %s renouvelé, expire le %s" % (ENV_LABEL, conf["access_expires_at"][:16]))
    if tok.get("refresh_token") and tok["refresh_token"] != old:
        print("⚠️ NOUVEAU refresh token émis — re-poser le secret GitHub Actions (cf. `secrets`).")


def cmd_whoami():
    me = bearer_call("GET", "/user/info/?fields=open_id,union_id,display_name,avatar_url")
    print("[%s] %s — open_id %s" % (ENV_LABEL, me["user"].get("display_name"), me["user"].get("open_id")))
    conf = load_conf()
    for key, label in (("access_expires_at", "access token"), ("refresh_expires_at", "refresh token")):
        if conf.get(key):
            delta = datetime.fromisoformat(conf[key]) - datetime.now(timezone.utc)
            print("%s : expire dans %d j %dh" % (label, delta.days, delta.seconds // 3600))


def cmd_post_test():
    """Photo de démo via la Content Posting API (l'« action API » de la vidéo de
    review). Toujours SELF_ONLY par défaut ; en prod le post apparaîtrait sur le
    vrai compte (même privé) → garde-fou, règle : aucun post sans validation Nicolas."""
    if not SANDBOX and os.environ.get("TIKTOK_POST_PROD_OK") != "1":
        sys.exit("post-test en PROD posterait sur le vrai compte @gardecoch (même en SELF_ONLY).\n"
                 "Pour la démo/QA, passer par le sandbox :\n"
                 "  TIKTOK_ENV=sandbox python3 tiktok_auth.py post-test\n"
                 "(ou TIKTOK_POST_PROD_OK=1 si le post prod est explicitement validé)")
    creator = bearer_call("POST", "/post/publish/creator_info/query/", {})
    options = creator.get("privacy_level_options", [])
    print("Compte créateur : %s — privacy dispo : %s" % (creator.get("creator_username"), options))
    privacy = os.environ.get("TIKTOK_PRIVACY", "SELF_ONLY")
    if options and privacy not in options:
        sys.exit("privacy %s indisponible pour ce compte (app non auditée → SELF_ONLY seulement)." % privacy)
    body = {"post_info": {"title": TEST_POST["title"][:90],
                          "description": TEST_POST["description"][:4000],
                          "privacy_level": privacy,
                          "disable_comment": True,
                          # divulgation contenu commercial : notre propre marque
                          "brand_organic_toggle": True, "brand_content_toggle": False},
            "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0,
                            "photo_images": [TEST_IMAGE]},
            "post_mode": "DIRECT_POST", "media_type": "PHOTO"}
    out = bearer_call("POST", "/post/publish/content/init/", body)
    pid = out["publish_id"]
    print("publish_id : %s — attente du statut…" % pid)
    for _ in range(24):
        st = bearer_call("POST", "/post/publish/status/fetch/", {"publish_id": pid})
        status = st.get("status")
        if status == "PUBLISH_COMPLETE":
            print("✅ post publié (%s, privacy %s)" % (ENV_LABEL, privacy))
            if SANDBOX:
                print("→ sandbox : rien n'est réellement publié sur TikTok.")
            return
        if status == "FAILED":
            sys.exit("❌ FAILED : %s" % st.get("fail_reason"))
        print("   …", status)
        time.sleep(5)
    sys.exit("Statut toujours pas final après 2 min — relancer status/fetch avec publish_id %s" % pid)


def cmd_secrets():
    if SANDBOX:
        sys.exit("`secrets` se lance sans TIKTOK_ENV : Actions publie en prod, jamais avec la conf sandbox.")
    conf = load_conf()
    if not conf.get("refresh_token"):
        sys.exit("Pas de tokens prod — lancer d'abord : python3 tiktok_auth.py login")
    print("À poser sur Gardecodev/gardeco-social (gh auth switch --user Gardecodev d'abord) :")
    for name, key in (("TIKTOK_CLIENT_KEY", "client_key"), ("TIKTOK_CLIENT_SECRET", "client_secret"),
                      ("TIKTOK_REFRESH_TOKEN", "refresh_token")):
        print("  gh secret set %s --repo Gardecodev/gardeco-social --body '%s'" % (name, conf.get(key, "")))
    if conf.get("refresh_expires_at"):
        print("⚠️ refresh token valable jusqu'au %s — re-consentir (login) avant." % conf["refresh_expires_at"][:10])


if __name__ == "__main__":
    commands = {"login": cmd_login, "refresh": cmd_refresh, "whoami": cmd_whoami,
                "post-test": cmd_post_test, "secrets": cmd_secrets}
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg not in commands:
        sys.exit(__doc__.strip())
    commands[arg]()
