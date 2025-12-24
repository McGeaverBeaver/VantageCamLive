#!/bin/bash

# ==============================================================================
#  CONFIGURATION
# ==============================================================================
RTSP_SOURCE="${RTSP_SOURCE:-rtsp://192.168.1.100:8554/stream}"
WORKDIR="/config"
ADMIN_USER="${ADMIN_USER:-cam_admin}"
ADMIN_PASS="${ADMIN_PASS:-your_secure_password}"
VAAPI_DEVICE="${VAAPI_DEVICE:-/dev/dri/renderD128}"

# Feature Toggles
ENABLE_LOCAL_STREAM="${ENABLE_LOCAL_STREAM:-false}"

# YouTube Settings
YOUTUBE_URL="${YOUTUBE_URL:-rtmp://a.rtmp.youtube.com/live2}"
YOUTUBE_KEY="${YOUTUBE_KEY:-}"
YOUTUBE_BITRATE="${YOUTUBE_BITRATE:-4500k}"
YOUTUBE_WIDTH="${YOUTUBE_WIDTH:-2560}"
YOUTUBE_HEIGHT="${YOUTUBE_HEIGHT:-1440}"

# SCALING_MODE is now handled in the Main Stream logic below
SCALING_MODE="${SCALING_MODE:-fill}" 

# Output Settings (Main Stream)
VIDEO_BITRATE="${VIDEO_BITRATE:-14M}"
VIDEO_FPS="${VIDEO_FPS:-30}"

# Settings
WEATHER_ENABLED="${WEATHER_ENABLED:-true}"
UPDATE_INTERVAL="${UPDATE_INTERVAL:-900}"

# Ads / Overlay Settings
SCALE_ADS_TL="${SCALE_TL:-500}"
AD_ROTATE_TIMER_TL="${OVERLAYAD_ROTATE_TIMER:-30}" 
SCALE_ADS_TR="${SCALE_TR:-400}"
TR_SHOW_SECONDS="${TR_SHOW_SECONDS:-20}"
TR_HIDE_SECONDS="${TR_HIDE_SECONDS:-300}"
DAY_START_HOUR="${DAY_START_HOUR:-6}"
DAY_END_HOUR="${DAY_END_HOUR:-20}"

# Folder-based Ad Configuration
ADS_BASE="/config/ads"

# Paths (Internal)
WEATHER_FINAL="$WORKDIR/weather.png"
WEATHER_LIST="$WORKDIR/weather_list.txt"
WEATHER_TEMP="$WORKDIR/weather_temp.png"

# TL Files
AD_FINAL_TL="$WORKDIR/current_ad_tl.png"
AD_TEMP_TL="$WORKDIR/temp_ad_tl.png"
AD_PLAYLIST_TL="$WORKDIR/ad_playlist_tl.txt"

# TR Files
AD_FINAL_TR="$WORKDIR/current_ad_tr.png"
AD_TEMP_TR="$WORKDIR/temp_ad_tr.png"
AD_PLAYLIST_TR="$WORKDIR/ad_playlist_tr.txt"


# ==============================================================================
#  1. SETUP & INITIALIZATION
# ==============================================================================

# ------------------------------------------------------------------------------
#  1.1 Auto-Download Weather Icons (Self-Healing)
# ------------------------------------------------------------------------------
echo "--- Checking Weather Icons ---"
cat <<EOF > /tmp/download_icons.py
import os
import requests
import sys

# Configuration matches your weather.py
DESTINATION_FOLDER = "/config/weather_icons"
REPO_OWNER = "basmilius"
REPO_NAME = "weather-icons"
PATH_TO_FOLDER = "production/fill/png/512"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{PATH_TO_FOLDER}"

def run():
    if not os.path.exists(DESTINATION_FOLDER):
        os.makedirs(DESTINATION_FOLDER)
    
    if len(os.listdir(DESTINATION_FOLDER)) > 5:
        print(f"[INFO] Icons already exist. Skipping download.")
        return

    print(f"[INFO] Icon folder is empty or missing. Downloading from GitHub...")
    try:
        headers = {'User-Agent': 'VantageCamBootScript'}
        response = requests.get(GITHUB_API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        files_data = response.json()
        
        png_files = [item for item in files_data if item['type'] == 'file' and item['name'].endswith('.png')]
        
        for item in png_files:
            file_name = item['name']
            download_url = item['download_url']
            local_path = os.path.join(DESTINATION_FOLDER, file_name)
            
            with requests.get(download_url, stream=True, timeout=15) as r:
                r.raise_for_status()
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
        print("[SUCCESS] All icons downloaded.")

    except Exception as e:
        print(f"[ERROR] Failed to download icons: {e}")

if __name__ == "__main__":
    run()
EOF
python3 /tmp/download_icons.py
rm /tmp/download_icons.py

# ------------------------------------------------------------------------------
#  1.2 Continue Normal Boot
# ------------------------------------------------------------------------------
echo "--- Initializing Ad Folders ---"
mkdir -p "$ADS_BASE/topleft/DAY"
mkdir -p "$ADS_BASE/topleft/NIGHT"
mkdir -p "$ADS_BASE/topright/DAY"
mkdir -p "$ADS_BASE/topright/NIGHT"

echo "--- Configuring RTSP Server ---"
if [ "$ENABLE_LOCAL_STREAM" = "true" ]; then
    RTSP_ADDRESS=":8554"
    echo ">> Local Stream: ENABLED (Accessible on Port 8554)"
else
    RTSP_ADDRESS="127.0.0.1:8554"
    echo ">> Local Stream: DISABLED (Internal Only)"
fi

cat <<EOF > /usr/local/bin/mediamtx.yml
rtspAddress: $RTSP_ADDRESS
readTimeout: 60s
writeTimeout: 60s
api: yes
rtmp: no
hls: no
webrtc: no
srt: no
authMethod: internal
authInternalUsers:
  - user: $ADMIN_USER
    pass: $ADMIN_PASS
    ips: []
    permissions:
      - action: api
      - action: publish
      - action: read
paths:
  all:
EOF

echo "--- Starting RTSP Server ---"
/usr/local/bin/mediamtx /usr/local/bin/mediamtx.yml &
sleep 2

# Start Audio Control API Server
if [ -n "$YOUTUBE_KEY" ]; then
    echo "--- Starting Audio Control API ---"
    python3 /audio_api.py &
    sleep 1
fi

echo "--- Initializing Placeholders ---"
rm -f "$WORKDIR/temp_*.png" "$WORKDIR/*_temp.png"

# 1. Weather Placeholder
if [ ! -f "$WEATHER_FINAL" ]; then
    python3 /weather.py blank "$WEATHER_FINAL" "900" "350"
fi
echo "file '$WEATHER_FINAL'" > "$WEATHER_LIST"
echo "duration 10" >> "$WEATHER_LIST" 
echo "file '$WEATHER_FINAL'" >> "$WEATHER_LIST"

# 2. Ads Placeholders
python3 /weather.py blank "$AD_FINAL_TL" "$SCALE_ADS_TL" "$SCALE_ADS_TL"
echo "file '$AD_FINAL_TL'" > "$AD_PLAYLIST_TL"
echo "duration 10" >> "$AD_PLAYLIST_TL"
echo "file '$AD_FINAL_TL'" >> "$AD_PLAYLIST_TL"

python3 /weather.py blank "$AD_FINAL_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"
echo "file '$AD_FINAL_TR'" > "$AD_PLAYLIST_TR"
echo "duration 10" >> "$AD_PLAYLIST_TR"
echo "file '$AD_FINAL_TR'" >> "$AD_PLAYLIST_TR"


# ==============================================================================
#  2. BACKGROUND MANAGERS
# ==============================================================================

get_mode() {
    local hr=$(date +%-H)
    if [ "$hr" -ge "$DAY_START_HOUR" ] && [ "$hr" -lt "$DAY_END_HOUR" ]; then
        echo "DAY"
    else
        echo "NIGHT"
    fi
}

# --- TL Manager ---
(
    shopt -s nocaseglob nullglob
    while true; do
        MODE=$(get_mode)
        TARGET_DIR="$ADS_BASE/topleft/$MODE"
        FILES=("$TARGET_DIR"/*.png "$TARGET_DIR"/*.jpg "$TARGET_DIR"/*.jpeg)
        
        if [ ${#FILES[@]} -eq 0 ]; then
            python3 /weather.py blank "$AD_FINAL_TL" "$SCALE_ADS_TL" "$SCALE_ADS_TL"
            sleep 60
        else
            for f in "${FILES[@]}"; do
                NEW_MODE=$(get_mode)
                if [ "$NEW_MODE" != "$MODE" ]; then break; fi
                
                if python3 /weather.py ad "$AD_TEMP_TL" "$f" "$SCALE_ADS_TL" "$SCALE_ADS_TL"; then
                    mv -f "$AD_TEMP_TL" "$AD_FINAL_TL"
                    echo "[TL] [$MODE] Showing: $(basename "$f")"
                fi
                sleep "$AD_ROTATE_TIMER_TL"
            done
        fi
    done
) &

# --- TR Manager ---
(
    shopt -s nocaseglob nullglob
    TR_INDEX=0
    while true; do
        MODE=$(get_mode)
        TARGET_DIR="$ADS_BASE/topright/$MODE"
        FILES=("$TARGET_DIR"/*.png "$TARGET_DIR"/*.jpg "$TARGET_DIR"/*.jpeg)
        COUNT=${#FILES[@]}

        if [ $COUNT -eq 0 ]; then
            python3 /weather.py blank "$AD_FINAL_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"
            sleep 60
        else
            if [ $TR_INDEX -ge $COUNT ]; then TR_INDEX=0; fi
            CURRENT_FILE="${FILES[$TR_INDEX]}"
            
            echo "[TR] [$MODE] Showing: $(basename "$CURRENT_FILE")"
            if python3 /weather.py ad "$AD_TEMP_TR" "$CURRENT_FILE" "$SCALE_ADS_TR" "$SCALE_ADS_TR"; then
                mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"
                sleep "$TR_SHOW_SECONDS"
            fi

            python3 /weather.py blank "$AD_TEMP_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"
            mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"
            sleep "$TR_HIDE_SECONDS"
            TR_INDEX=$((TR_INDEX + 1))
        fi
    done
) &

# --- Weather Manager ---
if [ "$WEATHER_ENABLED" = "true" ]; then
    (
        sleep 5 
        while true; do
            python3 /weather.py weather "$WEATHER_TEMP"
            if [ -f "$WEATHER_TEMP" ]; then
                mv -f "$WEATHER_TEMP" "$WEATHER_FINAL"
            fi
            sleep "$UPDATE_INTERVAL"
        done
    ) &
fi

# --- YouTube Restreamer (GPU ACCELERATED + SINGLE SOURCE) ---
if [ -n "$YOUTUBE_KEY" ]; then
    AUDIO_MODE_FILE="/config/audio_mode"
    RESTREAMER_PID_FILE="/config/youtube_restreamer.pid"
    echo "muted" > "$AUDIO_MODE_FILE"
    
    (
        echo "[Stream] YouTube restreamer starting in 10s..."
        echo "[Stream] Target Resolution: ${YOUTUBE_WIDTH}x${YOUTUBE_HEIGHT}"
        sleep 10
        
        # NOTE: WE DO NOT ZOOM HERE ANYMORE.
        # The main stream is already fixed to 16:9, so we just scale to the target YouTube size.
        # This keeps the overlays perfectly in the corners.
        YT_FILTERS="scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=nv12,hwupload"
        
        while true; do
            AUDIO_MODE=$(cat "$AUDIO_MODE_FILE" 2>/dev/null || echo "muted")
            
            if [ "$AUDIO_MODE" = "unmuted" ]; then
                echo "[Stream] YouTube: LIVE AUDIO (Synced)"
                ffmpeg -hide_banner -loglevel error \
                    -init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va \
                    -rtsp_transport tcp -i "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live" \
                    -vf "$YT_FILTERS" \
                    -map 0:v:0 -map 0:a:0? \
                    -c:v h264_vaapi -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60 \
                    -c:a aac -b:a 128k -ac 2 \
                    -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" &
            else
                echo "[Stream] YouTube: MUTED"
                ffmpeg -hide_banner -loglevel error \
                    -init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va \
                    -rtsp_transport tcp -i "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live" \
                    -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
                    -vf "$YT_FILTERS" \
                    -map 0:v:0 -map 1:a:0 \
                    -c:v h264_vaapi -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60 \
                    -c:a aac -b:a 128k \
                    -shortest \
                    -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" &
            fi
            
            FFMPEG_PID=$!
            echo $FFMPEG_PID > "$RESTREAMER_PID_FILE"
            wait $FFMPEG_PID
            sleep 5
        done
    ) &
fi

# ==============================================================================
#  3. MAIN STREAM ENCODING (PASS-THROUGH AUDIO)
# ==============================================================================
echo "--- Starting Main Stream ---"

# FIX: Force the "Canvas" to be 16:9 (2560x1440)
# We apply the crop/fill logic HERE, to the camera input ONLY.

if [ "$SCALING_MODE" = "fill" ]; then
    # FILL MODE: Scale to zoom (increase), then crop.
    # Fixed syntax: flags=bicubic is now attached to scale with a colon
    CAMERA_FILTER="[0:v]scale=2560:1440:force_original_aspect_ratio=increase:flags=bicubic,crop=2560:1440,format=yuv420p[base]"
else
    # FIT MODE: Scale to fit (decrease), then pad.
    # Fixed syntax: flags=bicubic is now attached to scale with a colon
    CAMERA_FILTER="[0:v]scale=2560:1440:force_original_aspect_ratio=decrease:flags=bicubic,pad=2560:1440:(ow-iw)/2:(oh-ih)/2,format=yuv420p[base]"
fi

INPUTS="-thread_queue_size 1024 -rtsp_transport tcp -i $RTSP_SOURCE"
FILTER_CHAIN="$CAMERA_FILTER"
LAST_V="base"
INPUT_COUNT=1

add_overlay() {
    local path=$1; local pos=$2; local width=$3; local height=$4
    local coords=""
    case $pos in
        tl) coords="20:20" ;;
        tr) coords="main_w-overlay_w-20:20" ;;
        br) coords="main_w-overlay_w-20:main_h-overlay_h-20" ;;
    esac

    INPUTS="$INPUTS -f concat -safe 0 -stream_loop -1 -i $path"
    
    local scale_cmd=""
    if [ -n "$height" ]; then
        scale_cmd="scale=${width}:${height}"
    else
        scale_cmd="scale=${width}:${width}" 
    fi

    FILTER_CHAIN="${FILTER_CHAIN};[${INPUT_COUNT}:v]${scale_cmd},format=rgba[ovr${INPUT_COUNT}];[${LAST_V}][ovr${INPUT_COUNT}]overlay=${coords}:eof_action=pass:shortest=0[v${INPUT_COUNT}]"
    LAST_V="v$INPUT_COUNT"
    INPUT_COUNT=$((INPUT_COUNT+1))
}

add_overlay "$AD_PLAYLIST_TL" "tl" "$SCALE_ADS_TL" ""
add_overlay "$AD_PLAYLIST_TR" "tr" "$SCALE_ADS_TR" ""
if [ "$WEATHER_ENABLED" = "true" ] && [ -f "$WEATHER_LIST" ]; then 
    add_overlay "$WEATHER_LIST" "br" "900" "350"
fi

FINAL_FILTERS="${FILTER_CHAIN};[${LAST_V}]format=nv12[soft_final];[soft_final]hwupload[vfinal]"

while true; do
    ffmpeg -hide_banner -loglevel warning -init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va \
    $INPUTS \
    -filter_complex "$FINAL_FILTERS" \
    -map "[vfinal]" \
    -map 0:a? \
    -c:v h264_vaapi -b:v $VIDEO_BITRATE -maxrate $VIDEO_BITRATE -bufsize 28M -r $VIDEO_FPS -g $(($VIDEO_FPS * 2)) \
    -c:a copy \
    -f rtsp -rtsp_transport tcp "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live"
    
    sleep 5
done