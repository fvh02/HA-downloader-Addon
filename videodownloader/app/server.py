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

from access import Gate

OPTIONS_FILE = Path("/data/options.json")
DATA_DIR = Path(os.environ.get("VIDEO_DATA", "/data"))
STATE_FILE = DATA_DIR / "queue.json"
LIBRARY_FILE = DATA_DIR / "library.json"
THUMB_DIR = DATA_DIR / "thumbs"
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
        def extract():
            opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist", "noplaylist": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.sanitize_info(ydl.extract_info(item["url"], download=False))

        try:
            info = await asyncio.to_thread(extract)
        except Exception as err:  # noqa: BLE001
            if item in self.items:
                item.update(status="error", error=clean_error(err))
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
            "windowsfilenames": True, "overwrites": False, "continuedl": True,
        }
        if quality == "audio":
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
        else:
            opts["merge_output_format"] = "mp4"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(item["url"], download=True)
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


async def make_thumb(queue: VideoQueue, path: Path, session: ClientSession) -> Path | None:
    rel = str(path.relative_to(DOWNLOAD_DIR))
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    target = THUMB_DIR / (hashlib.sha1(rel.encode()).hexdigest() + ".jpg")
    if target.exists():
        return target
    meta = queue.library.get(rel) or {}
    if meta.get("thumbnail"):
        try:
            async with session.get(meta["thumbnail"], timeout=ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    raw = target.with_suffix(".src")
                    raw.write_bytes(await resp.read())
                    # normalise (webp etc.) to a small jpeg
                    await asyncio.to_thread(subprocess.run, ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-vf", "scale=480:-2", str(target)], timeout=30)
                    raw.unlink(missing_ok=True)
                    if target.exists():
                        return target
        except Exception:  # noqa: BLE001
            pass
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
    return {k: v for k, v in item.items() if not k.startswith("_")}


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


async def on_cleanup(app):
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
