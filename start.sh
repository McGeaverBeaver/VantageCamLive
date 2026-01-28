#!/bin/bash

# ==============================================================================
#  USER PERMISSIONS
# ==============================================================================
PUID="${PUID:-0}"
PGID="${PGID:-0}"

if [ "$PUID" != "0" ] && [ "$(id -u)" = "0" ]; then
    echo "[init] Setting up permissions for PUID=$PUID PGID=$PGID"
    EXISTING_GROUP=$(getent group "$PGID" 2>/dev/null | cut -d: -f1)
    if [ -n "$EXISTING_GROUP" ]; then GROUP_NAME="$EXISTING_GROUP"; else addgroup -g "$PGID" abc 2>/dev/null || true; GROUP_NAME="abc"; fi
    EXISTING_USER=$(getent passwd "$PUID" 2>/dev/null | cut -d: -f1)
    if [ -n "$EXISTING_USER" ]; then USER_NAME="$EXISTING_USER"; else adduser -D -u "$PUID" -G "$GROUP_NAME" -h /config -s /bin/bash abc 2>/dev/null || true; USER_NAME="abc"; fi
    chown -R "$PUID:$PGID" /config 2>/dev/null || true
    echo "[init] Running as UID:$PUID GID:$PGID"
    exec su-exec "$PUID:$PGID" "$0" "$@"
fi

# ==============================================================================
#  CONFIGURATION
# ==============================================================================
RTSP_SOURCE="${RTSP_SOURCE:-rtsp://192.168.1.100:8554/stream}"
WORKDIR="/config"
ADMIN_USER="${ADMIN_USER:-cam_admin}"
ADMIN_PASS="${ADMIN_PASS:-your_secure_password}"

if [[ "$RTSP_SOURCE" =~ rtsp://([^:]+):([^@]+)@([^:/]+):([0-9]+)(.*) ]]; then RTSP_HOST="${BASH_REMATCH[3]}"; RTSP_PORT="${BASH_REMATCH[4]}";
elif [[ "$RTSP_SOURCE" =~ rtsp://([^:]+):([^@]+)@([^/]+)(.*) ]]; then RTSP_HOST="${BASH_REMATCH[3]}"; RTSP_PORT="554";
elif [[ "$RTSP_SOURCE" =~ rtsp://([^:/]+):([0-9]+)(.*) ]]; then RTSP_HOST="${BASH_REMATCH[1]}"; RTSP_PORT="${BASH_REMATCH[2]}";
elif [[ "$RTSP_SOURCE" =~ rtsp://([^/]+)(.*) ]]; then RTSP_HOST="${BASH_REMATCH[1]}"; RTSP_PORT="554";
else RTSP_HOST="localhost"; RTSP_PORT="554"; fi

HARDWARE_ACCEL="${HARDWARE_ACCEL:-true}"
VAAPI_DEVICE="${VAAPI_DEVICE:-/dev/dri/renderD128}"
ENABLE_LOCAL_STREAM="${ENABLE_LOCAL_STREAM:-false}"
YOUTUBE_URL="${YOUTUBE_URL:-rtmp://a.rtmp.youtube.com/live2}"
YOUTUBE_KEY="${YOUTUBE_KEY:-}"
YOUTUBE_BITRATE="${YOUTUBE_BITRATE:-4500k}"
YOUTUBE_WIDTH="${YOUTUBE_WIDTH:-2560}"
YOUTUBE_HEIGHT="${YOUTUBE_HEIGHT:-1440}"
SCALING_MODE="${SCALING_MODE:-fill}"
VIDEO_BITRATE="${VIDEO_BITRATE:-14M}"
VIDEO_FPS="${VIDEO_FPS:-30}"
WEATHER_ENABLED="${WEATHER_ENABLED:-true}"
ALERTS_UPDATE_INTERVAL="${ALERTS_UPDATE_INTERVAL:-900}"
SOFTWARE_PRESET="${SOFTWARE_PRESET:-faster}"
SOFTWARE_CRF="${SOFTWARE_CRF:-23}"
SCALE_ADS_TL="${SCALE_TL:-500}"
AD_ROTATE_TIMER_TL="${OVERLAYAD_ROTATE_TIMER:-30}"
SCALE_ADS_TR="${SCALE_TR:-400}"
TR_SHOW_SECONDS="${TR_SHOW_SECONDS:-20}"
TR_HIDE_SECONDS="${TR_HIDE_SECONDS:-300}"
DAY_START_HOUR="${DAY_START_HOUR:-6}"
DAY_END_HOUR="${DAY_END_HOUR:-20}"
ADS_BASE="/config/ads"
FLASH_ON_DURATION="${FLASH_ON_DURATION:-0.7}"
FLASH_OFF_DURATION="${FLASH_OFF_DURATION:-0.3}"
WATCHDOG_ENABLED="${WATCHDOG_ENABLED:-false}"

if [ -n "$YOUTUBE_KEY" ] && [ "$ENABLE_LOCAL_STREAM" != "true" ]; then DIRECT_YOUTUBE_MODE="true"; else DIRECT_YOUTUBE_MODE="false"; fi

WEATHER_COMBINED="$WORKDIR/weather_combined.png"
WEATHER_COMBINED_FLASH="$WORKDIR/weather_combined_flash.png"
WEATHER_META="$WORKDIR/weather_combined_meta.txt"
WEATHER_LIST="$WORKDIR/weather_list.txt"
WEATHER_TEMP="$WORKDIR/weather_temp.png"
AD_FINAL_TL="$WORKDIR/current_ad_tl.png"
AD_TEMP_TL="$WORKDIR/temp_ad_tl.png"
AD_PLAYLIST_TL="$WORKDIR/ad_playlist_tl.txt"
AD_FINAL_TR="$WORKDIR/current_ad_tr.png"
AD_TEMP_TR="$WORKDIR/temp_ad_tr.png"
AD_PLAYLIST_TR="$WORKDIR/ad_playlist_tr.txt"
FALLBACK_ENABLED="${FALLBACK_ENABLED:-true}"
FALLBACK_IMAGE="$WORKDIR/fallback.png"
STREAM_MODE_FILE="$WORKDIR/stream_mode"
MUSIC_DIR="$WORKDIR/music"
MUSIC_PLAYLIST="$WORKDIR/music_playlist.txt"

# --- HEARTBEAT MONITOR CONFIG ---
FFMPEG_PROGRESS_LOG="true"
FFMPEG_PROGRESS_FILE="$WORKDIR/ffmpeg_progress.txt"
FFMPEG_ERROR_LOG="$WORKDIR/ffmpeg_error.log"
FFMPEG_PROGRESS_ARG="-progress $FFMPEG_PROGRESS_FILE"
rm -f "$FFMPEG_PROGRESS_FILE" "$FFMPEG_ERROR_LOG"
touch "$FFMPEG_PROGRESS_FILE" "$FFMPEG_ERROR_LOG"

# ==============================================================================
#  HEALTH CHECK FUNCTIONS
# ==============================================================================
check_rtsp_basic() {
    if timeout 2 bash -c "echo >/dev/tcp/$RTSP_HOST/$RTSP_PORT" 2>/dev/null; then return 0; else return 1; fi
}
check_rtsp_robust() {
    if ! check_rtsp_basic; then return 1; fi
    if timeout 10 ffprobe -v error -rtsp_transport tcp -buffer_size 2097152 -i "$1" -t 1 -f null - 2>/dev/null; then return 0; else return 1; fi
}

# ==============================================================================
#  HELPER FUNCTIONS
# ==============================================================================
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }
cleanup() { log "Shutting down..."; pkill -P $$ 2>/dev/null; pkill -f "watchdog.py" 2>/dev/null; exit 0; }
trap cleanup SIGTERM SIGINT

check_vaapi() {
    if [ "$HARDWARE_ACCEL" = "true" ]; then
        if [ ! -e "$VAAPI_DEVICE" ]; then log "WARNING: VAAPI device not found. Using software."; HARDWARE_ACCEL="false"; return 1; fi
        if ! ffmpeg -hide_banner -init_hw_device vaapi=va:$VAAPI_DEVICE -f lavfi -i nullsrc=s=64x64:d=1 -vf 'format=nv12,hwupload' -c:v h264_vaapi -f null - 2>/dev/null; then
            log "WARNING: VAAPI test failed. Using software."; HARDWARE_ACCEL="false"; return 1;
        fi
        log "VAAPI hardware acceleration enabled on $VAAPI_DEVICE"; return 0;
    else log "Software encoding mode"; return 1; fi
}

update_weather_playlist() {
    if [ "$1" = "1" ] && [ -f "$WEATHER_COMBINED_FLASH" ]; then
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
EOF
    else
        echo -e "file '$WEATHER_COMBINED'\nduration 10\nfile '$WEATHER_COMBINED'" > "$WEATHER_LIST"
    fi
}

# Sanitize music filenames - remove problematic characters that break FFmpeg concat
sanitize_music_files() {
    mkdir -p "$MUSIC_DIR"
    local renamed_count=0
    
    # First, fix any files that got broken with trailing underscore
    shopt -s nullglob nocaseglob
    for f in "$MUSIC_DIR"/*.mp3_; do
        local newname="${f%_}"
        if [ ! -f "$newname" ]; then
            mv "$f" "$newname" 2>/dev/null && log "[Music] Fixed: removed trailing underscore from '$(basename "$f")'"
        fi
    done
    
    for f in "$MUSIC_DIR"/*.mp3; do
        local dir=$(dirname "$f")
        local base=$(basename "$f")
        
        # Only rename if filename contains apostrophe or ampersand (the problem chars)
        if echo "$base" | grep -qE "['\"\`&]"; then
            # Replace only the problematic characters
            local safe=$(printf '%s' "$base" | tr "'\"\`&" "_")
            safe=$(echo "$safe" | tr -s '_')
            
            if [ "$base" != "$safe" ]; then
                local newpath="$dir/$safe"
                # Handle collision
                local counter=1
                while [ -f "$newpath" ] && [ "$f" != "$newpath" ]; do
                    safe="${safe%.mp3}_${counter}.mp3"
                    newpath="$dir/$safe"
                    counter=$((counter + 1))
                done
                
                if [ "$f" != "$newpath" ]; then
                    mv "$f" "$newpath" 2>/dev/null && {
                        log "[Music] Renamed: '$base' -> '$safe'"
                        renamed_count=$((renamed_count + 1))
                    }
                fi
            fi
        fi
    done
    shopt -u nullglob nocaseglob
    
    if [ $renamed_count -gt 0 ]; then
        log "[Music] Sanitized $renamed_count file(s) with problematic characters"
    fi
}

generate_music_playlist() {
    mkdir -p "$MUSIC_DIR"
    # Sanitize filenames first
    sanitize_music_files
    
    local music_files=()
    shopt -s nullglob nocaseglob
    for f in "$MUSIC_DIR"/*.mp3; do
        music_files+=("$f")
    done
    shopt -u nullglob nocaseglob

    if [ ${#music_files[@]} -eq 0 ]; then
        log "[Music] No MP3 files found in $MUSIC_DIR"
        return 1
    fi

    log "[Music] Found ${#music_files[@]} MP3 file(s) in playlist"
    > "$MUSIC_PLAYLIST"
    for f in "${music_files[@]}"; do
        echo "file '$f'" >> "$MUSIC_PLAYLIST"
    done
    
    # Log playlist content for debugging (just first 5 entries)
    log "[Music] Playlist entries (first 5):"
    head -n 5 "$MUSIC_PLAYLIST" | while read -r line; do
        log "[Music]   $line"
    done
    
    return 0
}

# ==============================================================================
#  INITIALIZATION
# ==============================================================================
log "--- 1. Checking Hardware Acceleration ---"
check_vaapi

log "--- 2. Checking Weather Icons ---"
cat <<'EOF' > /tmp/download_icons.py
import os, requests
DESTINATION_FOLDER = "/config/weather_icons"
GITHUB_API_URL = "https://api.github.com/repos/basmilius/weather-icons/contents/production/fill/png/512"
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
    except: pass
if __name__ == "__main__": run()
EOF
python3 /tmp/download_icons.py; rm /tmp/download_icons.py

mkdir -p "$ADS_BASE/topleft/DAY" "$ADS_BASE/topleft/NIGHT" "$ADS_BASE/topright/DAY" "$ADS_BASE/topright/NIGHT"

log "--- Configuring Stream Output ---"
if [ "$DIRECT_YOUTUBE_MODE" = "false" ]; then
    log "MediaMTX mode enabled"
    if [ "$ENABLE_LOCAL_STREAM" = "true" ]; then RTSP_ADDRESS=":8554"; else RTSP_ADDRESS="127.0.0.1:8554"; fi
    cat <<EOF > /usr/local/bin/mediamtx.yml
rtspAddress: $RTSP_ADDRESS
readTimeout: 60s
writeTimeout: 60s
rtmpDisable: yes
hlsDisable: yes
webrtcDisable: yes
srtDisable: yes
api: yes
apiAddress: 127.0.0.1:9997
authMethod: internal
authInternalUsers: [{ user: $ADMIN_USER, pass: $ADMIN_PASS, permissions: [{ action: api }, { action: publish }, { action: read }] }]
paths: { all: }
EOF
    /usr/local/bin/mediamtx /usr/local/bin/mediamtx.yml &
    sleep 2
else
    log "Direct-to-YouTube mode enabled"
fi

if [ -n "$YOUTUBE_KEY" ]; then python3 /audio_api.py & sleep 1; fi

if [ ! -f "$WEATHER_COMBINED" ]; then python3 /weather.py blank "$WEATHER_COMBINED" "900" "500"; fi
update_weather_playlist "0"
python3 /weather.py blank "$AD_FINAL_TL" "$SCALE_ADS_TL" "$SCALE_ADS_TL"
echo -e "file '$AD_FINAL_TL'\nduration 10\nfile '$AD_FINAL_TL'" > "$AD_PLAYLIST_TL"
python3 /weather.py blank "$AD_FINAL_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"
echo -e "file '$AD_FINAL_TR'\nduration 10\nfile '$AD_FINAL_TR'" > "$AD_PLAYLIST_TR"

if [ "$FALLBACK_ENABLED" = "true" ]; then
    log "--- Generating Fallback Screen ---"
    python3 /weather.py fallback "$FALLBACK_IMAGE" "$YOUTUBE_WIDTH" "$YOUTUBE_HEIGHT" "We'll Be Right Back"
    echo "normal" > "$STREAM_MODE_FILE"
fi

# ==============================================================================
#  BACKGROUND MANAGERS
# ==============================================================================
get_mode() { local hr=$(date +%-H); if [ "$hr" -ge "$DAY_START_HOUR" ] && [ "$hr" -lt "$DAY_END_HOUR" ]; then echo "DAY"; else echo "NIGHT"; fi; }

# TL Manager
(
    shopt -s nocaseglob nullglob
    while true; do
        MODE=$(get_mode); TARGET_DIR="$ADS_BASE/topleft/$MODE"
        FILES=("$TARGET_DIR"/*.png "$TARGET_DIR"/*.jpg "$TARGET_DIR"/*.jpeg)
        if [ ${#FILES[@]} -eq 0 ]; then python3 /weather.py blank "$AD_FINAL_TL" "$SCALE_ADS_TL" "$SCALE_ADS_TL"; sleep 60; else
            for f in "${FILES[@]}"; do
                if [ "$(get_mode)" != "$MODE" ]; then break; fi
                CURRENT_HASH=$(md5sum "$f" 2>/dev/null | cut -d' ' -f1)
                if [ "$CURRENT_HASH" != "$LAST_AD_HASH_TL" ] || [ ! -f "$AD_FINAL_TL" ]; then
                    if python3 /weather.py ad "$AD_TEMP_TL" "$f" "$SCALE_ADS_TL" "$SCALE_ADS_TL"; then mv -f "$AD_TEMP_TL" "$AD_FINAL_TL"; LAST_AD_HASH_TL="$CURRENT_HASH"; fi
                fi
                sleep "$AD_ROTATE_TIMER_TL"
            done
        fi
    done
) &

# TR Manager
(
    shopt -s nocaseglob nullglob; TR_INDEX=0
    while true; do
        MODE=$(get_mode); TARGET_DIR="$ADS_BASE/topright/$MODE"
        FILES=("$TARGET_DIR"/*.png "$TARGET_DIR"/*.jpg "$TARGET_DIR"/*.jpeg)
        if [ ${#FILES[@]} -eq 0 ]; then python3 /weather.py blank "$AD_FINAL_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"; sleep 60; else
            if [ $TR_INDEX -ge ${#FILES[@]} ]; then TR_INDEX=0; fi
            CURRENT_HASH=$(md5sum "${FILES[$TR_INDEX]}" 2>/dev/null | cut -d' ' -f1)
            if [ "$CURRENT_HASH" != "$LAST_AD_HASH_TR" ] || [ ! -f "$AD_FINAL_TR" ]; then
                if python3 /weather.py ad "$AD_TEMP_TR" "${FILES[$TR_INDEX]}" "$SCALE_ADS_TR" "$SCALE_ADS_TR"; then mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"; LAST_AD_HASH_TR="$CURRENT_HASH"; fi
            fi
            sleep "$TR_SHOW_SECONDS"
            python3 /weather.py blank "$AD_TEMP_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"; mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"; LAST_AD_HASH_TR=""; sleep "$TR_HIDE_SECONDS"; TR_INDEX=$((TR_INDEX + 1))
        fi
    done
) &

# Weather Manager
if [ "$WEATHER_ENABLED" = "true" ]; then
    (
        sleep 5
        while true; do
            python3 /weather.py combined "$WEATHER_TEMP"
            if [ -f "$WEATHER_TEMP" ]; then
                mv -f "$WEATHER_TEMP" "$WEATHER_COMBINED"
                FLASH_TEMP="${WEATHER_TEMP%.png}_flash.png"
                if [ -f "$FLASH_TEMP" ]; then mv -f "$FLASH_TEMP" "$WEATHER_COMBINED_FLASH"; else rm -f "$WEATHER_COMBINED_FLASH"; fi
                META_TEMP="${WEATHER_TEMP%.png}_meta.txt"
                if [ -f "$META_TEMP" ]; then update_weather_playlist "$(grep "needs_flash=" "$META_TEMP" | cut -d'=' -f2)"; mv -f "$META_TEMP" "$WEATHER_META"; fi
            fi
            if [ "$(grep "needs_flash=" "$WEATHER_META" 2>/dev/null | cut -d'=' -f2)" = "1" ]; then sleep 60; else sleep "$ALERTS_UPDATE_INTERVAL"; fi
        done
    ) &
fi

if [ "$DIRECT_YOUTUBE_MODE" = "true" ]; then echo "muted" > "/config/audio_mode"; fi
if [ "$WATCHDOG_ENABLED" = "true" ] && [ -n "$YOUTUBE_KEY" ]; then log "--- Starting Self-Healing Watchdog ---"; python3 /watchdog.py & fi

# ==============================================================================
#  MAIN STREAM ENCODING
# ==============================================================================
log "--- Starting Main Stream (Hardware: $HARDWARE_ACCEL, Direct YouTube: $DIRECT_YOUTUBE_MODE) ---"

if [ "$SCALING_MODE" = "fill" ]; then
    CAMERA_FILTER="[0:v]scale=2560:1440:force_original_aspect_ratio=increase:flags=bicubic,crop=2560:1440,format=yuv420p[base]"
else
    CAMERA_FILTER="[0:v]scale=2560:1440:force_original_aspect_ratio=decrease:flags=bicubic,pad=2560:1440:(ow-iw)/2:(oh-ih)/2,format=yuv420p[base]"
fi

# ==============================================================================
#  INPUTS CONFIGURATION (FIX: Split RTSP and Overlays)
# ==============================================================================
# We split the inputs so we can re-use the overlays on the BRB screen.
# RTSP Input Options - Optimized for reliability over low latency
# - rtsp_transport tcp: Retransmits lost packets (unlike UDP)
# - buffer_size: 4MB receive buffer for network hiccups
# - max_delay: Allow up to 500ms delay to reassemble packets
# - fflags: Generate timestamps, discard corrupt frames cleanly
# - err_detect: Ignore decode errors instead of failing
# - thread_queue_size: Large queue for bursty network conditions
RTSP_INPUT_OPTS="-thread_queue_size 2048 -rtsp_transport tcp -buffer_size 4194304 -max_delay 500000 -fflags +genpts+discardcorrupt -err_detect ignore_err -timeout 8000000 -i $RTSP_SOURCE"
OVERLAY_INPUTS=""

FILTER_CHAIN="$CAMERA_FILTER"
LAST_V="base"
INPUT_COUNT=1

add_overlay() {
    local path=$1; local pos=$2; local width=$3; local height=$4
    local coords=""
    case $pos in tl) coords="20:20" ;; tr) coords="main_w-overlay_w-20:20" ;; br) coords="main_w-overlay_w-20:main_h-overlay_h-20" ;; bl) coords="20:main_h-overlay_h-20" ;; esac

    # Append to OVERLAY_INPUTS instead of the main string, so we can reuse it
    OVERLAY_INPUTS="$OVERLAY_INPUTS -f concat -safe 0 -stream_loop -1 -i $path"

    if [ -n "$height" ]; then scale_cmd="scale=${width}:${height}"; else scale_cmd="scale=${width}:${width}"; fi
    FILTER_CHAIN="${FILTER_CHAIN};[${INPUT_COUNT}:v]${scale_cmd},format=rgba[ovr${INPUT_COUNT}];[${LAST_V}][ovr${INPUT_COUNT}]overlay=${coords}:eof_action=pass:shortest=0[v${INPUT_COUNT}]"
    LAST_V="v$INPUT_COUNT"; INPUT_COUNT=$((INPUT_COUNT+1))
}

add_overlay "$AD_PLAYLIST_TL" "tl" "$SCALE_ADS_TL" ""
add_overlay "$AD_PLAYLIST_TR" "tr" "$SCALE_ADS_TR" ""
if [ "$WEATHER_ENABLED" = "true" ]; then add_overlay "$WEATHER_LIST" "br" "900" "500"; fi

if [ "$DIRECT_YOUTUBE_MODE" = "true" ]; then
    log "--- Direct YouTube Mode: Single FFmpeg pipeline ---"

    run_camera_ffmpeg() {
        local audio_mode="$1"
        if [ "$HARDWARE_ACCEL" = "true" ]; then
            local final_filters="${FILTER_CHAIN};[${LAST_V}]scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=nv12[soft_final];[soft_final]hwupload[vfinal]"
            local hw_init="-init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va"
            local video_codec="-c:v h264_vaapi -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
        else
            local final_filters="${FILTER_CHAIN};[${LAST_V}]scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=yuv420p[vfinal]"
            local hw_init=""
            local video_codec="-c:v libx264 -preset $SOFTWARE_PRESET -crf $SOFTWARE_CRF -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
        fi

        # Combine RTSP Input + Overlay Inputs
        if [ "$audio_mode" = "unmuted" ]; then
            # Read volume (0-100) and convert to decimal (0.0-1.0)
            local vol_pct=$(cat /config/music_volume 2>/dev/null || echo 50)
            local vol_dec=$(awk "BEGIN {printf \"%.2f\", $vol_pct/100}")
            log "[Audio] Volume: ${vol_pct}% (${vol_dec}x)"
            ffmpeg -hide_banner -loglevel warning $hw_init $RTSP_INPUT_OPTS $OVERLAY_INPUTS -filter_complex "$final_filters" -map "[vfinal]" -map 0:a? $video_codec -c:a aac -b:a 128k -ac 2 -af "volume=${vol_dec}" $FFMPEG_PROGRESS_ARG -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" 1>&2 &
        elif [ "$audio_mode" = "music" ]; then
            # Read volume (0-100) and convert to decimal (0.0-1.0)
            local vol_pct=$(cat /config/music_volume 2>/dev/null || echo 50)
            local vol_dec=$(awk "BEGIN {printf \"%.2f\", $vol_pct/100}")
            log "[Music] Volume: ${vol_pct}% (${vol_dec}x)"
            # Music mode: stream from playlist, loop infinitely with -stream_loop -1
            # Redirect stderr to error log for concat error monitoring
            ffmpeg -hide_banner -loglevel warning $hw_init $RTSP_INPUT_OPTS $OVERLAY_INPUTS -stream_loop -1 -thread_queue_size 4096 -re -f concat -safe 0 -i "$MUSIC_PLAYLIST" -filter_complex "$final_filters" -map "[vfinal]" -map $((INPUT_COUNT)):a $video_codec -c:a aac -b:a 128k -ac 2 -af "volume=${vol_dec},aresample=async=1:first_pts=0" $FFMPEG_PROGRESS_ARG -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" 2>> "$FFMPEG_ERROR_LOG" &
        else
            ffmpeg -hide_banner -loglevel warning $hw_init $RTSP_INPUT_OPTS $OVERLAY_INPUTS -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -filter_complex "$final_filters" -map "[vfinal]" -map $((INPUT_COUNT)):a $video_codec -c:a aac -b:a 128k $FFMPEG_PROGRESS_ARG -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" 1>&2 &
        fi
        echo $!
    }

    run_fallback_ffmpeg() {
        # BRB Input acts as Input 0
        local BRB_INPUT_OPTS="-loop 1 -re -i $FALLBACK_IMAGE"

        if [ "$HARDWARE_ACCEL" = "true" ]; then
            local final_filters="${FILTER_CHAIN};[${LAST_V}]scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=nv12[soft_final];[soft_final]hwupload[vfinal]"
            local hw_init="-init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va"
            local video_codec="-c:v h264_vaapi -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
        else
            local final_filters="${FILTER_CHAIN};[${LAST_V}]scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=yuv420p[vfinal]"
            local hw_init=""
            local video_codec="-c:v libx264 -preset $SOFTWARE_PRESET -tune stillimage -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
        fi

        # Combine BRB Input + Overlay Inputs + Silent Audio (at the end)
        ffmpeg -hide_banner -loglevel warning $hw_init \
            $BRB_INPUT_OPTS $OVERLAY_INPUTS \
            -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
            -filter_complex "$final_filters" \
            -map "[vfinal]" -map $((INPUT_COUNT)):a \
            $video_codec -c:a aac -b:a 128k \
            -f flv "${YOUTUBE_URL}/${YOUTUBE_KEY}" 1>&2 &
        echo $!
    }

    CURRENT_MODE="normal"
    FFMPEG_PID=""
    ERROR_MONITOR_PID=""
    LAST_SIZE=0
    FROZEN_COUNT=0

    while true; do
        if [ -z "$FFMPEG_PID" ] || ! kill -0 $FFMPEG_PID 2>/dev/null; then
            if [ "$CURRENT_MODE" = "normal" ]; then
                RETRY_COUNT=0
                while [ $RETRY_COUNT -lt 3 ]; do
                    AUDIO_MODE=$(cat "/config/audio_mode" 2>/dev/null || echo "muted")
                    # Generate music playlist if music mode is enabled
                    if [ "$AUDIO_MODE" = "music" ]; then
                        if ! generate_music_playlist; then
                            log "[Music] No music files available, falling back to muted"
                            AUDIO_MODE="muted"
                        fi
                    fi
                    rm -f "$FFMPEG_PROGRESS_FILE" "$FFMPEG_ERROR_LOG"; touch "$FFMPEG_PROGRESS_FILE" "$FFMPEG_ERROR_LOG"; LAST_SIZE=0; FROZEN_COUNT=0
                    FFMPEG_PID=$(run_camera_ffmpeg "$AUDIO_MODE")
                    
                    # Start concat error monitor if in music mode
                    if [ "$AUDIO_MODE" = "music" ]; then
                        (
                            tail -f "$FFMPEG_ERROR_LOG" 2>/dev/null | while IFS= read -r line; do
                                if echo "$line" | grep -qE "Error during demuxing|Error retrieving a packet from demuxer"; then
                                    log "[ERROR] Concat demuxer error detected. Killing FFmpeg PID $FFMPEG_PID..."
                                    kill -9 $FFMPEG_PID 2>/dev/null
                                    break
                                fi
                            done
                        ) &
                        ERROR_MONITOR_PID=$!
                    fi
                    
                    sleep 2
                    if kill -0 $FFMPEG_PID 2>/dev/null; then break; fi
                    log "Startup attempt $((RETRY_COUNT+1)) failed. Retrying in 2s..."
                    RETRY_COUNT=$((RETRY_COUNT+1))
                done
                if ! kill -0 $FFMPEG_PID 2>/dev/null; then
                     log "Startup failed. Forcing Fallback..."
                     CURRENT_MODE="fallback"
                     FFMPEG_PID=$(run_fallback_ffmpeg)
                fi
                echo $FFMPEG_PID > "/config/youtube_restreamer.pid"
                sleep 0.5  # Let FFmpeg init complete before logging
                if [ "$AUDIO_MODE" = "music" ]; then
                    log "FFmpeg started (PID: $FFMPEG_PID) - Music mode"
                elif [ "$AUDIO_MODE" = "unmuted" ]; then
                    log "FFmpeg started (PID: $FFMPEG_PID) - Audio unmuted"
                else
                    log "FFmpeg started (PID: $FFMPEG_PID) - Muted"
                fi
            else
                log "[Fallback] Starting 'We'll Be Right Back' stream (With Overlays)..."
                FFMPEG_PID=$(run_fallback_ffmpeg)
                echo $FFMPEG_PID > "/config/youtube_restreamer.pid"
                sleep 0.5
                log "[Fallback] FFmpeg started (PID: $FFMPEG_PID)"
            fi
        fi

        LOOP_COUNT=0
        while kill -0 $FFMPEG_PID 2>/dev/null; do
            LOOP_COUNT=$((LOOP_COUNT + 1))

            # 1. ZOMBIE CHECK (Size-Based) - Only in Normal Mode
            if [ "$CURRENT_MODE" = "normal" ]; then
                CURRENT_SIZE=$(wc -c < "$FFMPEG_PROGRESS_FILE" 2>/dev/null || echo 0)
                if [ "$CURRENT_SIZE" -le "$LAST_SIZE" ]; then
                    FROZEN_COUNT=$((FROZEN_COUNT + 1))
                    if [ $FROZEN_COUNT -ge 12 ]; then
                        log "[ERROR] FFmpeg FROZEN (Size static at $CURRENT_SIZE for 12s). Killing..."
                        kill -9 $FFMPEG_PID 2>/dev/null
                        break
                    fi
                else
                    FROZEN_COUNT=0
                    LAST_SIZE=$CURRENT_SIZE
                fi
            fi

            # 2. Audio Check
            if [ "$CURRENT_MODE" = "normal" ]; then
                NEW_AUDIO=$(cat "/config/audio_mode" 2>/dev/null || echo "muted")
                if [ "$NEW_AUDIO" != "$AUDIO_MODE" ]; then log "Audio Change"; kill $FFMPEG_PID 2>/dev/null; sleep 2; FFMPEG_PID=""; break; fi
            fi

            # 3. Connection Health Check (Every 3s)
            if [ $((LOOP_COUNT % 3)) -eq 0 ]; then
                if [ "$CURRENT_MODE" = "normal" ] && [ "$FALLBACK_ENABLED" = "true" ]; then
                   if ! check_rtsp_basic; then
                       log "[Fallback] RTSP Ping Failed - Killing PID $FFMPEG_PID..."
                       kill -9 $FFMPEG_PID 2>/dev/null
                       break
                   fi
                fi
                if [ "$CURRENT_MODE" = "fallback" ]; then
                   if check_rtsp_basic; then
                       log "[Fallback] RTSP Recovered! Killing BRB Stream (PID $FFMPEG_PID) to switch..."
                       kill -9 $FFMPEG_PID 2>/dev/null
                       break
                   fi
                fi
            fi

            # Heartbeat Logging every 10s
            if [ $((LOOP_COUNT % 10)) -eq 0 ] && [ "$CURRENT_MODE" = "normal" ]; then
                log "[Heartbeat] PID:$FFMPEG_PID Size:$CURRENT_SIZE Mode:$AUDIO_MODE"
            fi

            sleep 1
        done

        # FFmpeg Died/Killed Logic
        if [ -n "$FFMPEG_PID" ] && ! kill -0 $FFMPEG_PID 2>/dev/null; then
            # Kill error monitor if running
            if [ -n "$ERROR_MONITOR_PID" ]; then
                kill $ERROR_MONITOR_PID 2>/dev/null
                ERROR_MONITOR_PID=""
            fi
            wait $FFMPEG_PID 2>/dev/null; EXIT_CODE=$?
            if [ "$CURRENT_MODE" = "normal" ] && [ "$FALLBACK_ENABLED" = "true" ]; then
                log "[Fallback] Stream died (Code $EXIT_CODE). Switching..."
                CURRENT_MODE="fallback"
                echo "fallback" > "$STREAM_MODE_FILE"
            elif [ "$CURRENT_MODE" = "fallback" ]; then
                 if check_rtsp_basic; then
                     log "[Fallback] Ready. Switching to Normal..."
                     CURRENT_MODE="normal"
                     echo "normal" > "$STREAM_MODE_FILE"
                 else sleep 1; fi
            else sleep 2; fi
            FFMPEG_PID=""
        fi
    done

# ==============================================================================
#  MEDIAMTX MODE
# ==============================================================================
else
    # (Note: Overlays + RTSP split logic could be applied here too if needed, but keeping it simple for now)
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
        # Combine RTSP + Overlays
        ffmpeg -hide_banner -loglevel warning $HW_INIT $RTSP_INPUT_OPTS $OVERLAY_INPUTS -filter_complex "$FINAL_FILTERS" -map "[vfinal]" -map 0:a? $VIDEO_CODEC -c:a copy $FFMPEG_PROGRESS_ARG -f rtsp -rtsp_transport tcp "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live"
        log "FFmpeg exited, restarting in 5 seconds..."
        sleep 5
    done
fi
