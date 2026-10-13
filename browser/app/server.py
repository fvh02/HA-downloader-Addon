"""Web side of the Browser add-on: serves the noVNC web client and bridges its WebSocket to the
virtual screen (VNC on localhost:5900).

Only Home Assistant's Ingress is let in – the browser holds your logins, so it must never be
reachable from the home network or the internet directly.
"""

import asyncio
import logging
import os
from pathlib import Path

from aiohttp import WSMsgType, web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("browser")

PORT = int(os.environ.get("BROWSER_PORT", "8096"))
VNC = (os.environ.get("BROWSER_VNC_HOST", "127.0.0.1"), int(os.environ.get("BROWSER_VNC_PORT", "5900")))
NOVNC = Path(os.environ.get("BROWSER_NOVNC", "/usr/share/novnc"))
INGRESS_IPS = set(os.environ.get("BROWSER_INGRESS_IPS", "172.30.32.2").split(","))
STATIC = Path(__file__).parent / "static"


@web.middleware
async def only_home_assistant(request: web.Request, handler):
    if request.remote not in INGRESS_IPS or "X-Ingress-Path" not in request.headers:
        log.warning("Abgewiesen: %s %s (nur über Home Assistant)", request.remote, request.path)
        return web.Response(status=403, text="Der Browser ist nur über Home Assistant erreichbar.")
    response = await handler(request)
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


async def index(_: web.Request) -> web.Response:
    return web.FileResponse(STATIC / "index.html")


async def novnc(request: web.Request) -> web.StreamResponse:
    rel = request.match_info["path"] or "vnc.html"
    path = (NOVNC / rel).resolve()
    if not str(path).startswith(str(NOVNC.resolve())) or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def bridge(request: web.Request) -> web.WebSocketResponse:
    """noVNC speaks VNC inside a WebSocket; pass the bytes on to the VNC server and back."""
    ws = web.WebSocketResponse(protocols=("binary",), max_msg_size=16 * 1024 * 1024, heartbeat=30)
    await ws.prepare(request)
    try:
        reader, writer = await asyncio.open_connection(*VNC)
    except OSError as err:
        log.warning("Bildschirm nicht erreichbar: %s", err)
        await ws.close(code=1011, message=b"Bildschirm startet noch")
        return ws

    async def to_browser():
        while data := await reader.read(65536):
            await ws.send_bytes(data)
        await ws.close()

    pump = asyncio.create_task(to_browser())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                writer.write(msg.data)
                await writer.drain()
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        pump.cancel()
        writer.close()
    return ws


async def status(_: web.Request) -> web.Response:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(*VNC), 2)
        writer.close()
        return web.json_response({"screen": True})
    except (OSError, asyncio.TimeoutError):
        return web.json_response({"screen": False})


def main() -> None:
    app = web.Application(middlewares=[only_home_assistant])
    app.add_routes([web.get("/", index), web.get("/websockify", bridge), web.get("/api/status", status),
                    web.get("/novnc/{path:.*}", novnc)])
    log.info("Browser-Oberfläche auf Port %s", PORT)
    web.run_app(app, port=PORT, print=None, access_log=None)


if __name__ == "__main__":
    main()
