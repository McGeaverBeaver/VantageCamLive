FROM alpine:3.19

# Build argument for hardware acceleration support
ARG INCLUDE_INTEL=true

# 1. Install base dependencies
RUN apk add --no-cache \
    ffmpeg \
    bash \
    wget \
    curl \
    procps \
    coreutils \
    python3 \
    py3-pip \
    freetype \
    ttf-dejavu \
    tzdata

# 2. Conditionally install Intel/VAAPI drivers
# Only installed if INCLUDE_INTEL=true (default)
RUN if [ "$INCLUDE_INTEL" = "true" ]; then \
        apk add --no-cache intel-media-driver libva-utils && \
        echo "Intel VAAPI drivers installed"; \
    else \
        echo "Skipping Intel drivers (software-only build)"; \
    fi

# Set VAAPI driver (only effective if Intel drivers are installed)
ENV LIBVA_DRIVER_NAME=iHD

# 3. Install Python libraries
RUN pip3 install --break-system-packages --no-cache-dir \
    requests \
    Pillow \
    env_canada \
    geopy \
    aiohttp

# 4. Install MediaMTX
ARG ARCH=amd64
ARG MTX_VERSION=v1.6.0
RUN wget -q -O mediamtx.tar.gz \
    https://github.com/bluenviron/mediamtx/releases/download/${MTX_VERSION}/mediamtx_${MTX_VERSION}_linux_${ARCH}.tar.gz \
    && tar -xzf mediamtx.tar.gz -C /usr/local/bin/ \
    && rm mediamtx.tar.gz

# 5. Setup Entrypoint and Scripts
COPY start.sh /start.sh
COPY weather.py /weather.py
COPY audio_api.py /audio_api.py

RUN sed -i 's/\r$//' /start.sh /weather.py /audio_api.py \
    && chmod +x /start.sh

# 6. Create config directory
RUN mkdir -p /config

# 7. Expose ports
EXPOSE 8554 9998

# 8. Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:9998/health 2>/dev/null || exit 1

# 9. Entrypoint
ENTRYPOINT ["/bin/bash", "-c", "export TZ=${WEATHER_TIMEZONE:-America/Toronto} && exec /start.sh"]
