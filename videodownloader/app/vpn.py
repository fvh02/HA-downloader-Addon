"""Proton VPN (free) for the downloads only: a WireGuard file from Proton is uploaded once, the add-on
runs wireproxy with it and yt-dlp sends everything through its SOCKS proxy.

Nothing else of Home Assistant goes through the VPN. While the VPN is switched on, downloads never
fall back to the home connection: if the tunnel is down they wait (kill switch).
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("vpn")

SOCKS = "127.0.0.1:1080"
PROXY = f"socks5h://{SOCKS}"        # socks5h: names are resolved through the tunnel too (no DNS leak)
BINARY = os.environ.get("VIDEO_WIREPROXY", "/usr/local/bin/wireproxy")
CHECK_URL = os.environ.get("VIDEO_VPN_CHECK_URL", "https://ipinfo.io/json")
INTERFACE_KEYS = {"privatekey", "address", "dns", "mtu"}
PEER_KEYS = {"publickey", "presharedkey", "endpoint", "allowedips", "persistentkeepalive"}
COUNTRIES = {"NL": "Niederlande", "CH": "Schweiz", "JP": "Japan", "US": "USA", "RO": "Rumänien", "PL": "Polen",
             "DE": "Deutschland", "NO": "Norwegen", "SG": "Singapur", "MX": "Mexiko", "CA": "Kanada", "FR": "Frankreich"}


class VPNError(Exception):
    pass


def parse(text: str) -> tuple[dict, dict, str]:
    """[Interface] and [Peer] of a WireGuard file (only the keys wireproxy needs) and the server name."""
    section, interface, peer, server = "", {}, {}, ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if line.startswith("#"):
            # Proton names the server in a comment, e.g. "# NL-FREE#57".
            name = line.lstrip("# ").strip()
            if section == "peer" and re.fullmatch(r"[A-Z]{2}[-A-Z0-9#]*", name):
                server = name
            continue
        if "=" not in line:
            continue
        key, value = (x.strip() for x in line.split("=", 1))
        if section == "interface" and key.lower() in INTERFACE_KEYS:
            interface[key] = value
        elif section == "peer" and key.lower() in PEER_KEYS:
            peer[key] = value
    names = {k.lower() for k in interface} | {k.lower() for k in peer}
    missing = [k for k in ("privatekey", "address", "publickey", "endpoint") if k not in names]
    if missing:
        raise VPNError("Das ist keine vollständige WireGuard-Datei (es fehlt: " + ", ".join(missing) + ")")
    for value in list(interface.values()) + list(peer.values()):
        if any(c in value for c in "\n\r[]") or "$" in value:
            raise VPNError("Ungültige Zeichen in der WireGuard-Datei")
    return interface, peer, server


def runtime_config(interface: dict, peer: dict) -> str:
    """wireproxy configuration: the tunnel plus a SOCKS proxy that only listens inside the add-on."""
    peer = {k: v for k, v in peer.items() if k.lower() != "persistentkeepalive"}
    lines = ["[Interface]"] + [f"{k} = {v}" for k, v in interface.items()]
    lines += ["", "[Peer]"] + [f"{k} = {v}" for k, v in peer.items()] + ["PersistentKeepalive = 25"]
    lines += ["", "[Socks5]", f"BindAddress = {SOCKS}", ""]
    return "\n".join(lines)


class VPN:
    def __init__(self, data_dir: Path):
        self.file = data_dir / "proton-wireguard.conf"
        self.runtime = data_dir / ".wireproxy.conf"
        self.process: asyncio.subprocess.Process | None = None
        self.supervisor: asyncio.Task | None = None
        self.state = {"ok": None, "ip": "", "country": "", "city": "", "checked": 0.0, "message": "", "since": 0.0}
        self.lock = asyncio.Lock()

    # -- state ---------------------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self.file.exists()

    def info(self) -> dict:
        server = ""
        if self.enabled:
            try:
                server = parse(self.file.read_text())[2]
            except (OSError, VPNError):
                pass
        country = self.state["country"]
        return {"enabled": self.enabled, "server": server, "running": bool(self.process and self.process.returncode is None),
                "ok": self.state["ok"], "ip": self.state["ip"], "country": COUNTRIES.get(country, country),
                "city": self.state["city"], "checked": self.state["checked"] or None, "message": self.state["message"]}

    def ydl_options(self) -> dict:
        """Proxy for yt-dlp while the VPN is switched on (also when it is down: then nothing goes out)."""
        return {"proxy": PROXY} if self.enabled else {}

    # -- process -------------------------------------------------------------------------------
    async def start(self) -> None:
        await self.stop()
        if not self.enabled:
            return
        interface, peer, server = parse(self.file.read_text())
        self.runtime.write_text(runtime_config(interface, peer))
        os.chmod(self.runtime, 0o600)
        self.state.update(ok=None, ip="", country="", city="", message="Verbinde …", since=time.time())
        self.supervisor = asyncio.create_task(self._supervise())
        log.info("VPN: Proton %s wird verbunden", server or peer.get("Endpoint", ""))

    async def _supervise(self) -> None:
        """Keeps wireproxy running; restarts it if it stops."""
        while self.enabled:
            try:
                self.process = await asyncio.create_subprocess_exec(
                    BINARY, "-c", str(self.runtime), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            except OSError as err:
                self.state.update(ok=False, message=f"VPN-Programm fehlt: {err}")
                log.error("wireproxy nicht startbar: %s", err)
                return
            await asyncio.sleep(2)
            asyncio.create_task(self.check())
            _, err = await self.process.communicate()
            if not self.enabled:
                return
            text = (err or b"").decode(errors="replace").strip().splitlines()
            self.state.update(ok=False, message="VPN-Verbindung abgebrochen – neuer Versuch …")
            log.warning("wireproxy beendet (%s) – Neustart in 10 s", text[-1] if text else self.process.returncode)
            await asyncio.sleep(10)

    async def stop(self) -> None:
        if self.supervisor:
            self.supervisor.cancel()
            self.supervisor = None
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
        self.process = None
        self.runtime.unlink(missing_ok=True)

    # -- health ---------------------------------------------------------------------------------
    def _fetch_ip(self) -> dict:
        import yt_dlp  # its networking speaks SOCKS, so no extra library is needed
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "proxy": PROXY, "socket_timeout": 15}) as ydl:
            with ydl.urlopen(CHECK_URL) as resp:
                return json.loads(resp.read())

    async def check(self) -> dict:
        """Asks an IP service through the tunnel: works → the VPN is up, and shows where we appear to be."""
        if not self.enabled:
            return self.info()
        async with self.lock:
            try:
                data = await asyncio.to_thread(self._fetch_ip)
                self.state.update(ok=True, ip=str(data.get("ip") or ""), country=str(data.get("country") or ""),
                                  city=str(data.get("city") or ""), message="")
            except Exception as err:  # noqa: BLE001
                self.state.update(ok=False, message="Keine Verbindung über das VPN – Downloads warten")
                log.info("VPN-Prüfung fehlgeschlagen: %s", str(err)[:200])
            self.state["checked"] = time.time()
        return self.info()

    async def wait_ready(self, timeout: float = 0) -> bool:
        """True when downloads may start: VPN off, or VPN up (checked within the last minute)."""
        if not self.enabled:
            return True
        deadline = time.time() + timeout
        while True:
            if self.state["ok"] and time.time() - self.state["checked"] < 60:
                return True
            await self.check()
            if self.state["ok"]:
                return True
            if time.time() >= deadline:
                return False
            await asyncio.sleep(10)

    # -- file ----------------------------------------------------------------------------------
    async def install(self, text: str) -> dict:
        interface, peer, _ = parse(text)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        # Only what is needed is kept; comments and other settings are dropped.
        tmp.write_text("[Interface]\n" + "".join(f"{k} = {v}\n" for k, v in interface.items())
                       + "\n[Peer]\n# " + (parse(text)[2] or "Proton") + "\n" + "".join(f"{k} = {v}\n" for k, v in peer.items()))
        os.chmod(tmp, 0o600)
        tmp.replace(self.file)
        await self.start()
        return await self.check() if await self._wait_running() else self.info()

    async def _wait_running(self) -> bool:
        for _ in range(20):
            if self.process and self.process.returncode is None:
                await asyncio.sleep(1.5)
                return True
            await asyncio.sleep(0.25)
        return False

    async def remove(self) -> dict:
        self.file.unlink(missing_ok=True)
        await self.stop()
        self.state.update(ok=None, ip="", country="", city="", message="", checked=0.0)
        log.info("VPN ausgeschaltet – Downloads laufen wieder direkt")
        return self.info()
