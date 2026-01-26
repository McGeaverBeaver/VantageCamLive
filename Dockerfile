# Global build arguments (must be before any FROM)
ARG MTX_VERSION=v1.6.0

# MediaMTX builder stage
FROM bluenviron/mediamtx:${MTX_VERSION} AS mediamtx

# Main application stage
FROM alpine:3.19

ARG INCLUDE_INTEL=true
ARG ARCH=amd64
ARG VERSION=2.8.2

# Image metadata
LABEL maintainer="McGeaverBeaver"
LABEL version="${VERSION}"
LABEL description="Automated 24/7 Live Stream Broadcaster with Weather, Smart Alerts & Self-Healing"
LABEL org.opencontainers.image.source="https://github.com/McGeaverBeaver/VantageCamLive"

# 1. Install base dependencies (including shadow/su-exec for PUID/PGID support)
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
    tzdata \
    shadow \
    su-exec

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

# 4. Install MediaMTX from builder stage
COPY --from=mediamtx /mediamtx /usr/local/bin/mediamtx

# 5. Setup Entrypoint and Scripts
COPY start.sh /start.sh
COPY weather.py /weather.py
COPY audio_api.py /audio_api.py
COPY watchdog.py /watchdog.py
RUN sed -i 's/\r$//' /start.sh /weather.py /audio_api.py /watchdog.py \
    && chmod +x /start.sh /watchdog.py

# 6. Create config directory and health check script
RUN mkdir -p /config /health

# 7. Create health check script that monitors FFmpeg output
COPY --chmod=755 <<'EOF' /health/check.sh
#!/bin/bash
# VantageCam Health Check - Monitors actual stream health, not just process existence
PROGRESS_FILE="/config/ffmpeg_progress.txt"
MAX_AGE=60  # Consider stale if progress file older than 60 seconds
PID_FILE="/config/youtube_restreamer.pid"

# Level 1: Check if Audio API is responding (basic container health)
if ! curl -sf http://localhost:9998/health > /dev/null 2>&1; then
    echo "FAIL: Audio API not responding"
    exit 1
fi

# Level 2: Check if FFmpeg process exists
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$PID" ] && ! kill -0 "$PID" 2>/dev/null; then
        # PID file exists but process is dead - unhealthy
        echo "FAIL: FFmpeg process (PID $PID) not running"
        exit 1
    fi
fi

# Level 3: Check FFmpeg progress file freshness (if streaming to YouTube)
if [ -f "$PROGRESS_FILE" ]; then
    FILE_AGE=$(($(date +%s) - $(stat -c %Y "$PROGRESS_FILE" 2>/dev/null || echo 0)))
    
    if [ "$FILE_AGE" -gt "$MAX_AGE" ]; then
        echo "FAIL: FFmpeg progress stale (${FILE_AGE}s old)"
        exit 1
    fi
    
    # Level 4: Check if frames are advancing
    FRAME=$(grep "^frame=" "$PROGRESS_FILE" 2>/dev/null | tail -1 | cut -d= -f2)
    LAST_FRAME_FILE="/tmp/health_last_frame"
    
    if [ -n "$FRAME" ] && [ -f "$LAST_FRAME_FILE" ]; then
        LAST_FRAME=$(cat "$LAST_FRAME_FILE" 2>/dev/null)
        if [ "$FRAME" = "$LAST_FRAME" ] && [ "$FILE_AGE" -gt 15 ]; then
            echo "FAIL: FFmpeg stalled at frame $FRAME for ${FILE_AGE}s"
            exit 1
        fi
    fi
    
    # Save current frame for next check
    [ -n "$FRAME" ] && echo "$FRAME" > "$LAST_FRAME_FILE"
fi

echo "OK"
exit 0
EOF

# 8. Expose ports
EXPOSE 8554 9998

# 9. Health check - monitors actual stream health
# - interval: Check every 45 seconds
# - timeout: Allow 15 seconds for check to complete
# - start-period: Give 90 seconds for initial startup
# - retries: 3 failures before marking unhealthy
HEALTHCHECK --interval=45s --timeout=15s --start-period=90s --retries=3 \
    CMD /health/check.sh

# 10. Entrypoint
ENTRYPOINT ["/bin/bash", "-c", "export TZ=${WEATHER_TIMEZONE:-America/Toronto} && exec /start.sh"]