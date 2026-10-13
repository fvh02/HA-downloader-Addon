"""Finds videos on web pages that yt-dlp does not know.

1. Page scan: load the page and look for <video>/<source>, og:video, JSON-LD, direct MP4/HLS/DASH
   links and embedded players (iframes).
2. Browser scan: open the page in a headless Chromium, start the player and catch the video
   requests (HLS/DASH playlists, MP4/WebM files) – this also works for players that load the video
   with JavaScript.

Everything uses the same proxy as the downloads, so with the VPN switched on nothing goes past it.
DRM-protected streams (Netflix, Disney+ …) cannot be downloaded.
"""

import html as htmllib
import json
import logging
import re
import threading
import time
from urllib.parse import urljoin, urlparse

log = logging.getLogger("finder")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0.0.0 Safari/537.36")
MEDIA_EXT = (".m3u8", ".mpd", ".mp4", ".webm", ".m4v", ".mov", ".mkv")
MEDIA_TYPES = ("video/", "application/vnd.apple.mpegurl", "application/x-mpegurl", "application/dash+xml")
ADS = ("doubleclick", "googlesyndication", "googleads", "adservice", "imasdk", "adnxs", "/ads/", "advert",
       "/vast", "preroll", "pubmatic", "spotx", "teads", "outbrain", "taboola", "criteo")
MEDIA_IN_TEXT = re.compile(r"""((?:https?:)?\\?/\\?/[^"'()\s<>\\]+?\.(?:m3u8|mpd|mp4|webm|m4v|mov)(?:\?[^"'()\s<>\\]*)?)""", re.I)
browser_lock = threading.Lock()   # one browser at a time (memory)


def is_ad(url: str) -> bool:
    low = url.lower()
    return any(a in low for a in ADS)


def media_kind(url: str) -> str:
    path = urlparse(url).path.lower()
    return next((ext for ext in MEDIA_EXT if path.endswith(ext)), "")


def rank(urls: list[str]) -> list[str]:
    """Best first: HLS/DASH playlists (master before others), then whole files; no ads or segments."""
    seen, out = set(), []
    for u in urls:
        if u in seen or is_ad(u) or not u.startswith(("http://", "https://")):
            continue
        seen.add(u)
        out.append(u)

    def score(u: str) -> tuple:
        kind, low = media_kind(u), u.lower()
        if kind == ".m3u8":
            base = 0 if ("master" in low or "index" in low or "playlist" in low) else 1
        elif kind == ".mpd":
            base = 2
        elif kind:
            base = 3
        else:
            base = 4          # a media request without a known extension (seen in the browser)
        segment = any(s in low for s in ("segment", "chunk", "/seg-", "frag", "init."))
        return (segment, base)

    return sorted(out, key=score)


def scan_html(text: str, base: str) -> dict:
    """Video links, embedded players and the title of a page."""
    def attr(tag_re: str, name: str) -> list[str]:
        found = []
        for tag in re.findall(tag_re, text, re.I | re.S):
            m = re.search(rf"""\b{name}\s*=\s*["']([^"']+)["']""", tag, re.I)
            if m:
                found.append(urljoin(base, htmllib.unescape(m.group(1).strip())))
        return found

    media = attr(r"<video\b[^>]*>", "src") + attr(r"<source\b[^>]*>", "src")
    for prop in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"):
        for m in re.finditer(rf"""<meta[^>]+(?:property|name)\s*=\s*["']{re.escape(prop)}["'][^>]*>""", text, re.I):
            c = re.search(r"""content\s*=\s*["']([^"']+)["']""", m.group(0), re.I)
            if c:
                media.append(urljoin(base, htmllib.unescape(c.group(1))))
    for block in re.findall(r"""<script[^>]+application/ld\+json[^>]*>(.*?)</script>""", text, re.I | re.S):
        for m in re.finditer(r'"contentUrl"\s*:\s*"([^"]+)"', block):
            media.append(urljoin(base, m.group(1).replace("\\/", "/")))
    for m in MEDIA_IN_TEXT.finditer(text):
        url = m.group(1).replace("\\/", "/")
        media.append(("https:" + url) if url.startswith("//") else url)
    iframes = [u for u in attr(r"<iframe\b[^>]*>", "src") if u.startswith(("http://", "https://")) and not is_ad(u)]
    title = ""
    for pattern in (r"""<meta[^>]+property\s*=\s*["']og:title["'][^>]*content\s*=\s*["']([^"']+)""",
                    r"<title[^>]*>(.*?)</title>"):
        m = re.search(pattern, text, re.I | re.S)
        if m:
            title = htmllib.unescape(" ".join(m.group(1).split()))[:200]
            break
    return {"media": rank([u for u in media if media_kind(u) or "video" in u.lower()]), "iframes": iframes[:5], "title": title}


def fetch_page(url: str, ydl_options: dict) -> tuple[str, str]:
    """HTML and final address of a page, through yt-dlp's networking (same proxy as the downloads)."""
    import yt_dlp
    from yt_dlp.networking import Request
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "socket_timeout": 20, **ydl_options}) as ydl:
        with ydl.urlopen(Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})) as resp:
            raw = resp.read(6_000_000)
            charset = "utf-8"
            ctype = resp.headers.get("Content-Type", "")
            if "charset=" in ctype:
                charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
            return raw.decode(charset, "replace"), resp.url


def browser_scan(url: str, proxy: str | None, wait: float = 25) -> dict:
    """Opens the page in headless Chromium and records the video requests while the player starts."""
    try:
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"media": [], "title": "", "headers": {}, "error": "Browser-Suche nicht verfügbar"}
    found: list[str] = []
    args = ["--autoplay-policy=no-user-gesture-required", "--mute-audio", "--disable-quic",
            # never let WebRTC talk to the internet past the proxy
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--webrtc-ip-handling-policy=disable_non_proxied_udp"]
    with browser_lock, sync_playwright() as p:
        browser = p.chromium.launch(args=args, proxy={"server": proxy.replace("socks5h://", "socks5://")} if proxy else None)
        try:
            context = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 800}, locale="de-DE")
            page = context.new_page()

            def on_request(req):
                u = req.url
                if media_kind(u) or req.resource_type == "media":
                    found.append(u)

            def on_response(resp):
                ctype = (resp.headers.get("content-type") or "").lower()
                if any(ctype.startswith(t) for t in MEDIA_TYPES):
                    found.append(resp.url)

            page.on("request", on_request)
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
            except PWError as err:
                return {"media": [], "title": "", "headers": {}, "error": f"Seite nicht erreichbar: {str(err)[:120]}"}
            play = """() => {
                document.querySelectorAll('video').forEach(v => { v.muted = true; v.play().catch(() => {}); });
                for (const sel of ['.vjs-big-play-button', '.jw-display-icon-container', '.plyr__control--overlaid',
                                   'button[aria-label*="play" i]', 'button[title*="play" i]', '[class*="play-button"]',
                                   '[class*="playButton"]', '[class*="big-play"]']) {
                  const el = document.querySelector(sel); if (el) { try { el.click(); } catch (e) {} }
                }
            }"""
            end = time.time() + wait
            clicked = 0
            while time.time() < end:
                if clicked < 3:
                    for frame in page.frames:
                        try:
                            frame.evaluate(play)
                        except PWError:
                            pass
                    clicked += 1
                page.wait_for_timeout(1500)
                if any(media_kind(u) in (".m3u8", ".mpd") for u in found) or any(media_kind(u) in (".mp4", ".webm") for u in found if not is_ad(u)):
                    page.wait_for_timeout(1500)     # let the player pick its main stream
                    break
            title = ""
            try:
                title = page.title()[:200]
            except PWError:
                pass
            media = rank(found)
            headers = {"User-Agent": UA, "Referer": page.url}
            if media:
                cookies = context.cookies([media[0]])
                if cookies:
                    headers["Cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            return {"media": media, "title": title, "headers": headers}
        finally:
            browser.close()


def describe(result: dict) -> str:
    return json.dumps({k: (v[:3] if isinstance(v, list) else v) for k, v in result.items() if k != "headers"}, ensure_ascii=False)[:400]
