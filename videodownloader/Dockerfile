ARG BUILD_FROM=python:3.12-slim-bookworm

# wireproxy (https://github.com/pufferffish/wireproxy): WireGuard in user space with a SOCKS proxy,
# so the downloads can go through Proton VPN without extra privileges for the add-on.
FROM golang:1.26-bookworm AS wireproxy
ARG WIREPROXY_VERSION=v1.1.3
RUN git clone --depth 1 --branch "${WIREPROXY_VERSION}" https://github.com/pufferffish/wireproxy /src \
    && cd /src && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /wireproxy ./cmd/wireproxy

FROM ${BUILD_FROM}
ARG TARGETARCH
COPY --from=wireproxy /wireproxy /usr/local/bin/wireproxy

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg unzip \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp needs a JavaScript runtime for YouTube; Deno is the one it looks for first.
RUN case "${TARGETARCH}" in \
        amd64) arch=x86_64 ;; \
        arm64) arch=aarch64 ;; \
        *) echo "Nicht unterstützte Architektur: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/denoland/deno/releases/latest/download/deno-${arch}-unknown-linux-gnu.zip" -o /tmp/deno.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && rm /tmp/deno.zip \
    && deno --version

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Headless Chromium for the video search on pages yt-dlp does not know (only the small headless shell).
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN playwright install --with-deps --only-shell chromium && rm -rf /var/lib/apt/lists/*

COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
