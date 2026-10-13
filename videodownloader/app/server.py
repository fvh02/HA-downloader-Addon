"""Video-Downloader add-on: queue for online videos (yt-dlp) plus a media library."""

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from aiohttp import ClientSession, ClientTimeout, web

import finder
import vpn
from access import Gate, is_ingress

OPTIONS_FILE = Path("/data/options.json")
DATA_DIR = Path(os.environ.get("VIDEO_DATA", "/data"))
STATE_FILE = DATA_DIR / "queue.json"
LIBRARY_FILE = DATA_DIR / "library.json"
THUMB_DIR = DATA_DIR / "thumbs"
COOKIE_FILE = DATA_DIR / "youtube-cookies.txt"   # YouTube login (cookies.txt), for Premium and age/member content
tunnel = vpn.VPN(DATA_DIR)                          # optional Proton VPN for the downloads
STATIC_DIR = Path(__file__).parent / "static"
PORT = int(os.environ.get("VIDEO_PORT", "8097"))

QUALITIES = {
    "best": "Beste Qualität",
    "2160": "4K (2160p)",
    "1440": "1440p",
    "1080": "1080p",
    "720": "720p",
    "480": "480p",
    "360": "360p",
    "audio": "Nur Audio (MP3)",
}
QUALITY_SUFFIX = {q: f" {q}p" for q in QUALITIES if q.isdigit()} | {"audio": " (Audio)"}
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}
AUDIO_EXT = {".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac", ".aac"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("video")


def load_options() -> dict:
    try:
        return json.loads(OPTIONS_FILE.read_text())
    except (OSError, ValueError):
        return {}


OPTIONS = load_options()
DOWNLOAD_DIR = Path(os.environ.get("VIDEO_DIR") or OPTIONS.get("download_dir") or "/media/videos")
DESIGN = os.environ.get("VIDEO_DESIGN") or OPTIONS.get("design") or "glass"
THEME = os.environ.get("VIDEO_THEME") or OPTIONS.get("theme") or "dark"
DEFAULT_QUALITY = os.environ.get("VIDEO_QUALITY") or OPTIONS.get("quality") or "best"
if DESIGN not in ("modern", "terminal", "glass"):
    DESIGN = "glass"
if THEME not in ("dark", "light"):
    THEME = "dark"
if DEFAULT_QUALITY not in QUALITIES:
    DEFAULT_QUALITY = "best"


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(path)
    except OSError as err:
        log.warning("Konnte %s nicht speichern: %s", path.name, err)


def format_selector(quality: str) -> str:
    if quality == "audio":
        return "bestaudio/best"
    if quality == "best":
        return "bestvideo*+bestaudio/best"
    return f"bestvideo*[height<={quality}]+bestaudio/best[height<={quality}]/best"


def estimate_size(info: dict, quality: str) -> int | None:
    """Rough size of the chosen quality from the format list (yt-dlp gives exact or approximate sizes)."""
    formats = info.get("formats") or []

    def size(f):
        return (f.get("filesize") or f.get("filesize_approx") or 0) if f else 0

    audio = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    best_audio = max(audio, key=lambda f: f.get("abr") or f.get("tbr") or 0, default=None)
    if quality == "audio":
        return size(best_audio) or size(info) or None
    limit = 10_000 if quality == "best" else int(quality)
    video = [f for f in formats if f.get("vcodec") not in (None, "none") and (f.get("height") or 0) <= limit]
    if not video:
        return size(info) or None
    best_video = max(video, key=lambda f: ((f.get("height") or 0), f.get("tbr") or 0))
    total = size(best_video)
    if best_video.get("acodec") in (None, "none") and best_audio:
        total += size(best_audio)
    return total or None


class Cancelled(Exception):
    pass


# -- YouTube account (cookies) --------------------------------------------------
# YouTube no longer lets programs log in with e-mail and password; yt-dlp uses the login cookies of a
# browser instead. They are uploaded once through Home Assistant and stay in /data (never shown again).
AUTH_COOKIES = {"SAPISID", "__Secure-3PAPISID", "__Secure-1PSID", "__Secure-3PSID", "SID", "LOGIN_INFO"}
youtube_state: dict = {"checked": 0.0, "ok": None, "message": ""}


def parse_cookies(text: str) -> list[list[str]]:
    """Netscape cookies.txt lines for youtube.com / google.com."""
    rows = []
    for line in text.splitlines():
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) == 7 and (parts[0].endswith("youtube.com") or parts[0].endswith("google.com")):
            rows.append(parts)
    return rows


def cookie_info() -> dict:
    try:
        rows = parse_cookies(COOKIE_FILE.read_text())
    except OSError:
        return {"connected": False}
    auth = [r for r in rows if r[5] in AUTH_COOKIES and r[0].endswith("youtube.com")]
    expiry = [int(r[4]) for r in auth if r[4].isdigit() and int(r[4]) > 0]
    return {"connected": bool(auth), "since": COOKIE_FILE.stat().st_mtime,
            "expires": min(expiry) if expiry else None, "ok": youtube_state["ok"], "message": youtube_state["message"],
            "checked": youtube_state["checked"] or None}


def ydl_auth() -> dict:
    """yt-dlp options for the YouTube login. Each run gets its own copy, so parallel runs never
    write the file at the same time and a broken run cannot damage the saved login."""
    if not COOKIE_FILE.exists():
        return {}
    copy = DATA_DIR / f".cookies-{uuid.uuid4().hex}.txt"
    try:
        shutil.copyfile(COOKIE_FILE, copy)
        os.chmod(copy, 0o600)
    except OSError:
        return {}
    return {"cookiefile": str(copy)}


def drop_auth(opts: dict) -> None:
    if opts.get("cookiefile"):
        Path(opts["cookiefile"]).unlink(missing_ok=True)


def check_youtube() -> tuple[bool, str]:
    """Logged in? The "Watch later" list only opens with a valid login."""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True, "playlistend": 1,
            **ydl_auth(), **tunnel.ydl_options()}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info("https://www.youtube.com/playlist?list=WL", download=False)
        return True, "Angemeldet – Premium-Inhalte und Premium-Qualität sind verfügbar"
    except Exception as err:  # noqa: BLE001
        text = clean_error(err)
        if "sign in" in text.lower() or "login" in text.lower() or "private" in text.lower() or "does not exist" in text.lower():
            return False, "YouTube nimmt die Anmeldung nicht (mehr) an – bitte die Cookies neu exportieren"
        return False, f"Prüfung fehlgeschlagen: {text[:160]}"
    finally:
        drop_auth(opts)


class VideoQueue:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.library: dict[str, dict] = {}  # relative path -> metadata
        self.wakeup = asyncio.Event()
        self.current: dict | None = None

    # -- persistence -----------------------------------------------------------
    def load(self) -> None:
        self.items = read_json(STATE_FILE, [])
        for item in self.items:
            if item["status"] in ("downloading", "processing", "probing"):
                item.update(status="queued", downloaded=0, speed=0, eta=None)
        self.library = read_json(LIBRARY_FILE, {})

    def save(self) -> None:
        write_json(STATE_FILE, [{k: v for k, v in i.items() if not k.startswith("_")} for i in self.items])

    def save_library(self) -> None:
        write_json(LIBRARY_FILE, self.library)

    def get(self, item_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    # -- queue -----------------------------------------------------------------
    def add(self, url: str, quality: str) -> dict:
        item = {
            "id": uuid.uuid4().hex, "url": url, "quality": quality,
            "title": urlparse(url).netloc + urlparse(url).path, "thumbnail": None, "duration": None,
            "uploader": None, "site": None, "heights": [], "sizes": {}, "size": None,
            "downloaded": 0, "total": None, "speed": 0, "eta": None,
            "status": "probing", "error": None, "file": None, "added": time.time(),
        }
        self.items.append(item)
        self.save()
        asyncio.create_task(self.probe(item))
        return item

    def set_quality(self, item_id: str, quality: str) -> dict:
        item = self.get(item_id)
        if not item:
            raise web.HTTPNotFound()
        if item["status"] not in ("queued", "probing", "error"):
            raise web.HTTPConflict(text="Die Qualität lässt sich nur vor dem Download ändern")
        item["quality"] = quality
        item["size"] = item["sizes"].get(quality)
        if item["status"] == "error":
            item.update(status="queued", error=None)
            self.wakeup.set()
        self.save()
        return item

    def remove(self, item_id: str) -> bool:
        item = self.get(item_id)
        if not item:
            return False
        item["_cancel"] = True
        self.items.remove(item)
        self.save()
        return True

    def clear_finished(self) -> None:
        self.items = [i for i in self.items if i["status"] not in ("done", "error")]
        self.save()

    # -- probing ---------------------------------------------------------------
    async def probe(self, item: dict) -> None:
        if not await tunnel.wait_ready(timeout=60):
            if item in self.items:
                item.update(status="error", error="VPN nicht verbunden – nichts abgerufen (Kill-Switch). Später erneut versuchen.")
                self.save()
            return

        def extract(url: str, headers: dict | None = None):
            opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist", "noplaylist": True,
                    **ydl_auth(), **tunnel.ydl_options()}
            if headers:
                opts["http_headers"] = headers
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.sanitize_info(ydl.extract_info(url, download=False))
            finally:
                drop_auth(opts)

        try:
            info = await asyncio.to_thread(extract, item["url"])
        except Exception as err:  # noqa: BLE001
            # Not a site yt-dlp knows: look for the video on the page itself.
            info = await self.discover(item, extract) if unsupported(err) else None
            if info is None:
                if item in self.items:
                    item.update(status="error", error=item.pop("_why", None) or clean_error(err))
                    self.save()
                return
        if item not in self.items:
            return
        if info.get("_type") == "playlist":
            # A playlist link becomes one queue entry per video.
            entries = [e for e in (info.get("entries") or []) if e.get("url") or e.get("webpage_url")][:200]
            index = self.items.index(item)
            self.items.remove(item)
            for offset, entry in enumerate(entries):
                child = self.add(entry.get("webpage_url") or entry["url"], item["quality"])
                self.items.remove(child)
                self.items.insert(index + offset, child)
            self.save()
            return
        try:
            self._apply_probe(item, info)
        except Exception as err:  # noqa: BLE001 – never leave an entry stuck in "probing"
            log.warning("Auswertung fehlgeschlagen für %s: %s", item["url"], err)
            if item["status"] == "probing":
                item["status"] = "queued"
        self.save()
        self.wakeup.set()

    async def discover(self, item: dict, extract) -> dict | None:
        """Page scan, then browser scan (both through the VPN when it is on). Sets item["source"]."""
        page_url = item["url"]
        item["note"] = "suche das Video auf der Seite …"
        self.save()
        title = ""
        try:
            text, final = await asyncio.to_thread(finder.fetch_page, page_url, tunnel.ydl_options())
            found = finder.scan_html(text, final)
            title = found["title"]
            # Embedded players (e.g. Vimeo, Dailymotion) are often known to yt-dlp.
            for frame in found["iframes"]:
                try:
                    info = await asyncio.to_thread(extract, frame, {"Referer": final})
                    item["source"] = {"url": frame, "headers": {"Referer": final}, "how": "eingebetteter Player"}
                    return self._discovered(item, info, title)
                except Exception:  # noqa: BLE001
                    continue
            for media in found["media"][:4]:
                headers = {"Referer": final, "User-Agent": finder.UA}
                try:
                    info = await asyncio.to_thread(extract, media, headers)
                    item["source"] = {"url": media, "headers": headers, "how": "Video-Link auf der Seite"}
                    return self._discovered(item, info, title)
                except Exception:  # noqa: BLE001
                    continue
        except Exception as err:  # noqa: BLE001
            log.info("Seiten-Scan fehlgeschlagen für %s: %s", page_url, str(err)[:160])
        if not await tunnel.wait_ready(timeout=60):
            item["_why"] = "VPN nicht verbunden – nichts abgerufen (Kill-Switch)"
            return None
        item["note"] = "öffne die Seite im Browser und starte den Player …"
        self.save()
        try:
            result = await asyncio.to_thread(finder.browser_scan, page_url, tunnel.ydl_options().get("proxy"))
        except Exception as err:  # noqa: BLE001
            log.warning("Browser-Scan fehlgeschlagen für %s: %s", page_url, err)
            result = {"media": [], "error": "Browser-Suche fehlgeschlagen"}
        log.info("Browser-Scan %s: %s", page_url, finder.describe(result))
        for media in result.get("media", [])[:5]:
            try:
                info = await asyncio.to_thread(extract, media, result["headers"])
                item["source"] = {"url": media, "headers": result["headers"], "how": "im Browser gefunden"}
                return self._discovered(item, info, result.get("title") or title)
            except Exception:  # noqa: BLE001
                continue
        item.pop("note", None)
        item["_why"] = (result.get("error") or "Auf dieser Seite wurde kein Video gefunden "
                        "(oder es ist kopiergeschützt, z. B. Netflix/Disney+)")
        return None

    def _discovered(self, item: dict, info: dict, title: str) -> dict:
        item.pop("note", None)
        if title and (not info.get("title") or info.get("extractor_key") == "Generic" or info.get("title") in ("index", "master", "playlist")):
            info["title"] = title
        info.setdefault("webpage_url", item["url"])
        log.info("Video gefunden (%s): %s", item["source"]["how"], item["source"]["url"][:200])
        return info

    def _apply_probe(self, item: dict, info: dict) -> None:
        heights = sorted({f.get("height") for f in info.get("formats") or [] if f.get("height")}, reverse=True)
        item.update(
            title=info.get("title") or item["title"], thumbnail=info.get("thumbnail"),
            duration=info.get("duration"), uploader=info.get("uploader") or info.get("channel"),
            site=info.get("extractor_key"), heights=heights,
            sizes={q: estimate_size(info, q) for q in QUALITIES},
        )
        item["size"] = item["sizes"].get(item["quality"])
        if item["status"] == "probing":
            item["status"] = "queued"

    # -- downloading -----------------------------------------------------------
    def _download(self, item: dict) -> str:
        """Runs in a worker thread. Returns the path of the finished file."""
        parts: dict[str, tuple[int, int]] = {}
        result: dict = {}
        last = [0.0]

        def progress(d):
            if item.get("_cancel"):
                raise Cancelled()
            name = d.get("tmpfilename") or d.get("filename") or "?"
            item.setdefault("_tmp", set()).add(name)
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                parts[name] = (d.get("downloaded_bytes") or 0, total)
                now = time.monotonic()
                if now - last[0] >= 0.5:
                    last[0] = now
                    done = sum(p[0] for p in parts.values())
                    known = sum(p[1] for p in parts.values())
                    item.update(downloaded=done, total=max(known, item.get("size") or 0) or None,
                                speed=int(d.get("speed") or 0), eta=d.get("eta"))
            elif d["status"] == "finished":
                size = (d.get("total_bytes") or d.get("downloaded_bytes") or 0)
                parts[name] = (size, size)

        def postprocess(d):
            if item.get("_cancel"):
                raise Cancelled()
            if d["status"] == "started":
                item.update(status="processing", speed=0, eta=None)
            if d["status"] == "finished" and d.get("info_dict", {}).get("filepath"):
                result["path"] = d["info_dict"]["filepath"]

        quality = item["quality"]
        opts = {
            "quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
            "format": format_selector(quality),
            # Each quality gets its own name, so downloads of the same video never replace each other
            # (audio extraction deletes its intermediate file, which must not be another download).
            "outtmpl": str(DOWNLOAD_DIR / ("%(title).150B [%(id)s]" + QUALITY_SUFFIX.get(quality, "") + ".%(ext)s")),
            "progress_hooks": [progress], "postprocessor_hooks": [postprocess],
            "windowsfilenames": True, "overwrites": False, "continuedl": True, **ydl_auth(), **tunnel.ydl_options(),
        }
        if quality == "audio":
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
        else:
            opts["merge_output_format"] = "mp4"
        try:
            return self._run(opts, item, result, quality)
        finally:
            drop_auth(opts)

    def _run(self, opts: dict, item: dict, result: dict, quality: str):
        source = item.get("source") or {}
        if source.get("headers"):
            opts["http_headers"] = source["headers"]
        if source and item.get("title"):
            # Found on a page: name the file after the page, not after "master.m3u8".
            name = yt_dlp.utils.sanitize_filename(item["title"], restricted=False)[:150]
            opts["outtmpl"] = opts["outtmpl"].replace("%(title).150B", name.replace("%", "%%"))
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source.get("url") or item["url"], download=True)
            if item.get("title") and (info.get("extractor_key") == "Generic" or source):
                info["title"] = item["title"]
            path = result.get("path")
            if not path:
                downloads = info.get("requested_downloads") or []
                path = downloads[0].get("filepath") if downloads else ydl.prepare_filename(info)
            meta = {
                "title": info.get("title"), "url": item["url"], "uploader": info.get("uploader") or info.get("channel"),
                "duration": info.get("duration"), "thumbnail": info.get("thumbnail"), "site": info.get("extractor_key"),
                "added": time.time(), "quality": quality,
            }
            return path, meta

    def _cleanup_partial(self, item: dict) -> None:
        """Remove what a cancelled or failed download left behind (partial and per-stream files)."""
        for name in item.get("_tmp", ()):
            for candidate in (Path(name), Path(name + ".part"), Path(name + ".ytdl"), Path(name.removesuffix(".part"))):
                if is_partial(candidate.name):
                    try:
                        candidate.unlink(missing_ok=True)
                    except OSError:
                        pass

    async def worker(self) -> None:
        while True:
            item = next((i for i in self.items if i["status"] == "queued"), None)
            if not item:
                self.wakeup.clear()
                await self.wakeup.wait()
                continue
            if not await tunnel.wait_ready():
                # VPN switched on but down: wait instead of using the home connection.
                item["note"] = "wartet auf das VPN …"
                self.save()
                await asyncio.sleep(15)
                continue
            item.pop("note", None)
            item.update(status="downloading", downloaded=0, speed=0, eta=None, error=None)
            self.current = item
            self.save()
            try:
                DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
                path, meta = await asyncio.to_thread(self._download, item)
                rel = str(Path(path).resolve().relative_to(DOWNLOAD_DIR.resolve()))
                self.library[rel] = meta
                self.save_library()
                item.update(status="done", file=rel, speed=0, eta=None)
                try:
                    item["size"] = item["downloaded"] = Path(path).stat().st_size
                except OSError:
                    pass
                log.info("Fertig: %s", rel)
            except Exception as err:  # noqa: BLE001
                cancelled = isinstance(err, Cancelled) or "Cancelled" in type(err).__name__ or item.get("_cancel")
                self._cleanup_partial(item)
                if cancelled:
                    log.info("Abgebrochen: %s", item["title"])
                else:
                    item.update(status="error", error=clean_error(err), speed=0, eta=None)
                    log.warning("Fehler bei %s: %s", item["url"], err)
            finally:
                self.current = None
                self.save()


def is_partial(name: str) -> bool:
    """yt-dlp's temporary files: *.part, *.ytdl and separate streams like 'Title [id].f137.mp4'."""
    return name.endswith((".part", ".ytdl")) or ".part-Frag" in name or bool(re.search(r"\.f\d+[\w-]*\.\w+$", name)) or ".temp." in name


def unsupported(err: Exception) -> bool:
    """yt-dlp does not know the site, or found no video on it."""
    text = str(err).lower()
    return any(t in text for t in ("unsupported url", "no video formats found", "no media found", "unable to extract"))


def clean_error(err: Exception) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(err)).replace("ERROR: ", "").strip()
    return text[:300] or type(err).__name__


# -- library -------------------------------------------------------------------
def encode(rel: str) -> str:
    return base64.urlsafe_b64encode(rel.encode()).decode().rstrip("=")


def decode(token: str) -> Path:
    try:
        rel = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        raise web.HTTPNotFound()
    path = (DOWNLOAD_DIR / rel).resolve()
    if DOWNLOAD_DIR.resolve() not in path.parents or not path.is_file():
        raise web.HTTPNotFound()
    return path


def probe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return float(out) if out else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def library_list(queue: VideoQueue) -> list[dict]:
    if not DOWNLOAD_DIR.exists():
        return []
    entries = []
    changed = False
    for path in DOWNLOAD_DIR.rglob("*"):
        ext = path.suffix.lower()
        if not path.is_file() or ext not in VIDEO_EXT | AUDIO_EXT or is_partial(path.name):
            continue
        rel = str(path.relative_to(DOWNLOAD_DIR))
        meta = queue.library.get(rel)
        stat = path.stat()
        if meta is None:
            meta = queue.library[rel] = {"title": None, "added": stat.st_mtime}
            changed = True
        if meta.get("duration") is None and not meta.get("_probed"):
            meta["duration"] = probe_duration(path)
            meta["_probed"] = True
            changed = True
        entries.append({
            "id": encode(rel), "path": rel, "name": path.name,
            "title": meta.get("title") or path.stem, "uploader": meta.get("uploader"), "site": meta.get("site"),
            "url": meta.get("url"), "duration": meta.get("duration"), "size": stat.st_size,
            "added": meta.get("added") or stat.st_mtime, "kind": "audio" if ext in AUDIO_EXT else "video",
            "ext": ext.lstrip("."),
        })
    if changed:
        queue.save_library()
    return entries


async def fetch_image(url: str, session: ClientSession) -> bytes | None:
    """A preview image: through the VPN when it is on (never directly then), otherwise directly."""
    if not str(url).startswith(("http://", "https://")):
        return None
    if tunnel.enabled:
        if not await tunnel.wait_ready():
            return None

        def get():
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "socket_timeout": 20, **tunnel.ydl_options()}) as ydl:
                with ydl.urlopen(url) as resp:
                    return resp.read(5_000_000)
        try:
            return await asyncio.to_thread(get)
        except Exception:  # noqa: BLE001
            return None
    try:
        async with session.get(url, timeout=ClientTimeout(total=20)) as resp:
            return await resp.read() if resp.status == 200 else None
    except Exception:  # noqa: BLE001
        return None


async def make_thumb(queue: VideoQueue, path: Path, session: ClientSession) -> Path | None:
    rel = str(path.relative_to(DOWNLOAD_DIR))
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    target = THUMB_DIR / (hashlib.sha1(rel.encode()).hexdigest() + ".jpg")
    if target.exists():
        return target
    meta = queue.library.get(rel) or {}
    data = await fetch_image(meta["thumbnail"], session) if meta.get("thumbnail") else None
    if data:
        raw = target.with_suffix(".src")
        raw.write_bytes(data)
        # normalise (webp etc.) to a small jpeg
        await asyncio.to_thread(subprocess.run, ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-vf", "scale=480:-2", str(target)], timeout=30)
        raw.unlink(missing_ok=True)
        if target.exists():
            return target
    if path.suffix.lower() in VIDEO_EXT:
        at = max(1.0, (meta.get("duration") or 10) * 0.1)
        await asyncio.to_thread(subprocess.run, ["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-vf", "scale=480:-2", str(target)], timeout=60)
        if target.exists():
            return target
    return None


# -- HTTP ----------------------------------------------------------------------
routes = web.RouteTableDef()


def page(name: str) -> web.Response:
    html = (STATIC_DIR / name).read_text(encoding="utf-8")
    html = html.replace("<html ", f'<html data-theme="{THEME}" data-design="{DESIGN}" ', 1)
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"})


def public(item: dict) -> dict:
    data = {k: v for k, v in item.items() if not k.startswith("_")}
    if tunnel.enabled and data.get("thumbnail"):
        data["thumbnail"] = f"api/preview/{item['id']}"     # fetched through the VPN, not by the browser
    return data


@routes.get("/")
async def downloader_page(_):
    return page("downloader.html")


@routes.get("/mediathek")
async def mediathek_redirect(_):
    raise web.HTTPFound("mediathek/")


@routes.get("/mediathek/")
async def mediathek_page(_):
    return page("mediathek.html")


@routes.get("/api/items")
async def list_items(request):
    queue: VideoQueue = request.app["queue"]
    return web.json_response({
        "items": [public(i) for i in queue.items], "directory": str(DOWNLOAD_DIR),
        "qualities": QUALITIES, "default_quality": DEFAULT_QUALITY,
    })


@routes.post("/api/items")
async def add_items(request):
    queue: VideoQueue = request.app["queue"]
    try:
        data = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="Ungültige Anfrage")
    quality = str(data.get("quality") or DEFAULT_QUALITY)
    if quality not in QUALITIES:
        raise web.HTTPBadRequest(text="Unbekannte Qualität")
    urls = [u for u in re.split(r"\s+", str(data.get("url", ""))) if u]
    if not urls:
        raise web.HTTPBadRequest(text="Bitte einen Link eingeben")
    bad = [u for u in urls if urlparse(u).scheme not in ("http", "https") or not urlparse(u).netloc]
    if bad:
        raise web.HTTPBadRequest(text=f"Ungültiger Link: {bad[0]}")
    return web.json_response({"items": [public(queue.add(u, quality)) for u in urls]}, status=201)


@routes.patch("/api/items/{item_id}")
async def update_item(request):
    queue: VideoQueue = request.app["queue"]
    data = await request.json()
    quality = str(data.get("quality"))
    if quality not in QUALITIES:
        raise web.HTTPBadRequest(text="Unbekannte Qualität")
    return web.json_response(public(queue.set_quality(request.match_info["item_id"], quality)))


@routes.delete("/api/items/{item_id}")
async def delete_item(request):
    if not request.app["queue"].remove(request.match_info["item_id"]):
        raise web.HTTPNotFound()
    return web.Response(status=204)


@routes.post("/api/clear")
async def clear(request):
    request.app["queue"].clear_finished()
    return web.Response(status=204)


@routes.get("/api/status")
async def status(request):
    queue: VideoQueue = request.app["queue"]
    active = queue.current
    queued = [i for i in queue.items if i["status"] in ("queued", "probing")]
    lines = []
    if active:
        pct = f" {int(active['downloaded'] * 100 / active['total'])} %" if active.get("total") else ""
        lines.append(f"⬇️ {active['title']}{pct}")
    if queued:
        lines.append(f"⏳ {len(queued)} in der Warteschlange")
    done = sum(1 for i in queue.items if i["status"] == "done")
    if done:
        lines.append(f"✅ {done} fertig")
    return web.json_response({"summary": "\n".join(lines) or "Keine Videos in der Warteschlange.",
                              "items": [public(i) for i in queue.items]})


@routes.get("/api/preview/{item_id}")
async def preview(request):
    queue: VideoQueue = request.app["queue"]
    item = queue.get(request.match_info["item_id"])
    if not item or not item.get("thumbnail"):
        raise web.HTTPNotFound()
    cache = request.app.setdefault("previews", {})
    data = cache.get(item["id"]) or await fetch_image(item["thumbnail"], request.app["session"])
    if not data:
        raise web.HTTPNotFound()
    cache[item["id"]] = data
    while len(cache) > 100:
        cache.pop(next(iter(cache)))
    return web.Response(body=data, content_type="image/jpeg" if data[:2] == b"\xff\xd8" else "image/webp",
                        headers={"Cache-Control": "max-age=86400"})


@routes.get("/api/vpn")
async def vpn_status(request):
    return web.json_response({**tunnel.info(), "can_edit": is_ingress(request)})


@routes.post("/api/vpn")
async def vpn_upload(request):
    """Upload the WireGuard file from Proton (Home Assistant only: it contains a private key)."""
    if not is_ingress(request):
        return web.json_response({"error": "Das VPN lässt sich nur in Home Assistant einrichten"}, status=403)
    text = ""
    if request.content_type.startswith("multipart/"):
        async for part in await request.multipart():
            if part.name == "file":
                text = (await part.read(decode=False))[:100_000].decode("utf-8", "replace")
    else:
        text = (await request.text())[:100_000]
    try:
        return web.json_response(await tunnel.install(text))
    except vpn.VPNError as err:
        return web.json_response({"error": str(err)}, status=400)


@routes.post("/api/vpn/check")
async def vpn_check(_):
    return web.json_response(await tunnel.check())


@routes.delete("/api/vpn")
async def vpn_remove(request):
    if not is_ingress(request):
        return web.json_response({"error": "Nur in Home Assistant"}, status=403)
    return web.json_response(await tunnel.remove())


@routes.get("/api/youtube")
async def youtube_status(request):
    return web.json_response({**cookie_info(), "can_edit": is_ingress(request)})


@routes.post("/api/youtube")
async def youtube_upload(request):
    """Upload cookies.txt (Home Assistant only: it is a login)."""
    if not is_ingress(request):
        return web.json_response({"error": "Das YouTube-Konto lässt sich nur in Home Assistant verbinden"}, status=403)
    text = ""
    if request.content_type.startswith("multipart/"):
        async for part in await request.multipart():
            if part.name == "file":
                text = (await part.read(decode=False))[:2_000_000].decode("utf-8", "replace")
    else:
        text = (await request.text())[:2_000_000]
    rows = parse_cookies(text)
    if not rows:
        return web.json_response({"error": "Das ist keine cookies.txt-Datei von youtube.com (Netscape-Format)"}, status=400)
    if not any(r[5] in AUTH_COOKIES and r[0].endswith("youtube.com") for r in rows):
        return web.json_response({"error": "In der Datei fehlt die YouTube-Anmeldung – vor dem Export auf youtube.com einloggen"},
                                 status=400)
    # Keep only YouTube/Google cookies; nothing else from the browser is stored.
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOKIE_FILE.with_suffix(".tmp")
    tmp.write_text("# Netscape HTTP Cookie File\n" + "".join("\t".join(r) + "\n" for r in rows))
    os.chmod(tmp, 0o600)
    tmp.replace(COOKIE_FILE)
    ok, message = await asyncio.to_thread(check_youtube)
    youtube_state.update(checked=time.time(), ok=ok, message=message)
    log.info("YouTube-Konto verbunden (%d Cookies) – %s", len(rows), message)
    return web.json_response(cookie_info())


@routes.post("/api/youtube/check")
async def youtube_check(request):
    if not COOKIE_FILE.exists():
        return web.json_response({"error": "Kein YouTube-Konto verbunden"}, status=400)
    ok, message = await asyncio.to_thread(check_youtube)
    youtube_state.update(checked=time.time(), ok=ok, message=message)
    return web.json_response(cookie_info())


@routes.delete("/api/youtube")
async def youtube_remove(request):
    if not is_ingress(request):
        return web.json_response({"error": "Nur in Home Assistant"}, status=403)
    COOKIE_FILE.unlink(missing_ok=True)
    youtube_state.update(checked=0.0, ok=None, message="")
    log.info("YouTube-Konto getrennt")
    return web.json_response(cookie_info())


@routes.get("/api/library")
async def library(request):
    queue: VideoQueue = request.app["queue"]
    entries = await asyncio.to_thread(library_list, queue)
    try:
        usage = shutil.disk_usage(DOWNLOAD_DIR if DOWNLOAD_DIR.exists() else DOWNLOAD_DIR.parent)
        disk = {"total": usage.total, "free": usage.free, "used": usage.used}
    except OSError:
        disk = None
    return web.json_response({"entries": entries, "disk": disk, "directory": str(DOWNLOAD_DIR),
                              "library_size": sum(e["size"] for e in entries)})


@routes.get("/api/thumb/{token}")
async def thumb(request):
    path = decode(request.match_info["token"])
    target = await make_thumb(request.app["queue"], path, request.app["session"])
    if not target:
        raise web.HTTPNotFound()
    return web.FileResponse(target, headers={"Cache-Control": "max-age=86400"})


@routes.get("/files/{token}/{name}")
async def file(request):
    path = decode(request.match_info["token"])
    headers = {}
    if request.query.get("download"):
        headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + re.sub(r"[^\w.\-\[\] ]", "_", path.name).replace(" ", "%20")
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers["Content-Type"] = ctype
    return web.FileResponse(path, headers=headers)


@routes.post("/api/library/rename")
async def rename(request):
    queue: VideoQueue = request.app["queue"]
    data = await request.json()
    path = decode(str(data.get("id", "")))
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(data.get("name", ""))).strip(" .")
    if not name:
        raise web.HTTPBadRequest(text="Bitte einen Namen eingeben")
    target = path.with_name(name + path.suffix)
    if target.exists():
        raise web.HTTPConflict(text="Eine Datei mit diesem Namen gibt es schon")
    path.rename(target)
    old = str(path.relative_to(DOWNLOAD_DIR))
    new = str(target.relative_to(DOWNLOAD_DIR))
    meta = queue.library.pop(old, {})
    meta["title"] = name
    queue.library[new] = meta
    queue.save_library()
    old_thumb = THUMB_DIR / (hashlib.sha1(old.encode()).hexdigest() + ".jpg")
    if old_thumb.exists():
        old_thumb.rename(THUMB_DIR / (hashlib.sha1(new.encode()).hexdigest() + ".jpg"))
    return web.json_response({"id": encode(new)})


@routes.delete("/api/library/{token}")
async def delete_file(request):
    queue: VideoQueue = request.app["queue"]
    path = decode(request.match_info["token"])
    rel = str(path.relative_to(DOWNLOAD_DIR))
    path.unlink()
    queue.library.pop(rel, None)
    queue.save_library()
    (THUMB_DIR / (hashlib.sha1(rel.encode()).hexdigest() + ".jpg")).unlink(missing_ok=True)
    return web.Response(status=204)


async def on_startup(app):
    app["session"] = ClientSession(headers={"User-Agent": "Mozilla/5.0 (HomeAssistant Video-Downloader)"})
    app["worker"] = asyncio.create_task(app["queue"].worker())
    log.info("Video-Downloader: Ordner %s, Design %s/%s, yt-dlp %s", DOWNLOAD_DIR, DESIGN, THEME, yt_dlp.version.__version__)
    if tunnel.enabled:
        try:
            await tunnel.start()
        except vpn.VPNError as err:
            log.error("VPN-Datei ungültig: %s", err)
    for leftover in DATA_DIR.glob(".cookies-*.txt"):
        leftover.unlink(missing_ok=True)
    if COOKIE_FILE.exists():
        info = cookie_info()
        log.info("YouTube-Konto: %s", "verbunden" if info["connected"] else "Datei ohne Anmeldung – bitte neu hochladen")


async def on_cleanup(app):
    await tunnel.stop()
    app["worker"].cancel()
    if app["queue"].current:
        app["queue"].current["_cancel"] = True
    await app["session"].close()


async def serve(app):
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, None, PORT).start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await runner.cleanup()


def main():
    queue = VideoQueue()
    queue.load()
    app = web.Application()
    app["queue"] = queue
    Gate("Video-Downloader", os.environ.get("VIDEO_ACCESS_CODE") or OPTIONS.get("access_code"), THEME, "videos_zugang").setup(app)
    app.router.add_static("/static/", STATIC_DIR / "shared")
    app.add_routes(routes)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    asyncio.run(serve(app))


if __name__ == "__main__":
    main()
