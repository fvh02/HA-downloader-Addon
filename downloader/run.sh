#!/usr/bin/with-contenv bashio
bashio::log.info "Starte Downloader ..."
exec python3 /app/server.py
