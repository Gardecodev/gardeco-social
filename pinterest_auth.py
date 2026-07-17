#!/usr/bin/env python3
"""
Auth Pinterest API v5 — app « Gardeco Social » (App ID 1580225).

Le `login` déroule le flow OAuth complet : c'est ce flow qu'on filme pour la
demande d'accès Standard (exigence Pinterest : la démo doit montrer le flow
OAuth en entier + une action API réussie).

  python3 pinterest_auth.py login    # navigateur → consentement → tokens
  python3 pinterest_auth.py whoami   # vérifie le token (GET /v5/user_account)
  python3 pinterest_auth.py refresh  # renouvelle l'access token (30 j) via le refresh token (~1 an)
  python3 pinterest_auth.py secrets  # commandes gh pour poser les secrets GitHub Actions

App ID / App secret : portail dev Pinterest → My apps → Gardeco Social.
À fournir en env (PINTEREST_APP_ID / PINTEREST_APP_SECRET) au premier login ;
ensuite relus depuis ~/.config/claude-seo/pinterest-social.json (0600).
Le redirect URI http://localhost:8085/ doit être déclaré dans le portail dev.
"""
import base64, json, os, secrets, sys, urllib.request, urllib.parse, urllib.error, webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

API = "https://api.pinterest.com/v5"
REDIRECT = "http://localhost:8085/"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
CONF = os.path.expanduser("~/.config/claude-seo/pinterest-social.json")


def load_conf():
    return json.load(open(CONF, encoding="utf-8")) if os.path.exists(CONF) else {}


def save_conf(conf):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    json.dump(conf, open(CONF, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.chmod(CONF, 0o600)


def creds(conf):
    app_id = os.environ.get("PINTEREST_APP_ID", "").strip() or conf.get("app_id", "")
    secret = os.environ.get("PINTEREST_APP_SECRET", "").strip() or conf.get("app_secret", "")
    if not (app_id and secret):
        sys.exit("App ID / App secret manquants. Portail dev Pinterest → My apps → Gardeco Social, puis :\n"
                 "  PINTEREST_APP_ID=… PINTEREST_APP_SECRET=… python3 pinterest_auth.py login")
    return app_id, secret


def token_call(app_id, secret, data):
    basic = base64.b64encode(("%s:%s" % (app_id, secret)).encode()).decode()
    req = urllib.request.Request(API + "/oauth/token",
                                 data=urllib.parse.urlencode(data).encode(), method="POST")
    req.add_header("Authorization", "Basic " + basic)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("POST /oauth/token -> HTTP %s %s" % (e.code, e.read().decode()[:400]))


def bearer_get(path):
    conf = load_conf()
    tok = conf.get("access_token")
    if not tok:
        sys.exit("Pas d'access token — lancer d'abord : python3 pinterest_auth.py login")
    req = urllib.request.Request(API + path)
    req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("GET %s -> HTTP %s %s" % (path, e.code, e.read().decode()[:400]))


def store_tokens(conf, app_id, secret, tok):
    now = datetime.now(timezone.utc)
    conf.update({
        "app_id": app_id, "app_secret": secret,
        "access_token": tok["access_token"],
        "access_expires_at": (now + timedelta(seconds=tok.get("expires_in", 0))).isoformat(),
    })
    if tok.get("refresh_token"):
        conf["refresh_token"] = tok["refresh_token"]
        conf["refresh_expires_at"] = (now + timedelta(seconds=tok.get("refresh_token_expires_in", 0))).isoformat()
    save_conf(conf)


def cmd_login():
    conf = load_conf()
    app_id, secret = creds(conf)
    state = secrets.token_urlsafe(16)
    url = "https://www.pinterest.com/oauth/?" + urllib.parse.urlencode({
        "client_id": app_id, "redirect_uri": REDIRECT,
        "response_type": "code", "scope": SCOPES, "state": state})
    got = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Autorisation Pinterest reçue ✔</h2><p>Retournez au terminal.</p>".encode())

        def log_message(self, *args):
            pass

    print("1/4  Ouverture du navigateur (consentement Pinterest)…")
    print("     " + url)
    server = HTTPServer(("localhost", 8085), Callback)
    webbrowser.open(url)
    print("2/4  En attente du callback sur %s …" % REDIRECT)
    while "code" not in got and "error" not in got:
        server.handle_request()
    server.server_close()
    if "error" in got:
        sys.exit("Refusé : %s" % got["error"])
    if got.get("state") != state:
        sys.exit("state OAuth inattendu — on arrête (anti-CSRF).")
    print("3/4  Code reçu, échange contre les tokens…")
    tok = token_call(app_id, secret, {"grant_type": "authorization_code",
                                      "code": got["code"], "redirect_uri": REDIRECT})
    store_tokens(conf, app_id, secret, tok)
    print("     Tokens enregistrés dans %s" % CONF)
    me = bearer_get("/user_account")
    print("4/4  Authentifié : @%s (%s)" % (me.get("username"), me.get("account_type")))


def cmd_refresh():
    conf = load_conf()
    app_id, secret = creds(conf)
    if not conf.get("refresh_token"):
        sys.exit("Pas de refresh token — lancer d'abord : python3 pinterest_auth.py login")
    tok = token_call(app_id, secret, {"grant_type": "refresh_token",
                                      "refresh_token": conf["refresh_token"]})
    store_tokens(conf, app_id, secret, tok)
    print("Access token renouvelé, expire le %s" % conf["access_expires_at"][:10])


def cmd_whoami():
    me = bearer_get("/user_account")
    print("@%s — type %s" % (me.get("username"), me.get("account_type")))
    conf = load_conf()
    for key, label in (("access_expires_at", "access token"), ("refresh_expires_at", "refresh token")):
        if conf.get(key):
            days = (datetime.fromisoformat(conf[key]) - datetime.now(timezone.utc)).days
            print("%s : expire dans %d j" % (label, days))


def cmd_secrets():
    conf = load_conf()
    if not conf.get("refresh_token"):
        sys.exit("Pas de tokens — lancer d'abord : python3 pinterest_auth.py login")
    print("À poser sur Gardecodev/gardeco-social (gh auth switch --user Gardecodev d'abord) :")
    for name, key in (("PINTEREST_APP_ID", "app_id"), ("PINTEREST_APP_SECRET", "app_secret"),
                      ("PINTEREST_REFRESH_TOKEN", "refresh_token")):
        print("  gh secret set %s --repo Gardecodev/gardeco-social --body '%s'" % (name, conf.get(key, "")))


if __name__ == "__main__":
    commands = {"login": cmd_login, "refresh": cmd_refresh, "whoami": cmd_whoami, "secrets": cmd_secrets}
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg not in commands:
        sys.exit(__doc__.strip())
    commands[arg]()
