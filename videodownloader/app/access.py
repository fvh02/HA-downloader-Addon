"""Access code for requests from the internet (e.g. through a Cloudflare Tunnel).

The home network, Home Assistant Ingress and other add-ons (such as the Inkbox Claude Gateway)
keep working without a code. Requests that arrive through a proxy or tunnel need the code once;
the browser then keeps a cookie. Without a configured code, internet requests are refused.

This file is identical in the Downloader and Video-Downloader add-ons.
"""

import hashlib
import hmac
import logging
import time
from html import escape

from aiohttp import web

log = logging.getLogger("access")

INGRESS_IP = "172.30.32.2"  # Home Assistant's Ingress proxy (the person is logged in to Home Assistant)
# Cloudflare adds the first two to every request it forwards; other proxies add the last one.
PROXY_HEADERS = ("Cf-Connecting-IP", "Cf-Ray", "X-Forwarded-For")
LOGIN_PATH = "/__login"
TRIES, WINDOW = 8, 900  # wrong codes per address and time window (seconds)


def is_ingress(request: web.Request) -> bool:
    return request.remote == INGRESS_IP and "X-Ingress-Path" in request.headers


def from_internet(request: web.Request) -> bool:
    return not is_ingress(request) and any(h in request.headers for h in PROXY_HEADERS)


def client_ip(request: web.Request) -> str:
    return (request.headers.get("Cf-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote or "?")


class Gate:
    def __init__(self, title: str, code: str | None, theme: str, cookie: str):
        self.title = title
        self.code = (code or "").strip()
        self.theme = theme
        self.cookie = cookie
        self.token = hashlib.sha256(f"{cookie}:{self.code}".encode()).hexdigest() if self.code else ""
        self.failures: dict[str, list[float]] = {}

    def setup(self, app: web.Application) -> None:
        app.middlewares.append(self.middleware)
        app.router.add_post(LOGIN_PATH, self.login)
        if self.code:
            log.info("Zugangscode aktiv für Aufrufe aus dem Internet")
        else:
            log.info("Kein Zugangscode gesetzt: Aufrufe aus dem Internet werden abgewiesen, das Heimnetz ist offen")

    @web.middleware
    async def middleware(self, request: web.Request, handler):
        if not from_internet(request) or request.path == LOGIN_PATH:
            return await handler(request)
        if not self.code:
            return self.page(None, "Noch gesperrt: In der Add-on-Konfiguration muss zuerst ein Zugangscode gesetzt werden.", 403)
        if hmac.compare_digest(request.cookies.get(self.cookie, ""), self.token):
            return await handler(request)
        if request.method == "GET" and ("text/html" in request.headers.get("Accept", "") or request.path.endswith("/")):
            return self.page(request.path_qs)
        raise web.HTTPUnauthorized(text="Zugangscode fehlt")

    async def login(self, request: web.Request) -> web.Response:
        form = await request.post()
        target = str(form.get("next") or "/")
        if not target.startswith("/") or target.startswith("//"):
            target = "/"
        if not from_internet(request):
            return web.Response(status=303, headers={"Location": target})
        if not self.code:
            return self.page(None, "Noch gesperrt: In der Add-on-Konfiguration muss zuerst ein Zugangscode gesetzt werden.", 403)
        ip, now = client_ip(request), time.time()
        tries = [t for t in self.failures.get(ip, []) if now - t < WINDOW]
        self.failures[ip] = tries
        if len(tries) >= TRIES:
            return self.page(target, "Zu viele Versuche – bitte in ein paar Minuten noch einmal.", 429)
        if not hmac.compare_digest(str(form.get("code", "")).strip().encode(), self.code.encode()):
            tries.append(now)
            log.info("Falscher Zugangscode von %s", ip)
            return self.page(target, "Der Code stimmt nicht.")
        self.failures.pop(ip, None)
        response = web.Response(status=303, headers={"Location": target})
        response.set_cookie(self.cookie, self.token, max_age=365 * 86400, path="/", httponly=True,
                            samesite="Lax", secure=True)
        return response

    def page(self, target: str | None, message: str = "", status: int = 401) -> web.Response:
        form = "" if target is None else f"""
      <form method="post" action="{LOGIN_PATH}">
        <input type="hidden" name="next" value="{escape(target, quote=True)}">
        <input name="code" type="password" placeholder="Zugangscode" autocomplete="current-password" autofocus required>
        <p class="err">{escape(message) if target is not None else ""}</p>
        <button type="submit">Weiter</button>
      </form>"""
        intro = message if target is None else "Gib den Zugangscode ein, den du bekommen hast."
        html = f"""<!doctype html>
<html lang="de" data-theme="{self.theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{escape(self.title)}</title>
<style>
  :root {{ --bg: #eef2ff; --card: rgba(255,255,255,.75); --text: #1e1b3a; --muted: #5f5c80; --line: rgba(80,70,140,.2); --a: #7c3aed; --b: #ec4899; --err: #dc2626; }}
  [data-theme="dark"] {{ --bg: #0b0a1f; --card: rgba(255,255,255,.07); --text: #f1f0ff; --muted: #a7a3cf; --line: rgba(255,255,255,.16); --a: #a78bfa; --b: #f472b6; --err: #fb7185; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         color: var(--text); background: radial-gradient(60vmax 60vmax at 0 0, color-mix(in srgb, var(--a) 35%, transparent), transparent),
         radial-gradient(60vmax 60vmax at 100% 100%, color-mix(in srgb, var(--b) 30%, transparent), transparent), var(--bg); }}
  main {{ width: 100%; max-width: 380px; text-align: center; }}
  h1 {{ font-size: 2rem; margin: 0 0 6px; background: linear-gradient(135deg, var(--a), var(--b)); -webkit-background-clip: text; background-clip: text; color: transparent; }}
  p {{ color: var(--muted); margin: 0 0 20px; }}
  form {{ display: flex; flex-direction: column; gap: 12px; padding: 20px; border-radius: 22px; background: var(--card); border: 1px solid var(--line);
          backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); }}
  input {{ font: inherit; font-size: 1.1rem; text-align: center; padding: 12px; border-radius: 14px; border: 1px solid var(--line); background: transparent; color: var(--text); outline: none; }}
  input:focus {{ border-color: var(--a); }}
  button {{ font: inherit; font-weight: 700; padding: 12px; border: 0; border-radius: 14px; color: #fff; cursor: pointer; background: linear-gradient(135deg, var(--a), var(--b)); }}
  .err {{ color: var(--err); font-weight: 600; min-height: 1.2em; margin: 0; }}
</style>
</head>
<body>
  <main>
    <h1>{escape(self.title)}</h1>
    <p>{escape(intro)}</p>{form}
  </main>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html", status=status, headers={"Cache-Control": "no-store"})
