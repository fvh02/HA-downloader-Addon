"""Downloader add-on: hosts a small web UI and downloads queued files one after another."""

import asyncio
import json
import logging
import os
import re
import signal
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from aiohttp import ClientSession, ClientTimeout, web

from access import Gate

OPTIONS_FILE = Path("/data/options.json")
STATE_FILE = Path(os.environ.get("DOWNLOADER_STATE", "/data/queue.json"))
STATIC_DIR = Path(__file__).parent / "static"
PORT = int(os.environ.get("DOWNLOADER_PORT", "8099"))  # Ingress; other add-ons reach it on the internal network
# Gateway setups from before 1.3.0 still call the old port; answer there too (not mapped to the host).
LEGACY_PORT = int(os.environ.get("DOWNLOADER_LEGACY_PORT", "8100"))
CHUNK_SIZE = 256 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("downloader")


def load_options() -> dict:
    try:
        return json.loads(OPTIONS_FILE.read_text())
    except (OSError, ValueError):
        return {}


OPTIONS = load_options()
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOADER_DIR") or OPTIONS.get("download_dir") or "/media/downloads")
PAGES = {"modern": "modern.html", "terminal": "terminal.html"}
DESIGN = os.environ.get("DOWNLOADER_DESIGN") or OPTIONS.get("design") or "modern"
THEME = os.environ.get("DOWNLOADER_THEME") or OPTIONS.get("theme") or "dark"
if DESIGN not in PAGES:
    DESIGN = "modern"
if THEME not in ("dark", "light"):
    THEME = "dark"

# Optional iMessage notifications through the Inkbox API.
INKBOX_URL = os.environ.get("DOWNLOADER_INKBOX_URL", "https://inkbox.ai/api/v1/imessage/messages")
INKBOX_API_KEY = (os.environ.get("DOWNLOADER_INKBOX_API_KEY") or OPTIONS.get("inkbox_api_key") or "").strip()
IMESSAGE_TO = os.environ.get("DOWNLOADER_IMESSAGE_TO") or OPTIONS.get("imessage_to") or ""


def format_size(size: int | None) -> str:
    if size is None:
        return "unbekannte Größe"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            break
        value /= 1024
    text = f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
    return text.replace(".", ",")


def status_summary(items: list[dict]) -> str:
    """Short German status text, e.g. for a chat reply."""
    active = next((i for i in items if i["status"] == "downloading"), None)
    queued = [i for i in items if i["status"] == "queued"]
    done = [i for i in items if i["status"] == "done"]
    failed = [i for i in items if i["status"] == "error"]
    lines = []
    if active:
        progress = format_size(active["downloaded"])
        if active["size"]:
            percent = int(active["downloaded"] * 100 / active["size"])
            progress = f"{percent} % von {format_size(active['size'])}"
        speed = f", {format_size(active['speed'])}/s" if active["speed"] else ""
        lines.append(f"⬇️ {active['name']}: {progress}{speed}")
    if queued:
        names = ", ".join(i["name"] for i in queued[:5]) + (" …" if len(queued) > 5 else "")
        lines.append(f"⏳ {len(queued)} in der Warteschlange: {names}")
    if done:
        lines.append(f"✅ {len(done)} fertig")
    if failed:
        lines.append(f"❌ {len(failed)} fehlgeschlagen: " + ", ".join(i["name"] for i in failed[:5]))
    return "\n".join(lines) or "Keine Downloads in der Warteliste."


def sanitize_filename(name: str) -> str:
    name = unquote(name).replace("\\", "/").split("/")[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(" .")
    return name[:200] or "download"


def name_from_url(url: str) -> str:
    return sanitize_filename(urlparse(url).path.rstrip("/").split("/")[-1] or urlparse(url).netloc)


def name_from_headers(headers) -> str | None:
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", disposition, re.I)
    if match:
        return sanitize_filename(match.group(1).strip().strip('"'))
    match = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition, re.I)
    if match:
        return sanitize_filename(match.group(1).strip())
    return None


def unique_path(directory: Path, name: str) -> Path:
    target = directory / name
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists() or target.with_name(target.name + ".part").exists():
        target = directory / f"{stem} ({counter}){suffix}"
        counter += 1
    return target


class DownloadQueue:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.wakeup = asyncio.Event()
        self.current_id: str | None = None
        self.current_task: asyncio.Task | None = None
        self.session: ClientSession | None = None

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        try:
            self.items = json.loads(STATE_FILE.read_text())
        except (OSError, ValueError):
            self.items = []
        for item in self.items:
            # A download interrupted by a restart starts over.
            if item["status"] == "downloading":
                item.update(status="queued", downloaded=0, speed=0)

    def save(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items))
            tmp.replace(STATE_FILE)
        except OSError as err:
            log.warning("Konnte Warteliste nicht speichern: %s", err)

    # -- queue operations --------------------------------------------------
    def get(self, item_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    def add(self, url: str) -> dict:
        item = {
            "id": uuid.uuid4().hex,
            "url": url,
            "name": name_from_url(url),
            "size": None,
            "downloaded": 0,
            "speed": 0,
            "status": "queued",
            "error": None,
            "added": time.time(),
        }
        self.items.append(item)
        self.save()
        asyncio.create_task(self.probe(item))
        self.wakeup.set()
        return item

    def remove(self, item_id: str) -> bool:
        item = self.get(item_id)
        if not item:
            return False
        if item_id == self.current_id and self.current_task:
            self.current_task.cancel()
        self.items.remove(item)
        self.save()
        return True

    def clear_finished(self) -> None:
        self.items = [i for i in self.items if i["status"] not in ("done", "error")]
        self.save()

    # -- networking --------------------------------------------------------
    async def probe(self, item: dict) -> None:
        """Fetch file name and size without downloading the file."""
        try:
            async with self.session.head(item["url"], allow_redirects=True) as resp:
                if resp.status >= 400 or resp.content_length is None:
                    raise ValueError("HEAD unbrauchbar")
                headers, length = resp.headers, resp.content_length
        except Exception:  # noqa: BLE001 - fall back to a GET that only reads headers
            try:
                async with self.session.get(item["url"], allow_redirects=True) as resp:
                    if resp.status >= 400:
                        return
                    headers, length = resp.headers, resp.content_length
            except Exception:  # noqa: BLE001
                return
        if item["status"] != "queued":
            return
        name = name_from_headers(headers)
        if name:
            item["name"] = name
        if length:
            item["size"] = length
        self.save()

    async def download(self, item: dict) -> None:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        part = None
        try:
            async with self.session.get(item["url"], allow_redirects=True) as resp:
                resp.raise_for_status()
                name = name_from_headers(resp.headers) or item["name"]
                target = unique_path(DOWNLOAD_DIR, name)
                part = target.with_name(target.name + ".part")
                item.update(name=target.name, size=resp.content_length or item["size"])
                last_time, last_bytes = time.monotonic(), 0
                with part.open("wb") as fh:
                    async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                        await asyncio.to_thread(fh.write, chunk)
                        item["downloaded"] += len(chunk)
                        now = time.monotonic()
                        if now - last_time >= 1:
                            item["speed"] = int((item["downloaded"] - last_bytes) / (now - last_time))
                            last_time, last_bytes = now, item["downloaded"]
            part.replace(target)
            item.update(status="done", speed=0, size=item["size"] or item["downloaded"])
            log.info("Fertig: %s", target)
            self.notify(f"✅ Download fertig: {item['name']} ({format_size(item['size'])})")
        except asyncio.CancelledError:
            if part:
                part.unlink(missing_ok=True)
            log.info("Abgebrochen: %s", item["name"])
            raise
        except Exception as err:  # noqa: BLE001
            if part:
                part.unlink(missing_ok=True)
            item.update(status="error", error=str(err) or err.__class__.__name__, speed=0)
            log.warning("Fehler bei %s: %s", item["url"], err)
            self.notify(f"❌ Download fehlgeschlagen: {item['name']}\n{item['error']}")

    def notify(self, text: str) -> None:
        if INKBOX_API_KEY and IMESSAGE_TO:
            asyncio.create_task(self.send_imessage(text))

    async def send_imessage(self, text: str) -> None:
        try:
            async with self.session.post(
                INKBOX_URL,
                json={"to": IMESSAGE_TO, "text": text},
                headers={"X-API-Key": INKBOX_API_KEY},
                timeout=ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    log.warning("iMessage-Benachrichtigung fehlgeschlagen (%s): %s", resp.status, await resp.text())
        except Exception as err:  # noqa: BLE001
            log.warning("iMessage-Benachrichtigung fehlgeschlagen: %s", err)

    async def worker(self) -> None:
        while True:
            item = next((i for i in self.items if i["status"] == "queued"), None)
            if not item:
                self.wakeup.clear()
                await self.wakeup.wait()
                continue
            item.update(status="downloading", downloaded=0, speed=0, error=None)
            self.save()
            self.current_id = item["id"]
            self.current_task = asyncio.create_task(self.download(item))
            try:
                await self.current_task
            except asyncio.CancelledError:
                if not self.current_task.cancelled():
                    raise  # the worker itself is shutting down
            finally:
                self.current_id = self.current_task = None
                self.save()


# -- HTTP API --------------------------------------------------------------
routes = web.RouteTableDef()


def public(item: dict) -> dict:
    return {k: item[k] for k in ("id", "url", "name", "size", "downloaded", "speed", "status", "error")}


@routes.get("/")
async def index(_: web.Request) -> web.Response:
    html = (STATIC_DIR / PAGES[DESIGN]).read_text(encoding="utf-8")
    html = html.replace("<html ", f'<html data-theme="{THEME}" ', 1)
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"})


@routes.get("/api/items")
async def list_items(request: web.Request) -> web.Response:
    queue: DownloadQueue = request.app["queue"]
    return web.json_response({"items": [public(i) for i in queue.items], "directory": str(DOWNLOAD_DIR)})


@routes.get("/api/status")
async def status(request: web.Request) -> web.Response:
    items = request.app["queue"].items
    count = lambda status: sum(1 for i in items if i["status"] == status)  # noqa: E731
    active = next((i for i in items if i["status"] == "downloading"), None)
    return web.json_response({
        "summary": status_summary(items),
        "active": public(active) if active else None,
        "queued": count("queued"),
        "done": count("done"),
        "failed": count("error"),
        "items": [public(i) for i in items],
    })


@routes.post("/api/items")
async def add_items(request: web.Request) -> web.Response:
    queue: DownloadQueue = request.app["queue"]
    try:
        data = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="Ungültige Anfrage")
    urls = [u for u in re.split(r"\s+", str(data.get("url", ""))) if u]
    if not urls:
        raise web.HTTPBadRequest(text="Bitte einen Link eingeben")
    invalid = [u for u in urls if urlparse(u).scheme not in ("http", "https") or not urlparse(u).netloc]
    if invalid:
        raise web.HTTPBadRequest(text=f"Ungültiger Link: {invalid[0]}")
    added = [public(queue.add(u)) for u in urls]
    return web.json_response({"items": added}, status=201)


@routes.delete("/api/items/{item_id}")
async def delete_item(request: web.Request) -> web.Response:
    queue: DownloadQueue = request.app["queue"]
    if not queue.remove(request.match_info["item_id"]):
        raise web.HTTPNotFound()
    return web.Response(status=204)


@routes.post("/api/clear")
async def clear(request: web.Request) -> web.Response:
    request.app["queue"].clear_finished()
    return web.Response(status=204)


async def on_startup(app: web.Application) -> None:
    queue: DownloadQueue = app["queue"]
    queue.session = ClientSession(
        timeout=ClientTimeout(total=None, sock_connect=30, sock_read=120),
        headers={"User-Agent": "Mozilla/5.0 (HomeAssistant Downloader Add-on)"},
    )
    app["worker"] = asyncio.create_task(queue.worker())
    log.info("Downloads werden gespeichert in %s (Design: %s, %s)", DOWNLOAD_DIR, DESIGN, THEME)
    if INKBOX_API_KEY and IMESSAGE_TO:
        log.info("iMessage-Benachrichtigungen an %s aktiv", IMESSAGE_TO)


async def on_cleanup(app: web.Application) -> None:
    app["worker"].cancel()
    queue: DownloadQueue = app["queue"]
    if queue.current_task:
        queue.current_task.cancel()
    await queue.session.close()


def main() -> None:
    queue = DownloadQueue()
    queue.load()
    app = web.Application()
    app["queue"] = queue
    Gate("Downloader", os.environ.get("DOWNLOADER_ACCESS_CODE") or OPTIONS.get("access_code"), THEME, "downloader_zugang").setup(app)
    app.add_routes(routes)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    asyncio.run(serve(app))


async def serve(app: web.Application) -> None:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    # host=None listens on IPv4 and IPv6; the internal network may resolve add-on names to either.
    for port in (PORT, LEGACY_PORT):
        await web.TCPSite(runner, None, port).start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    main()
