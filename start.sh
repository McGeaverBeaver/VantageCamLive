#!/bin/bash

# ==============================================================================
#  CONFIGURATION
# ==============================================================================
RTSP_SOURCE="${RTSP_SOURCE:-rtsp://192.168.1.100:8554/stream}"
WORKDIR="/config"
ADMIN_USER="${ADMIN_USER:-cam_admin}"
ADMIN_PASS="${ADMIN_PASS:-your_secure_password}"

# Hardware Acceleration (set to 'false' for software encoding)
HARDWARE_ACCEL="${HARDWARE_ACCEL:-true}"
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
ALERTS_UPDATE_INTERVAL="${ALERTS_UPDATE_INTERVAL:-900}"

# Software Encoding Settings (only used when HARDWARE_ACCEL=false)
SOFTWARE_PRESET="${SOFTWARE_PRESET:-faster}"  # ultrafast, superfast, veryfast, faster, fast, medium
SOFTWARE_CRF="${SOFTWARE_CRF:-23}"

# Ads / Overlay Settings
SCALE_ADS_TL="${SCALE_TL:-500}"
AD_ROTATE_TIMER_TL="${OVERLAYAD_ROTATE_TIMER:-30}" 
SCALE_ADS_TR="${SCALE_TR:-400}"
TR_SHOW_SECONDS="${TR_SHOW_SECONDS:-20}"
TR_HIDE_SECONDS="${TR_HIDE_SECONDS:-300}"
DAY_START_HOUR="${DAY_START_HOUR:-6}"
DAY_END_HOUR="${DAY_END_HOUR:-20}"
ADS_BASE="/config/ads"

# Flashing settings for red warnings
FLASH_ON_DURATION="${FLASH_ON_DURATION:-0.7}"   # Seconds "on" state shown
FLASH_OFF_DURATION="${FLASH_OFF_DURATION:-0.3}" # Seconds "off" (dimmed) state shown

# Watchdog Settings (Self-Healing)
WATCHDOG_ENABLED="${WATCHDOG_ENABLED:-false}"

# Direct-to-YouTube mode: Skip MediaMTX when only streaming to YouTube
# This saves CPU by eliminating the internal RTSP encode/decode cycle
if [ -n "$YOUTUBE_KEY" ] && [ "$ENABLE_LOCAL_STREAM" != "true" ]; then
    DIRECT_YOUTUBE_MODE="true"
else
    DIRECT_YOUTUBE_MODE="false"
fi

# Paths
WEATHER_COMBINED="$WORKDIR/weather_combined.png"  # Combined weather+alerts
WEATHER_COMBINED_FLASH="$WORKDIR/weather_combined_flash.png"  # Flash frame
WEATHER_META="$WORKDIR/weather_combined_meta.txt"  # Metadata from Python
WEATHER_LIST="$WORKDIR/weather_list.txt"
WEATHER_TEMP="$WORKDIR/weather_temp.png"

# Ad Files
AD_FINAL_TL="$WORKDIR/current_ad_tl.png"
AD_TEMP_TL="$WORKDIR/temp_ad_tl.png"
AD_PLAYLIST_TL="$WORKDIR/ad_playlist_tl.txt"
AD_FINAL_TR="$WORKDIR/current_ad_tr.png"
AD_TEMP_TR="$WORKDIR/temp_ad_tr.png"
AD_PLAYLIST_TR="$WORKDIR/ad_playlist_tr.txt"

# FFmpeg Progress file for watchdog monitoring
FFMPEG_PROGRESS_FILE="$WORKDIR/ffmpeg_progress.txt"

# Cache control
LAST_AD_HASH_TL=""
LAST_AD_HASH_TR=""

# ==============================================================================
#  HELPER FUNCTIONS
# ==============================================================================
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

cleanup() {
    log "Shutting down..."
    pkill -P $$ 2>/dev/null
    # Also kill any watchdog process
    pkill -f "watchdog.py" 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT

check_vaapi() {
    if [ "$HARDWARE_ACCEL" = "true" ]; then
        if [ ! -e "$VAAPI_DEVICE" ]; then
            log "WARNING: VAAPI device $VAAPI_DEVICE not found. Falling back to software encoding."
            HARDWARE_ACCEL="false"
            return 1
        fi
        # Quick test of VAAPI
        if ! ffmpeg -hide_banner -init_hw_device vaapi=va:$VAAPI_DEVICE -f lavfi -i nullsrc=s=64x64:d=1 -vf 'format=nv12,hwupload' -c:v h264_vaapi -f null - 2>/dev/null; then
            log "WARNING: VAAPI encoding test failed. Falling back to software encoding."
            HARDWARE_ACCEL="false"
            return 1
        fi
        log "VAAPI hardware acceleration enabled on $VAAPI_DEVICE"
        return 0
    else
        log "Software encoding mode (HARDWARE_ACCEL=false)"
        return 1
    fi
}

# Update weather playlist based on flash state
update_weather_playlist() {
    local needs_flash=$1
    
    if [ "$needs_flash" = "1" ] && [ -f "$WEATHER_COMBINED_FLASH" ]; then
        # Flashing playlist - alternates between on and off states
        cat > "$WEATHER_LIST" <<EOF
file '$WEATHER_COMBINED'
duration $FLASH_ON_DURATION
file '$WEATHER_COMBINED_FLASH'
duration $FLASH_OFF_DURATION
file '$WEATHER_COMBINED'
duration $FLASH_ON_DURATION
file '$WEATHER_COMBINED_FLASH'
duration $FLASH_OFF_DURATION
file '$WEATHER_COMBINED'
duration $FLASH_ON_DURATION
file '$WEATHER_COMBINED_FLASH'
duration $FLASH_OFF_DURATION
file '$WEATHER_COMBINED'
duration $FLASH_ON_DURATION
file '$WEATHER_COMBINED_FLASH'
duration $FLASH_OFF_DURATION
file '$WEATHER_COMBINED'
duration $FLASH_ON_DURATION
file '$WEATHER_COMBINED_FLASH'
duration $FLASH_OFF_DURATION
file '$WEATHER_COMBINED'
EOF
        log "[Weather] Flashing playlist enabled for RED WARNING"
    else
        # Standard non-flashing playlist
        cat > "$WEATHER_LIST" <<EOF
file '$WEATHER_COMBINED'
duration 10
file '$WEATHER_COMBINED'
EOF
    fi
}

# ==============================================================================
#  1. SETUP & INITIALIZATION
# ==============================================================================

log "--- 1. Checking Hardware Acceleration ---"
check_vaapi

log "--- 2. Checking Weather Icons ---"
cat <<'EOF' > /tmp/download_icons.py
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

log "--- Initializing Ad Folders ---"
mkdir -p "$ADS_BASE/topleft/DAY" "$ADS_BASE/topleft/NIGHT"
mkdir -p "$ADS_BASE/topright/DAY" "$ADS_BASE/topright/NIGHT"

log "--- Configuring Stream Output ---"
if [ "$DIRECT_YOUTUBE_MODE" = "true" ]; then
    log "Direct-to-YouTube mode enabled (skipping MediaMTX for efficiency)"
else
    log "MediaMTX mode enabled (local stream available)"
    if [ "$ENABLE_LOCAL_STREAM" = "true" ]; then RTSP_ADDRESS=":8554"; else RTSP_ADDRESS="127.0.0.1:8554"; fi

    cat <<EOF > /usr/local/bin/mediamtx.yml
# RTSP - Primary protocol (required)
rtspAddress: $RTSP_ADDRESS
readTimeout: 60s
writeTimeout: 60s

# Disable unused protocols to save resources
rtmpDisable: yes
hlsDisable: yes
webrtcDisable: yes
srtDisable: yes

# API for health checks
api: yes
apiAddress: 127.0.0.1:9997

# Authentication
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
fi

if [ -n "$YOUTUBE_KEY" ]; then
    python3 /audio_api.py &
    sleep 1
fi

log "--- Initializing Placeholders ---"
# Combined Weather+Alerts (900x500 = 350 weather + 150 alerts max)
if [ ! -f "$WEATHER_COMBINED" ]; then python3 /weather.py blank "$WEATHER_COMBINED" "900" "500"; fi
update_weather_playlist "0"

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

# TL Manager - with hash-based caching
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
                # Skip if file hasn't changed (hash check)
                CURRENT_HASH=$(md5sum "$f" 2>/dev/null | cut -d' ' -f1)
                if [ "$CURRENT_HASH" != "$LAST_AD_HASH_TL" ] || [ ! -f "$AD_FINAL_TL" ]; then
                    if python3 /weather.py ad "$AD_TEMP_TL" "$f" "$SCALE_ADS_TL" "$SCALE_ADS_TL"; then 
                        mv -f "$AD_TEMP_TL" "$AD_FINAL_TL"
                        LAST_AD_HASH_TL="$CURRENT_HASH"
                    fi
                fi
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
            CURRENT_HASH=$(md5sum "${FILES[$TR_INDEX]}" 2>/dev/null | cut -d' ' -f1)
            if [ "$CURRENT_HASH" != "$LAST_AD_HASH_TR" ] || [ ! -f "$AD_FINAL_TR" ]; then
                if python3 /weather.py ad "$AD_TEMP_TR" "${FILES[$TR_INDEX]}" "$SCALE_ADS_TR" "$SCALE_ADS_TR"; then
                    mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"
                    LAST_AD_HASH_TR="$CURRENT_HASH"
                fi
            fi
            sleep "$TR_SHOW_SECONDS"
            python3 /weather.py blank "$AD_TEMP_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"
            mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"
            LAST_AD_HASH_TR=""  # Reset so next ad gets processed
            sleep "$TR_HIDE_SECONDS"
            TR_INDEX=$((TR_INDEX + 1))
        fi
    done
) &

# --- Weather & Alert Manager (Combined with Flashing Support) ---
if [ "$WEATHER_ENABLED" = "true" ]; then
    (
        sleep 5 
        while true; do
            # Generate combined weather+alerts overlay
            python3 /weather.py combined "$WEATHER_TEMP"
            
            if [ -f "$WEATHER_TEMP" ]; then 
                mv -f "$WEATHER_TEMP" "$WEATHER_COMBINED"
                
                # Check for flash frame
                FLASH_TEMP="${WEATHER_TEMP%.png}_flash.png"
                if [ -f "$FLASH_TEMP" ]; then
                    mv -f "$FLASH_TEMP" "$WEATHER_COMBINED_FLASH"
                else
                    # Remove old flash frame if no longer needed
                    rm -f "$WEATHER_COMBINED_FLASH"
                fi
                
                # Read metadata and update playlist
                META_TEMP="${WEATHER_TEMP%.png}_meta.txt"
                if [ -f "$META_TEMP" ]; then
                    NEEDS_FLASH=$(grep "needs_flash=" "$META_TEMP" | cut -d'=' -f2)
                    IS_STATEMENT=$(grep "is_statement=" "$META_TEMP" | cut -d'=' -f2)
                    
                    # Update playlist based on flash state
                    update_weather_playlist "$NEEDS_FLASH"
                    
                    if [ "$IS_STATEMENT" = "1" ]; then
                        log "[Weather] Statement alert active (compact display)"
                    fi
                    
                    mv -f "$META_TEMP" "$WEATHER_META"
                fi
            fi
            
            # For flashing alerts, update more frequently
            NEEDS_FLASH=$(grep "needs_flash=" "$WEATHER_META" 2>/dev/null | cut -d'=' -f2)
            if [ "$NEEDS_FLASH" = "1" ]; then
                # Update every 60 seconds for active warnings (keep flash fresh)
                sleep 60
            else
                sleep "$ALERTS_UPDATE_INTERVAL"
            fi
        done
    ) &
fi

# YouTube Restreamer - Only needed when using MediaMTX (not in direct mode)
if [ -n "$YOUTUBE_KEY" ] && [ "$DIRECT_YOUTUBE_MODE" != "true" ]; then
    echo "muted" > "/config/audio_mode"
    (
        sleep 10
        while true; do
            AUDIO_MODE=$(cat "/config/audio_mode" 2>/dev/null || echo "muted")
            
            if [ "$HARDWARE_ACCEL" = "true" ]; then
                # Hardware-accelerated YouTube encoding
                YT_FILTERS="scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=nv12,hwupload"
                HW_INIT="-init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va"
                VIDEO_CODEC="-c:v h264_vaapi -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
            else
                # Software YouTube encoding
                YT_FILTERS="scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT}"
                HW_INIT=""
                VIDEO_CODEC="-c:v libx264 -preset $SOFTWARE_PRESET -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
            fi
            
            if [ "$AUDIO_MODE" = "unmuted" ]; then
                ffmpeg -hide_banner -loglevel error \
                    $HW_INIT \
                    -rtsp_transport tcp -i "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live" \
                    -vf "$YT_FILTERS" -map 0:v:0 -map 0:a:0? \
                    $VIDEO_CODEC \
                    -c:a aac -b:a 128k -ac 2 \
                    -progress "$FFMPEG_PROGRESS_FILE" \
                    -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" &
            else
                ffmpeg -hide_banner -loglevel error \
                    $HW_INIT \
                    -rtsp_transport tcp -i "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live" \
                    -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
                    -vf "$YT_FILTERS" -map 0:v:0 -map 1:a:0 \
                    $VIDEO_CODEC \
                    -c:a aac -b:a 128k -shortest \
                    -progress "$FFMPEG_PROGRESS_FILE" \
                    -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" &
            fi
            FFMPEG_PID=$!; echo $FFMPEG_PID > "/config/youtube_restreamer.pid"; wait $FFMPEG_PID; sleep 5
        done
    ) &
fi

# Initialize audio mode for direct mode
if [ "$DIRECT_YOUTUBE_MODE" = "true" ]; then
    echo "muted" > "/config/audio_mode"
fi

# ==============================================================================
#  2.5 START WATCHDOG (Self-Healing)
# ==============================================================================
if [ "$WATCHDOG_ENABLED" = "true" ] && [ -n "$YOUTUBE_KEY" ]; then
    log "--- Starting Self-Healing Watchdog ---"
    python3 /watchdog.py &
    WATCHDOG_PID=$!
    log "Watchdog started (PID: $WATCHDOG_PID)"
else
    if [ "$WATCHDOG_ENABLED" = "true" ]; then
        log "Watchdog enabled but no YOUTUBE_KEY set - skipping"
    else
        log "Watchdog disabled (WATCHDOG_ENABLED=false)"
    fi
fi

# ==============================================================================
#  3. MAIN STREAM ENCODING
# ==============================================================================
log "--- Starting Main Stream (Hardware: $HARDWARE_ACCEL, Direct YouTube: $DIRECT_YOUTUBE_MODE) ---"

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
    esac

    INPUTS="$INPUTS -f concat -safe 0 -stream_loop -1 -i $path"
    local scale_cmd=""
    if [ -n "$height" ]; then scale_cmd="scale=${width}:${height}"; else scale_cmd="scale=${width}:${width}"; fi
    FILTER_CHAIN="${FILTER_CHAIN};[${INPUT_COUNT}:v]${scale_cmd},format=rgba[ovr${INPUT_COUNT}];[${LAST_V}][ovr${INPUT_COUNT}]overlay=${coords}:eof_action=pass:shortest=0[v${INPUT_COUNT}]"
    LAST_V="v$INPUT_COUNT"
    INPUT_COUNT=$((INPUT_COUNT+1))
}

add_overlay "$AD_PLAYLIST_TL" "tl" "$SCALE_ADS_TL" ""
add_overlay "$AD_PLAYLIST_TR" "tr" "$SCALE_ADS_TR" ""

if [ "$WEATHER_ENABLED" = "true" ]; then 
    # Single combined weather+alerts overlay
    # Fixed height: 500px (150 alert + 350 weather) - never changes to prevent FFmpeg crashes
    add_overlay "$WEATHER_LIST" "br" "900" "500"
fi

# ==============================================================================
#  DIRECT-TO-YOUTUBE MODE (Single FFmpeg, no MediaMTX)
# ==============================================================================
if [ "$DIRECT_YOUTUBE_MODE" = "true" ]; then
    log "--- Direct YouTube Mode: Single FFmpeg pipeline ---"
    
    while true; do
        AUDIO_MODE=$(cat "/config/audio_mode" 2>/dev/null || echo "muted")
        
        if [ "$HARDWARE_ACCEL" = "true" ]; then
            FINAL_FILTERS="${FILTER_CHAIN};[${LAST_V}]scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=nv12[soft_final];[soft_final]hwupload[vfinal]"
            HW_INIT="-init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va"
            VIDEO_CODEC="-c:v h264_vaapi -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
        else
            FINAL_FILTERS="${FILTER_CHAIN};[${LAST_V}]scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=yuv420p[vfinal]"
            HW_INIT=""
            VIDEO_CODEC="-c:v libx264 -preset $SOFTWARE_PRESET -crf $SOFTWARE_CRF -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
        fi
        
        if [ "$AUDIO_MODE" = "unmuted" ]; then
            # Use camera audio
            ffmpeg -hide_banner -loglevel warning $HW_INIT \
                $INPUTS \
                -filter_complex "$FINAL_FILTERS" \
                -map "[vfinal]" -map 0:a? \
                $VIDEO_CODEC \
                -c:a aac -b:a 128k -ac 2 \
                -progress "$FFMPEG_PROGRESS_FILE" \
                -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" &
        else
            # Muted - use silent audio
            ffmpeg -hide_banner -loglevel warning $HW_INIT \
                $INPUTS \
                -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
                -filter_complex "$FINAL_FILTERS" \
                -map "[vfinal]" -map $((INPUT_COUNT)):a \
                $VIDEO_CODEC \
                -c:a aac -b:a 128k \
                -progress "$FFMPEG_PROGRESS_FILE" \
                -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" &
        fi
        
        FFMPEG_PID=$!
        echo $FFMPEG_PID > "/config/youtube_restreamer.pid"
        log "FFmpeg started (PID: $FFMPEG_PID)"
        
        # Wait for FFmpeg OR audio mode change
        while kill -0 $FFMPEG_PID 2>/dev/null; do
            NEW_MODE=$(cat "/config/audio_mode" 2>/dev/null || echo "muted")
            if [ "$NEW_MODE" != "$AUDIO_MODE" ]; then
                log "[Audio] Mode changed to $NEW_MODE, restarting stream..."
                kill $FFMPEG_PID 2>/dev/null
                sleep 2
                break
            fi
            sleep 1
        done
        
        # If FFmpeg died on its own, wait a bit before restart
        if ! kill -0 $FFMPEG_PID 2>/dev/null; then
            wait $FFMPEG_PID 2>/dev/null
            EXIT_CODE=$?
            log "FFmpeg exited with code $EXIT_CODE, restarting in 5 seconds..."
            sleep 5
        fi
    done

# ==============================================================================
#  MEDIAMTX MODE (Two FFmpeg processes - encoder + restreamer)
# ==============================================================================
else
    if [ "$HARDWARE_ACCEL" = "true" ]; then
        FINAL_FILTERS="${FILTER_CHAIN};[${LAST_V}]format=nv12[soft_final];[soft_final]hwupload[vfinal]"
        HW_INIT="-init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va"
        VIDEO_CODEC="-c:v h264_vaapi -b:v $VIDEO_BITRATE -maxrate $VIDEO_BITRATE -bufsize 28M -r $VIDEO_FPS -g $(($VIDEO_FPS * 2))"
    else
        FINAL_FILTERS="${FILTER_CHAIN};[${LAST_V}]format=yuv420p[vfinal]"
        HW_INIT=""
        VIDEO_CODEC="-c:v libx264 -preset $SOFTWARE_PRESET -crf $SOFTWARE_CRF -b:v $VIDEO_BITRATE -maxrate $VIDEO_BITRATE -bufsize 28M -r $VIDEO_FPS -g $(($VIDEO_FPS * 2))"
    fi

    while true; do
        ffmpeg -hide_banner -loglevel warning $HW_INIT \
        $INPUTS \
        -filter_complex "$FINAL_FILTERS" \
        -map "[vfinal]" -map 0:a? \
        $VIDEO_CODEC \
        -c:a copy \
        -progress "$FFMPEG_PROGRESS_FILE" \
        -f rtsp -rtsp_transport tcp "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live"
        
        log "FFmpeg exited, restarting in 5 seconds..."
        sleep 5
    done
fi