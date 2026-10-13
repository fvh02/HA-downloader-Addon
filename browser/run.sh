#!/usr/bin/env bash
# Browser add-on: a virtual screen (Xvnc) with Google Chrome, shown in Home Assistant through noVNC.
set -euo pipefail

DATA="${BROWSER_DATA:-/data}"
OPTIONS="$DATA/options.json"
opt() { jq -r --arg k "$1" --arg d "$2" '.[$k] // $d' "$OPTIONS" 2>/dev/null || echo "$2"; }

START_URL="$(opt start_url https://www.google.de)"
RESOLUTION="$(opt resolution 1280x800)"
DOWNLOADS="$(opt download_dir /media/downloads/browser)"
PROFILE="$DATA/chrome"
export DISPLAY=:1

mkdir -p "$PROFILE/Default" "$DOWNLOADS"
chown -R browser:browser "$PROFILE" "$DOWNLOADS" 2>/dev/null || true

# Downloads go straight to the download folder, without asking every time.
python3 - "$PROFILE/Default/Preferences" "$DOWNLOADS" <<'PY'
import json, sys
path, folder = sys.argv[1], sys.argv[2]
try:
    prefs = json.load(open(path))
except (OSError, ValueError):
    prefs = {}
prefs.setdefault("download", {}).update(default_directory=folder, prompt_for_download=False, directory_upgrade=True)
prefs.setdefault("savefile", {})["default_directory"] = folder
prefs.setdefault("browser", {})["check_default_browser"] = False
prefs.setdefault("intl", {})["accept_languages"] = "de-DE,de,en-US,en"
# A crash or a stopped add-on must not show "Chrome was not shut down correctly".
prefs.setdefault("profile", {})["exit_type"] = "Normal"
prefs["profile"]["exited_cleanly"] = True
json.dump(prefs, open(path, "w"))
PY
chown browser:browser "$PROFILE/Default/Preferences" 2>/dev/null || true
rm -f "$PROFILE"/Singleton*          # stale lock from the last container

echo "[browser] Starte Bildschirm ($RESOLUTION) ..."
# VNC only on localhost and without password: it is reachable only through the add-on's web server,
# which only lets Home Assistant (Ingress) in.
runuser -u browser -- Xvnc :1 -geometry "$RESOLUTION" -depth 24 -SecurityTypes None -localhost \
  -rfbport 5900 -AlwaysShared -AcceptSetDesktopSize -desktop "Browser" >/tmp/xvnc.log 2>&1 &
for _ in $(seq 1 50); do [ -e /tmp/.X11-unix/X1 ] && break; sleep 0.1; done
runuser -u browser -- openbox >/tmp/openbox.log 2>&1 &

# Chrome is started again whenever it is closed (or crashes). Its own sandbox is used when the
# container allows it; otherwise it falls back to --no-sandbox (the add-on container still isolates it).
(
  sandbox=""
  quick=0
  while true; do
    started=$(date +%s)
    runuser -u browser -- env HOME=/home/browser google-chrome \
      --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check --disable-dev-shm-usage \
      --password-store=basic --start-maximized --lang=de --disable-features=Translate \
      $sandbox "$START_URL" >/tmp/chrome.log 2>&1 || true
    if [ $(( $(date +%s) - started )) -lt 8 ]; then
      quick=$((quick + 1))
      if [ -z "$sandbox" ] && grep -qiE "sandbox|namespace" /tmp/chrome.log; then
        echo "[browser] Chrome-Sandbox im Container nicht verfügbar – starte mit --no-sandbox"
        sandbox="--no-sandbox --test-type"
        quick=0
      elif [ "$quick" -ge 5 ]; then
        echo "[browser] Chrome startet nicht:"; tail -n 5 /tmp/chrome.log; sleep 30; quick=0
      fi
    else
      quick=0
      echo "[browser] Chrome wurde geschlossen – öffne neu"
    fi
    rm -f "$PROFILE"/Singleton*
    sleep 1
  done
) &

echo "[browser] Bereit – Seitenleiste → Browser"
cd /app
exec python3 server.py
