FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive LANG=de_DE.UTF-8 LC_ALL=C.UTF-8 PYTHONUNBUFFERED=1

# Virtual screen (TigerVNC), small window manager, noVNC web client, fonts incl. emoji
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl jq procps tigervnc-standalone-server openbox novnc python3 python3-aiohttp \
        fonts-noto-core fonts-noto-color-emoji fonts-liberation fonts-dejavu-core xdg-utils dbus-x11 \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome (stable) from Google
RUN curl -fsSL -o /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -rf /tmp/chrome.deb /var/lib/apt/lists/* \
    && google-chrome --version

RUN useradd --create-home --uid 1000 --shell /bin/bash browser

COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh
CMD [ "/run.sh" ]
