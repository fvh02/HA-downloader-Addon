#!/usr/bin/env bash
# YouTube changes often; a current yt-dlp is the best protection against broken downloads.
update="$(python3 -c 'import json; print(json.load(open("/data/options.json")).get("update_ytdlp", True))' 2>/dev/null || echo True)"
if [ "$update" != "False" ]; then
  echo "[video] Aktualisiere yt-dlp ..."
  pip install --no-cache-dir --quiet --upgrade "yt-dlp[default]" \
    || echo "[video] Update nicht möglich, nutze die vorhandene Version"
fi
cd /app
exec python3 server.py
