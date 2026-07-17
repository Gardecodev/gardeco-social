#!/usr/bin/env python3
"""
Auth + QA Pinterest API v5 — app « Gardeco Social » (App ID 1580225).

Le `login` déroule le flow OAuth complet : c'est ce flow qu'on filme pour la
demande d'accès Standard (exigence Pinterest : la démo doit montrer le flow
OAuth en entier + une action API réussie).

  python3 pinterest_auth.py login     # navigateur → consentement → tokens
  python3 pinterest_auth.py whoami    # vérifie le token (GET /v5/user_account)
  python3 pinterest_auth.py refresh   # renouvelle l'access token (30 j)
  python3 pinterest_auth.py pin-test  # crée le board + pin de démo (QA / vidéo)
  python3 pinterest_auth.py secrets   # commandes gh pour les secrets GitHub Actions

Environnements — PINTEREST_API_BASE choisit le host (défaut : prod) :
  prod     https://api.pinterest.com          tokens → pinterest-social.json
  sandbox  https://api-sandbox.pinterest.com  tokens → pinterest-social.sandbox.json
⚠️ App en accès Trial : la création de PIN en prod répond 403 (« use API Sandbox »),
les boards passent (et sont publics). Le pin de la démo se fait donc en sandbox :
  PINTEREST_API_BASE=https://api-sandbox.pinterest.com python3 pinterest_auth.py login
  PINTEREST_API_BASE=https://api-sandbox.pinterest.com python3 pinterest_auth.py pin-test

Refresh tokens : rotatifs ~60 j (chaque refresh en émet un nouveau, l'ancien reste
valable jusqu'à SA propre expiration — vérifié le 17-07-2026). Re-poser le secret
GitHub Actions au moins tous les 2 mois (cf. `secrets`).

App ID / App secret : portail dev Pinterest → My apps → Gardeco Social
(copie 1Password : « Gardeco - Pinterest App Secret »). À fournir en env au premier
login ; ensuite relus depuis le fichier de conf (0600).
Le redirect URI http://localhost:8085/ doit être déclaré dans le portail dev.
"""
import base64, json, os, secrets, sys, urllib.request, urllib.parse, urllib.error, webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = os.environ.get("PINTEREST_API_BASE", "https://api.pinterest.com").rstrip("/")
API = BASE + "/v5"
SANDBOX = "sandbox" in BASE
ENV_LABEL = "sandbox" if SANDBOX else "prod"
REDIRECT = "http://localhost:8085/"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
CONF = os.path.expanduser("~/.config/claude-seo/pinterest-social%s.json" % (".sandbox" if SANDBOX else ""))
PROD_CONF = os.path.expanduser("~/.config/claude-seo/pinterest-social.json")

# l'unicité des noms de boards est vérifiée à travers les environnements → nom dédié en sandbox
DEMO_BOARD = {"name": "Robots de piscine — sandbox" if SANDBOX else "Robots de piscine",
              "description": "Robots de piscine sans fil Beatbot — nettoyage fond, parois et ligne d'eau.",
              "privacy": "PUBLIC"}
DEMO_PIN = {"title": "Beatbot Sora P3 — robot de piscine sans fil",
            "description": "Nettoyage 3-en-1 : fond, parois, ligne d'eau. Sans fil, navigation ClearNav, "
                           "jusqu'à 5 h d'autonomie. Livré depuis la Suisse.",
            "link": "https://gardeco.ch/produit/sora-p3",
            "media_source": {"source_type": "image_url",
                             "url": "https://cdn.jsdelivr.net/gh/Gardecodev/gardeco-social@main/media/post-02.jpg"}}


def load_conf(path=None):
    path = path or CONF
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def save_conf(conf):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    json.dump(conf, open(CONF, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.chmod(CONF, 0o600)


def creds(conf):
    # le secret d'app est commun prod/sandbox — retomber sur la conf prod si besoin
    fallback = load_conf(PROD_CONF) if SANDBOX else {}
    app_id = os.environ.get("PINTEREST_APP_ID", "").strip() or conf.get("app_id") or fallback.get("app_id", "")
    secret = os.environ.get("PINTEREST_APP_SECRET", "").strip() or conf.get("app_secret") or fallback.get("app_secret", "")
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
        sys.exit("POST /oauth/token (%s) -> HTTP %s %s" % (ENV_LABEL, e.code, e.read().decode()[:400]))


def bearer_call(method, path, body=None):
    conf = load_conf()
    tok = conf.get("access_token")
    if not tok:
        sys.exit("Pas d'access token %s — lancer d'abord : python3 pinterest_auth.py login" % ENV_LABEL)
    req = urllib.request.Request(API + path,
                                 data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("%s %s (%s) -> HTTP %s %s" % (method, path, ENV_LABEL, e.code, e.read().decode()[:400]))


def store_tokens(conf, app_id, secret, tok):
    now = datetime.now(timezone.utc)
    conf.update({
        "app_id": app_id, "app_secret": secret, "env": ENV_LABEL,
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

    print("1/4  [%s] Ouverture du navigateur (consentement Pinterest)…" % ENV_LABEL)
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
    print("3/4  Code reçu, échange contre les tokens (%s)…" % ENV_LABEL)
    tok = token_call(app_id, secret, {"grant_type": "authorization_code",
                                      "code": got["code"], "redirect_uri": REDIRECT})
    store_tokens(conf, app_id, secret, tok)
    print("     Tokens enregistrés dans %s" % CONF)
    me = bearer_call("GET", "/user_account")
    print("4/4  Authentifié : @%s (%s)" % (me.get("username"), me.get("account_type")))


def cmd_refresh():
    conf = load_conf()
    app_id, secret = creds(conf)
    if not conf.get("refresh_token"):
        sys.exit("Pas de refresh token %s — lancer d'abord : python3 pinterest_auth.py login" % ENV_LABEL)
    tok = token_call(app_id, secret, {"grant_type": "refresh_token",
                                      "refresh_token": conf["refresh_token"]})
    store_tokens(conf, app_id, secret, tok)
    print("Access token %s renouvelé, expire le %s" % (ENV_LABEL, conf["access_expires_at"][:10]))
    if tok.get("refresh_token"):
        print("Nouveau refresh token émis (fenêtre 60 j) — penser à re-poser le secret Actions si utilisé là-bas (cf. `secrets`).")


def cmd_whoami():
    me = bearer_call("GET", "/user_account")
    print("[%s] @%s — type %s" % (ENV_LABEL, me.get("username"), me.get("account_type")))
    conf = load_conf()
    for key, label in (("access_expires_at", "access token"), ("refresh_expires_at", "refresh token")):
        if conf.get(key):
            days = (datetime.fromisoformat(conf[key]) - datetime.now(timezone.utc)).days
            print("%s : expire dans %d j" % (label, days))


def cmd_pin_test():
    """Board + pin de démo (l'« action API » de la vidéo Standard). En Trial,
    les pins ne passent qu'en sandbox — garde-fou pour ne jamais créer un vrai
    pin prod par accident (règle : aucun pin public sans validation Nicolas)."""
    if not SANDBOX and os.environ.get("PIN_TEST_PROD_OK") != "1":
        sys.exit("pin-test en PROD créerait un pin PUBLIC (une fois l'app en Standard).\n"
                 "Pour la démo/QA, passer par le sandbox :\n"
                 "  PINTEREST_API_BASE=https://api-sandbox.pinterest.com python3 pinterest_auth.py pin-test\n"
                 "(ou PIN_TEST_PROD_OK=1 si le pin prod est explicitement validé)")
    boards = bearer_call("GET", "/boards?page_size=50").get("items", [])
    board = next((b for b in boards if b.get("name") == DEMO_BOARD["name"]), None)
    if board:
        print("board existant : %s — %s" % (board["id"], board["name"]))
    else:
        board = bearer_call("POST", "/boards", DEMO_BOARD)
        print("board créé    : %s — %s" % (board["id"], board["name"]))
    pin = bearer_call("POST", "/pins", dict(DEMO_PIN, board_id=board["id"]))
    print("pin créé      : %s (env %s)" % (pin["id"], ENV_LABEL))
    if SANDBOX:
        print("→ visible uniquement par nous (entité sandbox), en étant connecté au compte.")


def cmd_secrets():
    conf = load_conf(PROD_CONF)  # Actions publie en prod — toujours la conf prod
    if not conf.get("refresh_token"):
        sys.exit("Pas de tokens prod — lancer d'abord : python3 pinterest_auth.py login")
    print("À poser sur Gardecodev/gardeco-social (gh auth switch --user Gardecodev d'abord) :")
    for name, key in (("PINTEREST_APP_ID", "app_id"), ("PINTEREST_APP_SECRET", "app_secret"),
                      ("PINTEREST_REFRESH_TOKEN", "refresh_token")):
        print("  gh secret set %s --repo Gardecodev/gardeco-social --body '%s'" % (name, conf.get(key, "")))
    if conf.get("refresh_expires_at"):
        print("⚠️ refresh token valable jusqu'au %s — re-poser avant." % conf["refresh_expires_at"][:10])


if __name__ == "__main__":
    commands = {"login": cmd_login, "refresh": cmd_refresh, "whoami": cmd_whoami,
                "pin-test": cmd_pin_test, "secrets": cmd_secrets}
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg not in commands:
        sys.exit(__doc__.strip())
    commands[arg]()
