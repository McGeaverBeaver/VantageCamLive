FROM alpine:3.19

# 1. Install dependencies
ENV LIBVA_DRIVER_NAME=iHD
RUN apk add --no-cache ffmpeg bash wget curl procps coreutils \
    intel-media-driver libva-utils \
    python3 py3-pip \
    freetype ttf-dejavu tzdata

# 2. Install Python libraries
# Added 'env_canada', 'geopy', 'aiohttp' for the Alerts
RUN pip3 install --break-system-packages requests Pillow env_canada geopy aiohttp

# 3. Install MediaMTX
ARG ARCH=amd64
ARG VERSION=v1.6.0
RUN wget -O mediamtx.tar.gz https://github.com/bluenviron/mediamtx/releases/download/${VERSION}/mediamtx_${VERSION}_linux_${ARCH}.tar.gz \
    && tar -xzf mediamtx.tar.gz -C /usr/local/bin/ \
    && rm mediamtx.tar.gz

# 4. Setup Entrypoint and Scripts
COPY start.sh /start.sh
COPY weather.py /weather.py
COPY audio_api.py /audio_api.py

RUN sed -i 's/\r$//' /start.sh /weather.py /audio_api.py \
    && chmod +x /start.sh

# 5. Expose ports
EXPOSE 8554 9998

# 6. Entrypoint
ENTRYPOINT ["/bin/bash", "-c", "export TZ=${WEATHER_TIMEZONE:-America/Toronto} && exec /start.sh"]