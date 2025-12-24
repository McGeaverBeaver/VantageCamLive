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
ENABLE_LOCAL_STREAM="${ENABLE_LOCAL_STREAM:-false}" # New Toggle

# YouTube Settings
YOUTUBE_URL="${YOUTUBE_URL:-rtmp://a.rtmp.youtube.com/live2}"
YOUTUBE_KEY="${YOUTUBE_KEY:-}"

# Output Settings
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
echo "--- Initializing Ad Folders ---"
mkdir -p "$ADS_BASE/topleft/DAY"
mkdir -p "$ADS_BASE/topleft/NIGHT"
mkdir -p "$ADS_BASE/topright/DAY"
mkdir -p "$ADS_BASE/topright/NIGHT"

echo "--- Configuring RTSP Server ---"
# Logic: If Local Stream is enabled, bind to all interfaces (:8554).
# If disabled, bind only to localhost (127.0.0.1:8554) so only internal ffmpeg can see it.
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

# --- YouTube Restreamer (UNIVERSAL FIT) ---
if [ -n "$YOUTUBE_KEY" ]; then
    AUDIO_MODE_FILE="/config/audio_mode"
    RESTREAMER_PID_FILE="/config/youtube_restreamer.pid"
    echo "muted" > "$AUDIO_MODE_FILE"
    
    (
        echo "[Stream] YouTube restreamer starting in 10s..."
        sleep 10
        
        # UNIVERSAL FILTER:
        # 1. scale=...:decrease -> Fit image inside 1920x1080 without stretching
        # 2. pad=... -> Fill the rest of the 1920x1080 frame with black bars
        # This works for Wide (you), Normal (16:9), and Tall (9:16) users perfectly.
        YT_FLAGS="-c:v libx264 -preset veryfast -b:v 4500k -maxrate 4500k -bufsize 9000k -pix_fmt yuv420p -g 60 -vf scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
        
        while true; do
            AUDIO_MODE=$(cat "$AUDIO_MODE_FILE" 2>/dev/null || echo "muted")
            
            if [ "$AUDIO_MODE" = "unmuted" ]; then
                echo "[Stream] YouTube: LIVE AUDIO (Universal Fit)"
                ffmpeg -hide_banner -loglevel error \
                    -rtsp_transport tcp -i "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live" \
                    -rtsp_transport tcp -i "${RTSP_SOURCE}" \
                    -map 0:v:0 -map 1:a:0? \
                    $YT_FLAGS \
                    -c:a aac -b:a 128k -ac 2 \
                    -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" &
            else
                echo "[Stream] YouTube: MUTED (Universal Fit)"
                ffmpeg -hide_banner -loglevel error \
                    -rtsp_transport tcp -i "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live" \
                    -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
                    $YT_FLAGS \
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
#  3. MAIN STREAM ENCODING
# ==============================================================================
echo "--- Starting Main Stream ---"

INPUTS="-thread_queue_size 1024 -rtsp_transport tcp -i $RTSP_SOURCE"
FILTER_CHAIN="[0:v]scale=3840:-1:flags=bicubic,format=yuv420p[base]"
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
    -c:v h264_vaapi -b:v $VIDEO_BITRATE -maxrate $VIDEO_BITRATE -bufsize 28M -r $VIDEO_FPS -g $(($VIDEO_FPS * 2)) \
    -f rtsp -rtsp_transport tcp "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live"
    
    sleep 5
done