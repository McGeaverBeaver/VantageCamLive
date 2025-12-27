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
SCALING_MODE="${SCALING_MODE:-fill}" 

# Output Settings
VIDEO_BITRATE="${VIDEO_BITRATE:-14M}"
VIDEO_FPS="${VIDEO_FPS:-30}"
WEATHER_ENABLED="${WEATHER_ENABLED:-true}"
# Renamed per request
ALERTS_UPDATE_INTERVAL="${ALERTS_UPDATE_INTERVAL:-900}"

# Ads / Overlay Settings
SCALE_ADS_TL="${SCALE_TL:-500}"
AD_ROTATE_TIMER_TL="${OVERLAYAD_ROTATE_TIMER:-30}" 
SCALE_ADS_TR="${SCALE_TR:-400}"
TR_SHOW_SECONDS="${TR_SHOW_SECONDS:-20}"
TR_HIDE_SECONDS="${TR_HIDE_SECONDS:-300}"
DAY_START_HOUR="${DAY_START_HOUR:-6}"
DAY_END_HOUR="${DAY_END_HOUR:-20}"
ADS_BASE="/config/ads"

# Paths
WEATHER_FINAL="$WORKDIR/weather.png"
WEATHER_LIST="$WORKDIR/weather_list.txt"
WEATHER_TEMP="$WORKDIR/weather_temp.png"
ALERT_FINAL="$WORKDIR/alert.png"
ALERT_LIST="$WORKDIR/alert_list.txt"
ALERT_TEMP="$WORKDIR/alert_temp.png"

# Ad Files
AD_FINAL_TL="$WORKDIR/current_ad_tl.png"
AD_TEMP_TL="$WORKDIR/temp_ad_tl.png"
AD_PLAYLIST_TL="$WORKDIR/ad_playlist_tl.txt"
AD_FINAL_TR="$WORKDIR/current_ad_tr.png"
AD_TEMP_TR="$WORKDIR/temp_ad_tr.png"
AD_PLAYLIST_TR="$WORKDIR/ad_playlist_tr.txt"

# ==============================================================================
#  1. SETUP & INITIALIZATION
# ==============================================================================

echo "--- 1. Checking Weather Icons ---"
cat <<EOF > /tmp/download_icons.py
import os, requests
DESTINATION_FOLDER = "/config/weather_icons"
REPO_OWNER = "basmilius"
REPO_NAME = "weather-icons"
PATH_TO_FOLDER = "production/fill/png/512"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{PATH_TO_FOLDER}"
def run():
    if not os.path.exists(DESTINATION_FOLDER): os.makedirs(DESTINATION_FOLDER)
    if len(os.listdir(DESTINATION_FOLDER)) > 5: return
    try:
        headers = {'User-Agent': 'VantageCamBoot'}
        resp = requests.get(GITHUB_API_URL, headers=headers, timeout=10)
        resp.raise_for_status()
        for item in [i for i in resp.json() if i['type']=='file' and i['name'].endswith('.png')]:
            with requests.get(item['download_url'], stream=True) as r, open(os.path.join(DESTINATION_FOLDER, item['name']), 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
    except Exception as e: print(f"[ERROR] Icon download failed: {e}")
if __name__ == "__main__": run()
EOF
python3 /tmp/download_icons.py
rm /tmp/download_icons.py

echo "--- Initializing Ad Folders ---"
mkdir -p "$ADS_BASE/topleft/DAY" "$ADS_BASE/topleft/NIGHT"
mkdir -p "$ADS_BASE/topright/DAY" "$ADS_BASE/topright/NIGHT"

echo "--- Configuring RTSP Server ---"
if [ "$ENABLE_LOCAL_STREAM" = "true" ]; then RTSP_ADDRESS=":8554"; else RTSP_ADDRESS="127.0.0.1:8554"; fi

cat <<EOF > /usr/local/bin/mediamtx.yml
rtspAddress: $RTSP_ADDRESS
readTimeout: 60s
writeTimeout: 60s
api: yes
authMethod: internal
authInternalUsers:
  - user: $ADMIN_USER
    pass: $ADMIN_PASS
    permissions: [ { action: api }, { action: publish }, { action: read } ]
paths:
  all:
EOF

/usr/local/bin/mediamtx /usr/local/bin/mediamtx.yml &
sleep 2

if [ -n "$YOUTUBE_KEY" ]; then
    python3 /audio_api.py &
    sleep 1
fi

echo "--- Initializing Placeholders ---"
# Weather (900x350)
if [ ! -f "$WEATHER_FINAL" ]; then python3 /weather.py blank "$WEATHER_FINAL" "900" "350"; fi
echo "file '$WEATHER_FINAL'" > "$WEATHER_LIST"; echo "duration 10" >> "$WEATHER_LIST"; echo "file '$WEATHER_FINAL'" >> "$WEATHER_LIST"

# Alerts (900x150)
if [ ! -f "$ALERT_FINAL" ]; then python3 /weather.py blank "$ALERT_FINAL" "900" "150"; fi
echo "file '$ALERT_FINAL'" > "$ALERT_LIST"; echo "duration 10" >> "$ALERT_LIST"; echo "file '$ALERT_FINAL'" >> "$ALERT_LIST"

# Ads
python3 /weather.py blank "$AD_FINAL_TL" "$SCALE_ADS_TL" "$SCALE_ADS_TL"
echo "file '$AD_FINAL_TL'" > "$AD_PLAYLIST_TL"; echo "duration 10" >> "$AD_PLAYLIST_TL"; echo "file '$AD_FINAL_TL'" >> "$AD_PLAYLIST_TL"
python3 /weather.py blank "$AD_FINAL_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"
echo "file '$AD_FINAL_TR'" > "$AD_PLAYLIST_TR"; echo "duration 10" >> "$AD_PLAYLIST_TR"; echo "file '$AD_FINAL_TR'" >> "$AD_PLAYLIST_TR"

# ==============================================================================
#  2. BACKGROUND MANAGERS
# ==============================================================================
get_mode() {
    local hr=$(date +%-H)
    if [ "$hr" -ge "$DAY_START_HOUR" ] && [ "$hr" -lt "$DAY_END_HOUR" ]; then echo "DAY"; else echo "NIGHT"; fi
}

# TL Manager
(
    shopt -s nocaseglob nullglob
    while true; do
        MODE=$(get_mode); TARGET_DIR="$ADS_BASE/topleft/$MODE"
        FILES=("$TARGET_DIR"/*.png "$TARGET_DIR"/*.jpg "$TARGET_DIR"/*.jpeg)
        if [ ${#FILES[@]} -eq 0 ]; then
            python3 /weather.py blank "$AD_FINAL_TL" "$SCALE_ADS_TL" "$SCALE_ADS_TL"; sleep 60
        else
            for f in "${FILES[@]}"; do
                if [ "$(get_mode)" != "$MODE" ]; then break; fi
                if python3 /weather.py ad "$AD_TEMP_TL" "$f" "$SCALE_ADS_TL" "$SCALE_ADS_TL"; then mv -f "$AD_TEMP_TL" "$AD_FINAL_TL"; fi
                sleep "$AD_ROTATE_TIMER_TL"
            done
        fi
    done
) &

# TR Manager
(
    shopt -s nocaseglob nullglob
    TR_INDEX=0
    while true; do
        MODE=$(get_mode); TARGET_DIR="$ADS_BASE/topright/$MODE"
        FILES=("$TARGET_DIR"/*.png "$TARGET_DIR"/*.jpg "$TARGET_DIR"/*.jpeg)
        if [ ${#FILES[@]} -eq 0 ]; then
            python3 /weather.py blank "$AD_FINAL_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"; sleep 60
        else
            if [ $TR_INDEX -ge ${#FILES[@]} ]; then TR_INDEX=0; fi
            if python3 /weather.py ad "$AD_TEMP_TR" "${FILES[$TR_INDEX]}" "$SCALE_ADS_TR" "$SCALE_ADS_TR"; then
                mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"; sleep "$TR_SHOW_SECONDS"
            fi
            python3 /weather.py blank "$AD_TEMP_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"
            mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"; sleep "$TR_HIDE_SECONDS"
            TR_INDEX=$((TR_INDEX + 1))
        fi
    done
) &

# --- Weather & Alert Manager ---
if [ "$WEATHER_ENABLED" = "true" ]; then
    (
        sleep 5 
        while true; do
            # 1. Update Bottom-Right Weather
            python3 /weather.py weather "$WEATHER_TEMP"
            if [ -f "$WEATHER_TEMP" ]; then mv -f "$WEATHER_TEMP" "$WEATHER_FINAL"; fi
            
            # 2. Update Alerts (Stacked)
            python3 /weather.py alerts "$ALERT_TEMP"
            if [ -f "$ALERT_TEMP" ]; then mv -f "$ALERT_TEMP" "$ALERT_FINAL"; fi
            
            # WAIT for next cycle
            sleep "$ALERTS_UPDATE_INTERVAL"
        done
    ) &
fi

# YouTube Restreamer
if [ -n "$YOUTUBE_KEY" ]; then
    echo "muted" > "/config/audio_mode"
    (
        sleep 10
        YT_FILTERS="scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=nv12,hwupload"
        while true; do
            AUDIO_MODE=$(cat "/config/audio_mode" 2>/dev/null || echo "muted")
            if [ "$AUDIO_MODE" = "unmuted" ]; then
                ffmpeg -hide_banner -loglevel error \
                    -init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va \
                    -rtsp_transport tcp -i "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live" \
                    -vf "$YT_FILTERS" -map 0:v:0 -map 0:a:0? \
                    -c:v h264_vaapi -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60 \
                    -c:a aac -b:a 128k -ac 2 -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" &
            else
                ffmpeg -hide_banner -loglevel error \
                    -init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va \
                    -rtsp_transport tcp -i "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live" \
                    -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
                    -vf "$YT_FILTERS" -map 0:v:0 -map 1:a:0 \
                    -c:v h264_vaapi -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60 \
                    -c:a aac -b:a 128k -shortest -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" &
            fi
            FFMPEG_PID=$!; echo $FFMPEG_PID > "/config/youtube_restreamer.pid"; wait $FFMPEG_PID; sleep 5
        done
    ) &
fi

# ==============================================================================
#  3. MAIN STREAM ENCODING
# ==============================================================================
echo "--- Starting Main Stream ---"

if [ "$SCALING_MODE" = "fill" ]; then
    CAMERA_FILTER="[0:v]scale=2560:1440:force_original_aspect_ratio=increase:flags=bicubic,crop=2560:1440,format=yuv420p[base]"
else
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
        bl) coords="20:main_h-overlay_h-20" ;;
        
        # --- NEW ALERT POSITION: Stacked ---
        # Weather height (350) + Margin (20) = 370px from bottom
        br_alert) coords="main_w-overlay_w-20:main_h-overlay_h-370" ;;
    esac

    INPUTS="$INPUTS -f concat -safe 0 -stream_loop -1 -i $path"
    local scale_cmd=""; if [ -n "$height" ]; then scale_cmd="scale=${width}:${height}"; else scale_cmd="scale=${width}:${width}"; fi
    FILTER_CHAIN="${FILTER_CHAIN};[${INPUT_COUNT}:v]${scale_cmd},format=rgba[ovr${INPUT_COUNT}];[${LAST_V}][ovr${INPUT_COUNT}]overlay=${coords}:eof_action=pass:shortest=0[v${INPUT_COUNT}]"
    LAST_V="v$INPUT_COUNT"
    INPUT_COUNT=$((INPUT_COUNT+1))
}

add_overlay "$AD_PLAYLIST_TL" "tl" "$SCALE_ADS_TL" ""
add_overlay "$AD_PLAYLIST_TR" "tr" "$SCALE_ADS_TR" ""

if [ "$WEATHER_ENABLED" = "true" ]; then 
    # 1. Weather (Bottom Right)
    add_overlay "$WEATHER_LIST" "br" "900" "350"
    
    # 2. Alert (Stacked above it)
    add_overlay "$ALERT_LIST" "br_alert" "900" "150"
fi

FINAL_FILTERS="${FILTER_CHAIN};[${LAST_V}]format=nv12[soft_final];[soft_final]hwupload[vfinal]"

while true; do
    ffmpeg -hide_banner -loglevel warning -init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va \
    $INPUTS \
    -filter_complex "$FINAL_FILTERS" \
    -map "[vfinal]" -map 0:a? \
    -c:v h264_vaapi -b:v $VIDEO_BITRATE -maxrate $VIDEO_BITRATE -bufsize 28M -r $VIDEO_FPS -g $(($VIDEO_FPS * 2)) \
    -c:a copy \
    -f rtsp -rtsp_transport tcp "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live"
    sleep 5
done