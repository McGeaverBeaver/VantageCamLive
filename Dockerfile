FROM alpine:3.19

# 1. Install dependencies, including Python for the weather generator
ENV LIBVA_DRIVER_NAME=iHD
RUN apk add --no-cache ffmpeg bash wget curl procps coreutils \
    intel-media-driver libva-utils \
    python3 py3-pip \
    freetype ttf-dejavu tzdata

# Install Python libraries for image generation (Pillow) and API requests
# --break-system-packages is safe here as this is a container
RUN pip3 install --break-system-packages requests Pillow

# 2. Install MediaMTX
ARG ARCH=amd64
ARG VERSION=v1.6.0
RUN wget -O mediamtx.tar.gz https://github.com/bluenviron/mediamtx/releases/download/${VERSION}/mediamtx_${VERSION}_linux_${ARCH}.tar.gz \
    && tar -xzf mediamtx.tar.gz -C /usr/local/bin/ \
    && rm mediamtx.tar.gz

# 3. Setup Entrypoint and Scripts
COPY start.sh /start.sh
COPY weather.py /weather.py
COPY audio_api.py /audio_api.py
RUN chmod +x /start.sh

# 4. Expose ports (Audio API: 9998)
EXPOSE 9998

# 5. Entrypoint with timezone support
ENTRYPOINT ["/bin/bash", "-c", "export TZ=${WEATHER_TIMEZONE:-America/Toronto} && exec /start.sh"]