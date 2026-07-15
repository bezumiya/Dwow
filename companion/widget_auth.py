"""One-time authorization of the app on your Discord account (scopes openid +
sdk.social_layer) — required for the widget to appear on your profile.

Before running (once, in the Developer Portal):
  1. OAuth2 → Redirects: add  http://localhost:8917/callback
  2. OAuth2 → Client Secret → Reset Secret → copy it
  3. Paste it into config.json under widget.client_secret

Then:  python widget_auth.py
Opens the browser, you click Authorize, and that's it.
"""
from __future__ import annotations

import http.server
import json
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8917
REDIRECT = f"http://localhost:{PORT}/callback"
SCOPES = "openid sdk.social_layer"

cfg = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))
app_id = str(cfg["application_id"])
secret = (cfg.get("widget") or {}).get("client_secret", "")
if not secret:
    raise SystemExit("Preencha widget.client_secret no config.json (Portal → OAuth2 → Client Secret).")

result: dict = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if query.get("code"):
            result["code"] = query["code"][0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h2>Dwow: autorizado! Pode fechar esta aba.</h2>".encode("utf-8"))

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("localhost", PORT), Handler)
auth_url = (
    "https://discord.com/oauth2/authorize"
    f"?client_id={app_id}&response_type=code"
    f"&redirect_uri={urllib.parse.quote(REDIRECT, safe='')}"
    f"&scope={urllib.parse.quote(SCOPES)}"
)
print("Abrindo o navegador para autorizar… Se não abrir, cole esta URL:")
print(auth_url)
webbrowser.open(auth_url)

while not result.get("code"):
    server.handle_request()

data = urllib.parse.urlencode({
    "client_id": app_id,
    "client_secret": secret,
    "grant_type": "authorization_code",
    "code": result["code"],
    "redirect_uri": REDIRECT,
}).encode()
req = urllib.request.Request(
    "https://discord.com/api/oauth2/token",
    data=data,
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        # without a User-Agent, Discord's Cloudflare answers urllib with 403
        "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 1.0.0)",
    },
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        token = json.loads(resp.read())
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="replace")[:400]
    raise SystemExit(f"Troca de token falhou: HTTP {exc.code} — {body}")

print(f"OK! App autorizado na sua conta (scopes concedidos: {token.get('scope', '?')}).")
print("Agora ative o widget no config.json (widget.enabled: true) e rode main.py.")
