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

# Parse host/port for TCP health checks. Splitting on the LAST '@' keeps
# passwords containing '@' or ':' from shifting the host (the old regexes did).
_rtsp_hostport="${RTSP_SOURCE#*://}"
_rtsp_hostport="${_rtsp_hostport##*@}"
_rtsp_hostport="${_rtsp_hostport%%/*}"
if [[ "$_rtsp_hostport" == \[*\]* ]]; then
    RTSP_HOST="${_rtsp_hostport%%]*}"; RTSP_HOST="${RTSP_HOST#[}"
    _rtsp_after="${_rtsp_hostport##*]}"
    if [[ "$_rtsp_after" == :* ]]; then RTSP_PORT="${_rtsp_after#:}"; else RTSP_PORT="554"; fi
elif [[ "$_rtsp_hostport" == *:* ]]; then
    RTSP_HOST="${_rtsp_hostport%%:*}"; RTSP_PORT="${_rtsp_hostport##*:}"
else
    RTSP_HOST="$_rtsp_hostport"; RTSP_PORT="554"
fi
case "$RTSP_PORT" in (*[!0-9]*|"") RTSP_PORT="554";; esac
[ -n "$RTSP_HOST" ] || RTSP_HOST="localhost"
if [[ "$RTSP_SOURCE" == *[[:space:]]* ]]; then
    echo "[init] WARNING: RTSP_SOURCE contains whitespace - FFmpeg will misparse it. Percent-encode special characters."
fi

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

# Day/night source: "sun" follows real sunrise/sunset for WEATHER_LAT/LON,
# "clock" keeps the fixed DAY_START_HOUR/DAY_END_HOUR schedule.
DAY_NIGHT_MODE="${DAY_NIGHT_MODE:-sun}"
DAY_NIGHT_FILE="$WORKDIR/day_night"

# Extra RTMP destinations, comma separated, each a complete URL including its
# own stream key (e.g. rtmp://live-api-s.facebook.com:80/rtmp/FB-KEY).
SIMULCAST_URLS="${SIMULCAST_URLS:-}"

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
# The -progress file drives frozen-stream detection, the Docker healthcheck and
# the Admin WebUI stats; it is always on and its growth is capped by periodic
# truncation in the monitor loops.
FFMPEG_PROGRESS_FILE="$WORKDIR/ffmpeg_progress.txt"
FFMPEG_PROGRESS_ARG="-progress $FFMPEG_PROGRESS_FILE"
rm -f "$FFMPEG_PROGRESS_FILE"
touch "$FFMPEG_PROGRESS_FILE"

# --- FFMPEG STDERR LOG (viewable in the Admin WebUI) ---
FFMPEG_LOG="$WORKDIR/ffmpeg.log"
# Keep the log bounded: truncate when it grows past ~5MB
trim_ffmpeg_log() {
    if [ -f "$FFMPEG_LOG" ] && [ "$(wc -c < "$FFMPEG_LOG" 2>/dev/null || echo 0)" -gt 5242880 ]; then
        tail -c 1048576 "$FFMPEG_LOG" > "$FFMPEG_LOG.tmp" 2>/dev/null && mv -f "$FFMPEG_LOG.tmp" "$FFMPEG_LOG"
    fi
}

# --- WATCHDOG RESTART HOLD ---
# watchdog.py writes an epoch timestamp here before killing FFmpeg; we honor it
# so its exponential backoff actually delays the respawn (previously the loop
# restarted FFmpeg instantly, making the backoff a no-op).
RESTART_HOLD_FILE="$WORKDIR/restart_hold"

# --- BROADCAST PAUSE ---
# Created by the Admin WebUI "Stop Broadcast" button. While it exists the
# supervisor keeps FFmpeg stopped instead of respawning it, so Stop actually
# means stopped rather than "restarts in two seconds". Survives container
# restarts on purpose: a deliberately stopped stream should stay stopped.
STREAM_PAUSED_FILE="$WORKDIR/stream_paused"
is_paused() { [ -f "$STREAM_PAUSED_FILE" ]; }
honor_restart_hold() {
    local hold_until now wait_s
    hold_until=$(cat "$RESTART_HOLD_FILE" 2>/dev/null || echo 0)
    case "$hold_until" in (*[!0-9]*|"") hold_until=0;; esac
    now=$(date +%s)
    [ "$hold_until" -gt "$now" ] || { rm -f "$RESTART_HOLD_FILE"; return; }

    wait_s=$((hold_until - now))
    [ "$wait_s" -gt 900 ] && wait_s=900
    log "[Watchdog] Honoring restart hold: waiting ${wait_s}s before respawning FFmpeg."
    log "[Watchdog] Cancel it any time with: rm -f $RESTART_HOLD_FILE   (or 'Retry Now' in the WebUI)"
    # Sleep in short slices and re-check, so deleting the file cancels the wait
    # instead of leaving the operator staring at a 15-minute blackout.
    while [ -f "$RESTART_HOLD_FILE" ]; do
        now=$(date +%s)
        [ "$now" -ge "$hold_until" ] && break
        sleep 2
    done
    if [ ! -f "$RESTART_HOLD_FILE" ]; then log "[Watchdog] Restart hold cancelled - respawning now."; fi
    rm -f "$RESTART_HOLD_FILE"
}
rm -f "$RESTART_HOLD_FILE"
# Clear a stale PID file from a previous run: after a reboot the recorded PID
# may belong to an unrelated process that the audio API/watchdog would signal.
rm -f "$WORKDIR/youtube_restreamer.pid"

# --- EVENT TIMELINE ---
# One JSON line per significant transition, read back by the Admin WebUI.
# Written straight from bash (no Python spawn) so it is cheap enough to call
# from the supervision loop.
EVENTS_FILE="$WORKDIR/events.jsonl"
record_event() {
    local etype="$1" level="$2" msg="$3" esc
    # Escape backslashes then quotes so the line is always valid JSON
    esc=${msg//\\/\\\\}
    esc=${esc//\"/\\\"}
    # Strip every control character (tabs, CR, newlines): a raw one makes the
    # line invalid JSON and would break the whole timeline reader.
    esc=${esc//[$'\001'-$'\037']/ }
    printf '{"ts":%s,"type":"%s","level":"%s","msg":"%s"}\n' \
        "$(date +%s)" "$etype" "$level" "$esc" >> "$EVENTS_FILE" 2>/dev/null
    # Keep it bounded without rewriting on every append
    if [ "$(wc -c < "$EVENTS_FILE" 2>/dev/null || echo 0)" -gt 307200 ]; then
        tail -n 2000 "$EVENTS_FILE" > "$EVENTS_FILE.tmp" 2>/dev/null && mv -f "$EVENTS_FILE.tmp" "$EVENTS_FILE"
    fi
}

# ==============================================================================
#  HEALTH CHECK FUNCTIONS
# ==============================================================================
check_rtsp_basic() {
    if timeout 2 bash -c "echo >/dev/tcp/$RTSP_HOST/$RTSP_PORT" 2>/dev/null; then return 0; else return 1; fi
}

# --- YouTube ingest reachability -------------------------------------------
# Parse the configured ingest URL once so failures can say *which* leg broke:
# an unreachable ingest host looks nothing like a dead camera, but both used to
# surface as the same anonymous "Startup attempt failed" line.
parse_youtube_endpoint() {
    local url="${YOUTUBE_URL:-}"
    local scheme="${url%%://*}"
    local rest="${url#*://}"
    rest="${rest%%/*}"
    YT_HOST="${rest%%:*}"
    if [[ "$rest" == *:* ]]; then YT_PORT="${rest##*:}"; else
        case "$scheme" in
            rtmps) YT_PORT=443 ;;
            rtmp)  YT_PORT=1935 ;;
            *)     YT_PORT=1935 ;;
        esac
    fi
    YT_SCHEME="$scheme"
    case "$YT_PORT" in (*[!0-9]*|"") YT_PORT=1935;; esac
}
parse_youtube_endpoint

# Build the FFmpeg output. With no simulcast targets this is the plain flv
# muxer exactly as before; with targets it becomes a tee fan-out where every
# leg carries onfail=ignore, so a dead Facebook/Twitch endpoint can never take
# the YouTube broadcast down with it.
build_output_target() {
    OUTPUT_EXTRA=""
    if [ -z "$SIMULCAST_URLS" ]; then
        OUTPUT_FORMAT="flv"
        OUTPUT_TARGET="${YOUTUBE_URL}/${YOUTUBE_KEY}"
        return
    fi
    local spec="[f=flv:onfail=ignore]${YOUTUBE_URL}/${YOUTUBE_KEY}" u count=0
    IFS=',' read -ra _urls <<< "$SIMULCAST_URLS"
    for u in "${_urls[@]}"; do
        u="${u#"${u%%[![:space:]]*}"}"; u="${u%"${u##*[![:space:]]}"}"
        [ -z "$u" ] && continue
        spec="${spec}|[f=flv:onfail=ignore]${u}"
        count=$((count+1))
    done
    if [ $count -eq 0 ]; then
        OUTPUT_FORMAT="flv"; OUTPUT_TARGET="${YOUTUBE_URL}/${YOUTUBE_KEY}"; return
    fi
    OUTPUT_FORMAT="tee"
    OUTPUT_TARGET="$spec"
    OUTPUT_EXTRA="-flags +global_header"
    log "Simulcast enabled: YouTube + $count additional destination(s)"
}
build_output_target

check_youtube_ingest() {
    [ -n "$YT_HOST" ] || return 0
    timeout 5 bash -c "echo >/dev/tcp/$YT_HOST/$YT_PORT" 2>/dev/null
}

# Redact the stream key from anything FFmpeg prints. FFmpeg echoes the full
# output URL (key included) in its error messages, which otherwise lands in
# `docker logs` and /config/ffmpeg.log in plaintext.
# Pure bash on purpose: Alpine's sed is busybox (no -u), so a sed filter would
# block-buffer the log. The quoted pattern makes the match literal.
# Every secret that can appear in FFmpeg output: the YouTube key plus the key
# portion of each simulcast URL.
SECRETS=()
[ -n "$YOUTUBE_KEY" ] && SECRETS+=("$YOUTUBE_KEY")
if [ -n "$SIMULCAST_URLS" ]; then
    IFS=',' read -ra _simul_list <<< "$SIMULCAST_URLS"
    for _u in "${_simul_list[@]}"; do
        _u="${_u//[[:space:]]/}"
        [ -z "$_u" ] && continue
        _tail="${_u##*/}"                      # last path segment = the key
        [ -n "$_tail" ] && [ ${#_tail} -ge 8 ] && SECRETS+=("$_tail")
    done
fi

scrub_key() {
    if [ ${#SECRETS[@]} -eq 0 ]; then cat; return; fi
    local line secret
    while IFS= read -r line || [ -n "$line" ]; do
        for secret in "${SECRETS[@]}"; do
            line="${line//"$secret"/<STREAM_KEY>}"
        done
        printf '%s\n' "$line"
    done
}
check_rtsp_robust() {
    if ! check_rtsp_basic; then return 1; fi
    if timeout 10 ffprobe -v error -rtsp_transport tcp -buffer_size 2097152 -i "$1" -t 1 -f null - 2>/dev/null; then return 0; else return 1; fi
}

# ==============================================================================
#  HELPER FUNCTIONS
# ==============================================================================
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }
# Escape a value for use inside a double-quoted YAML scalar (mediamtx config).
# Without this, a password containing " or \ breaks (or truncates) the config.
yaml_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
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

# Record the encoder actually in use (after VAAPI auto-fallback) for the WebUI
record_encoder_mode() {
    if [ "$HARDWARE_ACCEL" = "true" ]; then echo "vaapi" > "$WORKDIR/encoder_mode"; else echo "software" > "$WORKDIR/encoder_mode"; fi
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

generate_music_playlist() {
    mkdir -p "$MUSIC_DIR"
    local music_files=()
    local seen_files=()
    shopt -s nullglob nocaseglob
    
    # Collect all MP3 files (lowercase and uppercase patterns)
    for f in "$MUSIC_DIR"/*.mp3 "$MUSIC_DIR"/*.MP3; do
        # Normalize path to detect duplicates (e.g., Song.mp3 vs Song.MP3)
        local normalized=$(printf '%s\n' "$f" | tr '[:upper:]' '[:lower:]')
        
        # Check if we've already seen this file (case-insensitive)
        local is_duplicate=0
        for seen in "${seen_files[@]}"; do
            if [ "$normalized" = "$seen" ]; then
                is_duplicate=1
                break
            fi
        done
        
        # Only add if not a duplicate and is a regular file
        if [ "$is_duplicate" -eq 0 ] && [ -f "$f" ]; then
            music_files+=("$f")
            seen_files+=("$normalized")
        fi
    done
    shopt -u nullglob nocaseglob

    if [ ${#music_files[@]} -eq 0 ]; then
        log "[Music] No MP3 files found in $MUSIC_DIR"
        return 1
    fi

    log "[Music] Found ${#music_files[@]} unique MP3 file(s) in playlist"
    > "$MUSIC_PLAYLIST"
    local esc
    for f in "${music_files[@]}"; do
        # Escape single quotes for the concat demuxer ("Don't Stop.mp3" etc.)
        esc=$(printf '%s' "$f" | sed "s/'/'\\\\''/g")
        echo "file '$esc'" >> "$MUSIC_PLAYLIST"
    done
    
    # Validate playlist has at least one entry
    if [ ! -s "$MUSIC_PLAYLIST" ]; then
        log "[Music] ERROR: Playlist file is empty!"
        return 1
    fi
    
    return 0
}

# ==============================================================================
#  INITIALIZATION
# ==============================================================================
log "--- 1. Checking Hardware Acceleration ---"
check_vaapi
record_encoder_mode

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
            with requests.get(item['download_url'], stream=True, timeout=(5, 30)) as r, open(os.path.join(DESTINATION_FOLDER, item['name']), 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
    except Exception as e:
        print(f"[Icons] Download skipped/failed: {e}")
if __name__ == "__main__": run()
EOF
# Hard cap: a hung connection must never block the stream from starting
timeout 180 python3 /tmp/download_icons.py; rm /tmp/download_icons.py

mkdir -p "$ADS_BASE/topleft/DAY" "$ADS_BASE/topleft/NIGHT" "$ADS_BASE/topright/DAY" "$ADS_BASE/topright/NIGHT"

# ==============================================================================
#  OVERLAY LAYOUT (positions editable in the Admin WebUI)
# ==============================================================================
OVERLAY_LAYOUT_SH="$WORKDIR/overlay_layout.sh"
load_overlay_layout() {
    # Regenerates the shell fragment from overlay_layout.json (creating defaults
    # on first run), then sources it. The fragment holds only integer
    # assignments, so sourcing it is safe.
    python3 /overlay_layout.py sh > /dev/null 2>&1
    if [ -f "$OVERLAY_LAYOUT_SH" ]; then
        # shellcheck disable=SC1090
        . "$OVERLAY_LAYOUT_SH"
    fi
    # Fall back to the classic corner positions if anything went wrong
    : "${LAYOUT_TL_X:=20}"      "${LAYOUT_TL_Y:=20}"
    : "${LAYOUT_TL_W:=$SCALE_ADS_TL}"  "${LAYOUT_TL_H:=$SCALE_ADS_TL}"  "${LAYOUT_TL_ENABLED:=1}"
    : "${LAYOUT_TR_X:=$((2560 - SCALE_ADS_TR - 20))}" "${LAYOUT_TR_Y:=20}"
    : "${LAYOUT_TR_W:=$SCALE_ADS_TR}"  "${LAYOUT_TR_H:=$SCALE_ADS_TR}"  "${LAYOUT_TR_ENABLED:=1}"
    : "${LAYOUT_WEATHER_X:=1640}" "${LAYOUT_WEATHER_Y:=920}"
    : "${LAYOUT_WEATHER_W:=900}"  "${LAYOUT_WEATHER_H:=500}" "${LAYOUT_WEATHER_ENABLED:=1}"
}
load_overlay_layout
log "Overlay layout: TL ${LAYOUT_TL_W}x${LAYOUT_TL_H}@${LAYOUT_TL_X},${LAYOUT_TL_Y} | TR ${LAYOUT_TR_W}x${LAYOUT_TR_H}@${LAYOUT_TR_X},${LAYOUT_TR_Y} | Weather ${LAYOUT_WEATHER_W}x${LAYOUT_WEATHER_H}@${LAYOUT_WEATHER_X},${LAYOUT_WEATHER_Y}"

log "--- Configuring Stream Output ---"
if [ "$DIRECT_YOUTUBE_MODE" = "false" ]; then
    log "MediaMTX mode enabled"
    if [ "$ENABLE_LOCAL_STREAM" = "true" ] && { [ "$ADMIN_PASS" = "your_secure_password" ] || [ "$ADMIN_PASS" = "change_me_please" ]; }; then
        log "WARNING: ADMIN_PASS is a shipped default - the exposed RTSP output is protected by well-known credentials. Change it!"
    fi
    if [ "$ENABLE_LOCAL_STREAM" = "true" ]; then RTSP_ADDRESS=":8554"; else RTSP_ADDRESS="127.0.0.1:8554"; fi
    # Write the config to /tmp (NOT /usr/local/bin): when PUID is set the script
    # re-execs as a non-root user that cannot write to /usr/local/bin.
    MEDIAMTX_CONF="/tmp/mediamtx.yml"
    # NOTE: uses MediaMTX v1.x keys (rtmp/hls/webrtc/srt) - the pre-1.0
    # *Disable keys make v1.15 exit with "non-existent parameter".
    cat <<EOF > "$MEDIAMTX_CONF"
rtspAddress: $RTSP_ADDRESS
readTimeout: 60s
writeTimeout: 60s
rtmp: no
hls: no
webrtc: no
srt: no
api: yes
apiAddress: 127.0.0.1:9997
authMethod: internal
authInternalUsers: [{ user: "$(yaml_escape "$ADMIN_USER")", pass: "$(yaml_escape "$ADMIN_PASS")", permissions: [{ action: api }, { action: publish }, { action: read }] }]
paths: { all_others: }
EOF
    chmod 600 "$MEDIAMTX_CONF" 2>/dev/null
    /usr/local/bin/mediamtx "$MEDIAMTX_CONF" &
    sleep 2
else
    log "Direct-to-YouTube mode enabled"
fi

# Audio API always runs (the Docker healthcheck depends on its /health endpoint)
python3 /audio_api.py & sleep 1

# Admin WebUI (dashboard + on-demand stream preview) - see README
if [ "${ADMIN_WEBUI_ENABLED:-true}" = "true" ]; then
    log "--- Starting Admin WebUI on port ${ADMIN_PORT:-9999} ---"
    python3 /admin_api.py &
fi

if [ ! -f "$WEATHER_COMBINED" ]; then python3 /weather.py blank "$WEATHER_COMBINED" "900" "500"; fi
update_weather_playlist "0"
python3 /weather.py blank "$AD_FINAL_TL" "$SCALE_ADS_TL" "$SCALE_ADS_TL"
echo -e "file '$AD_FINAL_TL'\nduration 10\nfile '$AD_FINAL_TL'" > "$AD_PLAYLIST_TL"
python3 /weather.py blank "$AD_FINAL_TR" "$SCALE_ADS_TR" "$SCALE_ADS_TR"
echo -e "file '$AD_FINAL_TR'\nduration 10\nfile '$AD_FINAL_TR'" > "$AD_PLAYLIST_TR"

if [ "$FALLBACK_ENABLED" = "true" ]; then
    log "--- Generating Fallback Screen ---"
    python3 /weather.py fallback "$FALLBACK_IMAGE" "$YOUTUBE_WIDTH" "$YOUTUBE_HEIGHT" "We'll Be Right Back"
fi
# Always reset the mode at boot - a stale "fallback" left from a previous run
# would make the watchdog skip every recovery (it defers while in fallback).
echo "normal" > "$STREAM_MODE_FILE"

# ==============================================================================
#  BACKGROUND MANAGERS
# ==============================================================================
# DAY/NIGHT for sponsor rotation. In "sun" mode the answer is precomputed into
# $DAY_NIGHT_FILE by the solar manager below, so this stays a cheap file read
# even though it is called from tight loops; it falls back to the fixed clock
# schedule whenever that file is missing or stale.
get_mode() {
    if [ "$DAY_NIGHT_MODE" = "sun" ] && [ -s "$DAY_NIGHT_FILE" ]; then
        local m; m=$(cat "$DAY_NIGHT_FILE" 2>/dev/null)
        if [ "$m" = "DAY" ] || [ "$m" = "NIGHT" ]; then echo "$m"; return; fi
    fi
    local hr; hr=$(date +%-H)
    if [ "$hr" -ge "$DAY_START_HOUR" ] && [ "$hr" -lt "$DAY_END_HOUR" ]; then echo "DAY"; else echo "NIGHT"; fi
}

# Solar manager: resolves sunrise/sunset once a minute (the fetch itself is
# cached per day inside sun_times.py, so this is one HTTP call every 24h).
if [ "$DAY_NIGHT_MODE" = "sun" ]; then
    SUN_INIT=$(python3 /sun_times.py 2>/dev/null || echo "unavailable")
    log "Day/night source: sunrise-sunset (currently $SUN_INIT)"
    (
        LAST_SUN_MODE=""
        while true; do
            python3 /sun_times.py >/dev/null 2>&1
            NOW_MODE=$(cat "$DAY_NIGHT_FILE" 2>/dev/null)
            if [ -n "$NOW_MODE" ] && [ "$NOW_MODE" != "$LAST_SUN_MODE" ]; then
                [ -n "$LAST_SUN_MODE" ] && record_event "sponsor" "info" "Switched to $NOW_MODE sponsors (solar)"
                LAST_SUN_MODE="$NOW_MODE"
            fi
            sleep 60
        done
    ) &
else
    log "Day/night source: fixed clock (${DAY_START_HOUR}:00-${DAY_END_HOUR}:00)"
fi

# Sponsor rotation honours the schedule in /config/ads/sponsors.json. If that
# lookup fails for any reason we fall back to a plain directory glob, so a bug
# in the scheduler can never blank the overlays.
list_sponsors() {
    local slot="$1" mode="$2" out
    if out=$(python3 /sponsors.py list "$slot" "$mode" 2>/dev/null); then
        printf '%s\n' "$out"
        return
    fi
    shopt -s nocaseglob nullglob
    local d="$ADS_BASE/$slot/$mode"
    printf '%s\n' "$d"/*.png "$d"/*.jpg "$d"/*.jpeg "$d"/*.webp
}

# Airtime ledger (backgrounded - never delay a rotation for bookkeeping)
record_airtime() { python3 /sponsors.py record "$1" "$2" "$(basename "$3")" "$4" >/dev/null 2>&1 & }

# TL Manager
(
    shopt -s nocaseglob nullglob
    while true; do
        # Re-read the layout each pass so logos are re-rendered at the box size
        # the operator picked in the WebUI (keeps them crisp after a resize).
        [ -f "$OVERLAY_LAYOUT_SH" ] && . "$OVERLAY_LAYOUT_SH"
        TL_W="${LAYOUT_TL_W:-$SCALE_ADS_TL}"; TL_H="${LAYOUT_TL_H:-$SCALE_ADS_TL}"
        MODE=$(get_mode)
        mapfile -t FILES < <(list_sponsors topleft "$MODE" | grep -v '^[[:space:]]*$')
        if [ ${#FILES[@]} -eq 0 ]; then
            # Atomic swap: never rewrite the live overlay in place while ffmpeg reads it
            if python3 /weather.py blank "$AD_TEMP_TL" "$TL_W" "$TL_H"; then mv -f "$AD_TEMP_TL" "$AD_FINAL_TL"; fi
            LAST_AD_HASH_TL=""; sleep 60; else
            for f in "${FILES[@]}"; do
                if [ "$(get_mode)" != "$MODE" ]; then break; fi
                # Size is part of the cache key so a resize forces a re-render
                CURRENT_HASH=$(md5sum "$f" 2>/dev/null | cut -d' ' -f1)"-${TL_W}x${TL_H}"
                if [ "$CURRENT_HASH" != "$LAST_AD_HASH_TL" ] || [ ! -f "$AD_FINAL_TL" ]; then
                    if python3 /weather.py ad "$AD_TEMP_TL" "$f" "$TL_W" "$TL_H"; then mv -f "$AD_TEMP_TL" "$AD_FINAL_TL"; LAST_AD_HASH_TL="$CURRENT_HASH"; fi
                fi
                sleep "$AD_ROTATE_TIMER_TL"
                record_airtime topleft "$MODE" "$f" "$AD_ROTATE_TIMER_TL"
            done
        fi
    done
) &

# TR Manager
(
    shopt -s nocaseglob nullglob; TR_INDEX=0
    while true; do
        [ -f "$OVERLAY_LAYOUT_SH" ] && . "$OVERLAY_LAYOUT_SH"
        TR_W="${LAYOUT_TR_W:-$SCALE_ADS_TR}"; TR_H="${LAYOUT_TR_H:-$SCALE_ADS_TR}"
        MODE=$(get_mode)
        mapfile -t FILES < <(list_sponsors topright "$MODE" | grep -v '^[[:space:]]*$')
        if [ ${#FILES[@]} -eq 0 ]; then
            if python3 /weather.py blank "$AD_TEMP_TR" "$TR_W" "$TR_H"; then mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"; fi
            LAST_AD_HASH_TR=""; sleep 60; else
            if [ $TR_INDEX -ge ${#FILES[@]} ]; then TR_INDEX=0; fi
            CURRENT_HASH=$(md5sum "${FILES[$TR_INDEX]}" 2>/dev/null | cut -d' ' -f1)"-${TR_W}x${TR_H}"
            if [ "$CURRENT_HASH" != "$LAST_AD_HASH_TR" ] || [ ! -f "$AD_FINAL_TR" ]; then
                if python3 /weather.py ad "$AD_TEMP_TR" "${FILES[$TR_INDEX]}" "$TR_W" "$TR_H"; then mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"; LAST_AD_HASH_TR="$CURRENT_HASH"; fi
            fi
            sleep "$TR_SHOW_SECONDS"
            record_airtime topright "$MODE" "${FILES[$TR_INDEX]}" "$TR_SHOW_SECONDS"
            python3 /weather.py blank "$AD_TEMP_TR" "$TR_W" "$TR_H"; mv -f "$AD_TEMP_TR" "$AD_FINAL_TR"; LAST_AD_HASH_TR=""; sleep "$TR_HIDE_SECONDS"; TR_INDEX=$((TR_INDEX + 1))
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
                if [ -f "$FLASH_TEMP" ]; then
                    mv -f "$FLASH_TEMP" "$WEATHER_COMBINED_FLASH"
                elif [ -f "$WEATHER_COMBINED_FLASH" ]; then
                    # Never delete the flash frame while a running encoder's
                    # playlist may still reference it (a missing concat entry
                    # kills ffmpeg). Overwrite it with the normal frame instead.
                    cp -f "$WEATHER_COMBINED" "${WEATHER_COMBINED_FLASH}.tmp" && mv -f "${WEATHER_COMBINED_FLASH}.tmp" "$WEATHER_COMBINED_FLASH"
                fi
                META_TEMP="${WEATHER_TEMP%.png}_meta.txt"
                if [ -f "$META_TEMP" ]; then update_weather_playlist "$(grep "needs_flash=" "$META_TEMP" | cut -d'=' -f2)"; mv -f "$META_TEMP" "$WEATHER_META"; fi
            fi
            if [ "$(grep "needs_flash=" "$WEATHER_META" 2>/dev/null | cut -d'=' -f2)" = "1" ]; then sleep 60; else sleep "$ALERTS_UPDATE_INTERVAL"; fi
        done
    ) &
fi

# Initialize audio mode only if missing - the user's persisted choice
# (e.g. music) survives container restarts.
if [ ! -f "/config/audio_mode" ]; then echo "muted" > "/config/audio_mode"; fi
if [ "$WATCHDOG_ENABLED" = "true" ] && [ -n "$YOUTUBE_KEY" ]; then log "--- Starting Self-Healing Watchdog ---"; python3 /watchdog.py & fi

# ==============================================================================
#  MAIN STREAM ENCODING
# ==============================================================================
log "--- Starting Main Stream (Hardware: $HARDWARE_ACCEL, Direct YouTube: $DIRECT_YOUTUBE_MODE) ---"
record_event "boot" "info" "Container started (encoder: ${HARDWARE_ACCEL:+VAAPI}${HARDWARE_ACCEL:-software}, direct: $DIRECT_YOUTUBE_MODE)"

# Preflight: probe the ingest layer by layer (DNS -> TCP -> TLS) so a blocked
# port or a broken TLS path is named explicitly instead of surfacing as
# FFmpeg's generic "I/O error". Backgrounded so it never delays the stream.
if [ -n "$YOUTUBE_KEY" ]; then
    (
        python3 /ingest_probe.py --text "$YOUTUBE_URL" 2>/dev/null | while IFS= read -r _l; do log "$_l"; done
    ) &
fi

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
# - timeout: 3 second timeout for initial connect and for reads (detect failures faster)
RTSP_INPUT_OPTS="-thread_queue_size 2048 -rtsp_transport tcp -buffer_size 4194304 -max_delay 500000 -fflags +genpts+discardcorrupt -err_detect ignore_err -timeout 3000000 -i $RTSP_SOURCE"
OVERLAY_INPUTS=""

FILTER_CHAIN="$CAMERA_FILTER"
LAST_V="base"
INPUT_COUNT=1

# Overlay positions come from /config/overlay_layout.json (editable in the
# Admin WebUI). Coordinates are absolute within the 2560x1440 canvas above.
add_overlay() {
    local path=$1; local x=$2; local y=$3; local w=$4; local h=$5

    # Append to OVERLAY_INPUTS instead of the main string, so we can reuse it
    OVERLAY_INPUTS="$OVERLAY_INPUTS -f concat -safe 0 -stream_loop -1 -i $path"

    # force_original_aspect_ratio=decrease: resizing a box never distorts a logo
    local scale_cmd="scale=${w}:${h}:force_original_aspect_ratio=decrease"
    FILTER_CHAIN="${FILTER_CHAIN};[${INPUT_COUNT}:v]${scale_cmd},format=rgba[ovr${INPUT_COUNT}];[${LAST_V}][ovr${INPUT_COUNT}]overlay=${x}:${y}:eof_action=pass:shortest=0[v${INPUT_COUNT}]"
    LAST_V="v$INPUT_COUNT"; INPUT_COUNT=$((INPUT_COUNT+1))
}

if [ "$LAYOUT_TL_ENABLED" = "1" ]; then
    add_overlay "$AD_PLAYLIST_TL" "$LAYOUT_TL_X" "$LAYOUT_TL_Y" "$LAYOUT_TL_W" "$LAYOUT_TL_H"
fi
if [ "$LAYOUT_TR_ENABLED" = "1" ]; then
    add_overlay "$AD_PLAYLIST_TR" "$LAYOUT_TR_X" "$LAYOUT_TR_Y" "$LAYOUT_TR_W" "$LAYOUT_TR_H"
fi
if [ "$WEATHER_ENABLED" = "true" ] && [ "$LAYOUT_WEATHER_ENABLED" = "1" ]; then
    add_overlay "$WEATHER_LIST" "$LAYOUT_WEATHER_X" "$LAYOUT_WEATHER_Y" "$LAYOUT_WEATHER_W" "$LAYOUT_WEATHER_H"
fi

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
        # NOTE: stdout stays redirected to stderr so $(...) PID capture stays clean;
        # stderr is tee'd into $FFMPEG_LOG for the Admin WebUI log viewer.
        if [ "$audio_mode" = "unmuted" ]; then
            ffmpeg -hide_banner -loglevel warning $hw_init $RTSP_INPUT_OPTS $OVERLAY_INPUTS -filter_complex "$final_filters" -map "[vfinal]" -map 0:a? $video_codec -c:a aac -b:a 128k -ac 2 $FFMPEG_PROGRESS_ARG $OUTPUT_EXTRA -f "$OUTPUT_FORMAT" "$OUTPUT_TARGET" 1>&2 2> >(scrub_key | tee -a "$FFMPEG_LOG" >&2) &
        elif [ "$audio_mode" = "music" ]; then
            # Music mode: stream from playlist, loop infinitely with -stream_loop -1
            ffmpeg -hide_banner -loglevel warning $hw_init $RTSP_INPUT_OPTS $OVERLAY_INPUTS -stream_loop -1 -f concat -safe 0 -i "$MUSIC_PLAYLIST" -filter_complex "$final_filters" -map "[vfinal]" -map $((INPUT_COUNT)):a $video_codec -c:a aac -b:a 128k -ac 2 $FFMPEG_PROGRESS_ARG $OUTPUT_EXTRA -f "$OUTPUT_FORMAT" "$OUTPUT_TARGET" 1>&2 2> >(scrub_key | tee -a "$FFMPEG_LOG" >&2) &
        else
            ffmpeg -hide_banner -loglevel warning $hw_init $RTSP_INPUT_OPTS $OVERLAY_INPUTS -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -filter_complex "$final_filters" -map "[vfinal]" -map $((INPUT_COUNT)):a $video_codec -c:a aac -b:a 128k $FFMPEG_PROGRESS_ARG $OUTPUT_EXTRA -f "$OUTPUT_FORMAT" "$OUTPUT_TARGET" 1>&2 2> >(scrub_key | tee -a "$FFMPEG_LOG" >&2) &
        fi
        echo $!
    }

    run_fallback_ffmpeg() {
        log "[Fallback] Starting 'We'll Be Right Back' stream (With Overlays)..." >&2

        # Fresh progress file so the Docker healthcheck stays green during
        # camera outages (the BRB encoder keeps it advancing)
        rm -f "$FFMPEG_PROGRESS_FILE"; touch "$FFMPEG_PROGRESS_FILE"

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
            $FFMPEG_PROGRESS_ARG \
            $OUTPUT_EXTRA -f "$OUTPUT_FORMAT" "$OUTPUT_TARGET" 1>&2 2> >(scrub_key | tee -a "$FFMPEG_LOG" >&2) &
        echo $!
    }

    CURRENT_MODE="normal"
    FFMPEG_PID=""
    PAUSE_ANNOUNCED=0
    LAST_MTIME=""
    FROZEN_COUNT=0
    LAST_FRAME=""
    VIDEO_FROZEN_COUNT=0

    while true; do
        # Operator-requested stop: hold everything down until Start is pressed.
        if is_paused; then
            if [ -n "$FFMPEG_PID" ] && kill -0 $FFMPEG_PID 2>/dev/null; then
                log "[Control] Broadcast stopped by operator - terminating FFmpeg (PID $FFMPEG_PID)"
                kill $FFMPEG_PID 2>/dev/null
                for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 $FFMPEG_PID 2>/dev/null || break; sleep 1; done
                kill -9 $FFMPEG_PID 2>/dev/null
            fi
            if [ "$PAUSE_ANNOUNCED" != "1" ]; then
                log "[Control] Broadcast is STOPPED. Press Start in the Admin WebUI to resume."
                record_event "operator_stop" "warn" "Broadcast stopped by operator"
                echo "stopped" > "$STREAM_MODE_FILE"
                PAUSE_ANNOUNCED=1
            fi
            FFMPEG_PID=""
            sleep 2
            continue
        fi
        if [ "$PAUSE_ANNOUNCED" = "1" ]; then
            log "[Control] Broadcast resumed by operator."
            record_event "operator_start" "success" "Broadcast resumed by operator"
            PAUSE_ANNOUNCED=0
            CURRENT_MODE="normal"
            echo "normal" > "$STREAM_MODE_FILE"
            rm -f "$RESTART_HOLD_FILE"
        fi

        if [ -z "$FFMPEG_PID" ] || ! kill -0 $FFMPEG_PID 2>/dev/null; then
            if [ "$CURRENT_MODE" = "normal" ]; then
                honor_restart_hold
                trim_ffmpeg_log
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
                    rm -f "$FFMPEG_PROGRESS_FILE"; touch "$FFMPEG_PROGRESS_FILE"; LAST_MTIME=""; FROZEN_COUNT=0; LAST_FRAME=""; VIDEO_FROZEN_COUNT=0
                    FFMPEG_PID=$(run_camera_ffmpeg "$AUDIO_MODE")
                    FFMPEG_START_TIME=$(date +%s)
                    sleep 2
                    if kill -0 $FFMPEG_PID 2>/dev/null; then break; fi
                    log "Startup attempt $((RETRY_COUNT+1)) failed. Retrying in 2s..."
                    RETRY_COUNT=$((RETRY_COUNT+1))
                done
                if ! kill -0 $FFMPEG_PID 2>/dev/null; then
                    # Diagnose WHICH leg failed before deciding what to do. The
                    # BRB screen publishes to the SAME output, so falling back
                    # when the *output* is broken just fails again instantly and
                    # hammers the ingest server in a tight loop.
                    STARTUP_FAIL_COUNT=$(( ${STARTUP_FAIL_COUNT:-0} + 1 ))
                    OUTPUT_SIDE=0
                    if ! check_youtube_ingest; then
                        log "[ERROR] Cannot reach the ${YT_SCHEME} ingest ${YT_HOST}:${YT_PORT}."
                        log "[ERROR] Nothing can be published until that endpoint is reachable from this container."
                        OUTPUT_SIDE=1
                    elif check_rtsp_basic; then
                        log "[ERROR] Camera AND ingest (${YT_HOST}:${YT_PORT}) are both reachable, but FFmpeg refused to start."
                        # Layer-by-layer probe distinguishes a TLS problem from a rejected key
                        python3 /ingest_probe.py --text "$YOUTUBE_URL" 2>/dev/null | while IFS= read -r _l; do log "$_l"; done
                        log "[ERROR] If the probe above says the ingest is fine, this is an output-side"
                        log "[ERROR] rejection: a bad/rotated stream key, a broadcast that is not live-ready,"
                        log "[ERROR] or another encoder already publishing with the same key."
                        log "[ERROR] Last FFmpeg output:"
                        tail -n 8 "$FFMPEG_LOG" 2>/dev/null | while IFS= read -r _l; do log "    $_l"; done
                        OUTPUT_SIDE=1
                    fi

                    if [ "$OUTPUT_SIDE" = "1" ]; then
                        BACKOFF=$(( STARTUP_FAIL_COUNT * 10 ))
                        [ $BACKOFF -gt 120 ] && BACKOFF=120
                        log "Staying in normal mode (BRB would hit the same output). Retry #$STARTUP_FAIL_COUNT in ${BACKOFF}s..."
                        record_event "encoder_fail" "error" "Publishing failed (attempt $STARTUP_FAIL_COUNT) - ingest reachable but refused; retrying in ${BACKOFF}s"
                        FFMPEG_PID=""
                        sleep $BACKOFF
                        continue
                    fi

                    if [ "$FALLBACK_ENABLED" = "true" ]; then
                        log "Camera unreachable at startup. Switching to Fallback..."
                        record_event "camera_down" "error" "Camera unreachable at startup - showing BRB screen"
                        CURRENT_MODE="fallback"
                        echo "fallback" > "$STREAM_MODE_FILE"
                        FFMPEG_PID=$(run_fallback_ffmpeg)
                        FFMPEG_START_TIME=$(date +%s)
                    else
                        log "Startup failed and fallback is disabled. Retrying in 10s..."
                        FFMPEG_PID=""
                        sleep 10
                        continue
                    fi
                fi
                STARTUP_FAIL_COUNT=0
                echo $FFMPEG_PID > "/config/youtube_restreamer.pid"
                log "FFmpeg started (PID: $FFMPEG_PID)"
                record_event "encoder_start" "success" "Encoder started (PID $FFMPEG_PID, audio $AUDIO_MODE)"
            else
                FFMPEG_PID=$(run_fallback_ffmpeg)
                FFMPEG_START_TIME=$(date +%s)
                echo $FFMPEG_PID > "/config/youtube_restreamer.pid"
            fi
        fi

        LOOP_COUNT=0
        while kill -0 $FFMPEG_PID 2>/dev/null; do
            LOOP_COUNT=$((LOOP_COUNT + 1))

            # 1. ZOMBIE CHECK (mtime-based) - runs in BOTH modes: a wedged BRB
            # encoder used to go unrecovered for the whole camera outage since
            # neither this check nor the watchdog covered fallback mode.
            # FFmpeg rewrites the -progress file every ~0.5s; if its mtime stops
            # changing for 12 consecutive checks the encoder is frozen. (mtime is
            # used instead of file size so the file can be safely truncated below
            # without breaking detection.)
            # Skip frozen detection for first 5 seconds after startup (initialization time)
            FFMPEG_UPTIME=$(( $(date +%s) - FFMPEG_START_TIME ))
            if [ $FFMPEG_UPTIME -gt 5 ]; then
                CURRENT_MTIME=$(stat -c %Y "$FFMPEG_PROGRESS_FILE" 2>/dev/null || echo 0)
                if [ "$CURRENT_MTIME" = "$LAST_MTIME" ]; then
                    FROZEN_COUNT=$((FROZEN_COUNT + 1))
                    if [ $FROZEN_COUNT -ge 12 ]; then
                        log "[ERROR] FFmpeg FROZEN (no progress writes for 12s after ${FFMPEG_UPTIME}s uptime). Killing..."
                        record_event "encoder_fail" "error" "Encoder frozen (no progress for 12s) - restarting"
                        kill -9 $FFMPEG_PID 2>/dev/null
                        break
                    fi
                else
                    FROZEN_COUNT=0
                    LAST_MTIME="$CURRENT_MTIME"
                fi
                # VIDEO-FRAME CHECK: with silent/music audio the progress
                # file keeps updating even if the camera video stalls, so
                # also require the video frame counter to advance.
                CURRENT_FRAME=$(tail -c 4096 "$FFMPEG_PROGRESS_FILE" 2>/dev/null | grep '^frame=' | tail -1 | cut -d= -f2)
                if [ -n "$CURRENT_FRAME" ] && [ "$CURRENT_FRAME" = "$LAST_FRAME" ]; then
                    VIDEO_FROZEN_COUNT=$((VIDEO_FROZEN_COUNT + 1))
                    if [ $VIDEO_FROZEN_COUNT -ge 30 ]; then
                        log "[ERROR] Video FROZEN at frame $CURRENT_FRAME for 30s (audio still flowing). Killing..."
                        record_event "encoder_fail" "error" "Video frozen at frame $CURRENT_FRAME while audio kept flowing - restarting"
                        kill -9 $FFMPEG_PID 2>/dev/null
                        break
                    fi
                else
                    VIDEO_FROZEN_COUNT=0
                    LAST_FRAME="$CURRENT_FRAME"
                fi
                # Cap progress file growth on long runs (~10MB/day previously
                # grew unbounded in /config)
                if [ $((LOOP_COUNT % 3600)) -eq 0 ] && [ "$(wc -c < "$FFMPEG_PROGRESS_FILE" 2>/dev/null || echo 0)" -gt 10485760 ]; then
                    : > "$FFMPEG_PROGRESS_FILE"
                fi
            else
                # Still initializing, reset frozen counters
                FROZEN_COUNT=0
                LAST_MTIME=""
                VIDEO_FROZEN_COUNT=0
                LAST_FRAME=""
            fi

            # 1b. Operator stop request - leave the monitor loop at once
            if is_paused; then break; fi

            # 2. Audio Check
            if [ "$CURRENT_MODE" = "normal" ]; then
                NEW_AUDIO=$(cat "/config/audio_mode" 2>/dev/null || echo "muted")
                if [ "$NEW_AUDIO" != "$AUDIO_MODE" ]; then
                    log "Audio Change"
                    record_event "audio" "info" "Audio mode changed: $AUDIO_MODE -> $NEW_AUDIO"
                    kill $FFMPEG_PID 2>/dev/null
                    # Confirm the old encoder is dead before respawning - two
                    # encoders on the same stream key glitch the YouTube ingest
                    for _ in 1 2 3 4 5 6 7 8 9 10; do
                        kill -0 $FFMPEG_PID 2>/dev/null || break
                        sleep 1
                    done
                    if kill -0 $FFMPEG_PID 2>/dev/null; then kill -9 $FFMPEG_PID 2>/dev/null; sleep 1; fi
                    FFMPEG_PID=""
                    break
                fi
            fi

            # 3. Connection Health Check (Every 3s)
            if [ $((LOOP_COUNT % 3)) -eq 0 ]; then
                if [ "$CURRENT_MODE" = "normal" ] && [ "$FALLBACK_ENABLED" = "true" ]; then
                   if ! check_rtsp_basic; then
                       log "[Fallback] RTSP Ping Failed - Killing PID $FFMPEG_PID..."
                       record_event "camera_down" "error" "Camera stopped responding - switching to BRB screen"
                       kill -9 $FFMPEG_PID 2>/dev/null
                       break
                   fi
                fi
                if [ "$CURRENT_MODE" = "fallback" ]; then
                   if check_rtsp_basic; then
                       log "[Fallback] RTSP Recovered! Killing BRB Stream (PID $FFMPEG_PID) to switch..."
                       record_event "camera_up" "success" "Camera came back - leaving BRB screen"
                       kill -9 $FFMPEG_PID 2>/dev/null
                       break
                   fi
                fi
            fi

            # Heartbeat Logging every 10s
            if [ $((LOOP_COUNT % 10)) -eq 0 ] && [ "$CURRENT_MODE" = "normal" ]; then
                log "[Heartbeat] Monitoring Stream... PID:$FFMPEG_PID Uptime:${FFMPEG_UPTIME:-0}s"
            fi

            sleep 1
        done

        # FFmpeg Died/Killed Logic
        if [ -n "$FFMPEG_PID" ] && ! kill -0 $FFMPEG_PID 2>/dev/null; then
            wait $FFMPEG_PID 2>/dev/null; EXIT_CODE=$?
            # ffmpeg is spawned inside a command substitution subshell, so it is
            # not a job of this shell and wait reports 127 - don't log it as a
            # meaningful exit code.
            [ "$EXIT_CODE" = "127" ] && EXIT_CODE="n/a"
            if [ "$CURRENT_MODE" = "normal" ] && [ -f "$RESTART_HOLD_FILE" ]; then
                # Intentional restart (watchdog or WebUI/API) - skip the BRB
                # detour and respawn in normal mode; honor_restart_hold paces it.
                log "FFmpeg stopped for a managed restart (Code $EXIT_CODE). Respawning..."
            elif [ "$CURRENT_MODE" = "normal" ] && [ "$FALLBACK_ENABLED" = "true" ]; then
                if check_rtsp_basic; then
                    # Camera is fine - the failure is output-side (YouTube
                    # ingest/encoder). The BRB stream pushes to the same output
                    # and would fail identically, so retry normal mode with a
                    # growing delay instead of flapping normal<->BRB at full
                    # speed against the RTMP endpoint.
                    if [ $(( $(date +%s) - ${FFMPEG_START_TIME:-0} )) -ge 60 ]; then OUTPUT_FAIL_COUNT=0; fi
                    OUTPUT_FAIL_COUNT=$(( ${OUTPUT_FAIL_COUNT:-0} + 1 ))
                    RETRY_DELAY=$((OUTPUT_FAIL_COUNT * 5)); [ $RETRY_DELAY -gt 60 ] && RETRY_DELAY=60
                    log "[Fallback] Stream died (Code $EXIT_CODE) but camera is reachable - output-side failure. Retrying normal mode in ${RETRY_DELAY}s..."
                    sleep $RETRY_DELAY
                else
                    log "[Fallback] Stream died (Code $EXIT_CODE). Switching..."
                    record_event "fallback_enter" "warn" "Encoder died and camera is unreachable - BRB screen live"
                    CURRENT_MODE="fallback"
                    echo "fallback" > "$STREAM_MODE_FILE"
                fi
            elif [ "$CURRENT_MODE" = "fallback" ]; then
                 if check_rtsp_basic; then
                     log "[Fallback] Ready. Switching to Normal..."
                     record_event "fallback_exit" "success" "Returning to the camera feed"
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
    if [ "$HARDWARE_ACCEL" = "true" ]; then
        FINAL_FILTERS="${FILTER_CHAIN};[${LAST_V}]format=nv12[soft_final];[soft_final]hwupload[vfinal]"
        HW_INIT="-init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va"
        VIDEO_CODEC="-c:v h264_vaapi -b:v $VIDEO_BITRATE -maxrate $VIDEO_BITRATE -bufsize 28M -r $VIDEO_FPS -g $(($VIDEO_FPS * 2))"
    else
        FINAL_FILTERS="${FILTER_CHAIN};[${LAST_V}]format=yuv420p[vfinal]"
        HW_INIT=""
        VIDEO_CODEC="-c:v libx264 -preset $SOFTWARE_PRESET -crf $SOFTWARE_CRF -b:v $VIDEO_BITRATE -maxrate $VIDEO_BITRATE -bufsize 28M -r $VIDEO_FPS -g $(($VIDEO_FPS * 2))"
    fi

    # --- YouTube Restreamer (MediaMTX -> YouTube) ---
    # Restored: this second FFmpeg leg (documented in the README since v2.7)
    # was lost in the v2.8.3 refactor, so MediaMTX mode never actually pushed
    # to YouTube. It reads the composed local stream and re-encodes for YouTube,
    # with the same audio-mode support (muted / unmuted / music) as direct mode.
    if [ -n "$YOUTUBE_KEY" ]; then
        if [ ! -f "/config/audio_mode" ]; then echo "muted" > "/config/audio_mode"; fi
        (
            sleep 10
            if [ "$HARDWARE_ACCEL" = "true" ]; then
                YT_FILTERS="scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT},format=nv12,hwupload"
                YT_HW_INIT="-init_hw_device vaapi=va:$VAAPI_DEVICE -filter_hw_device va"
                YT_CODEC="-c:v h264_vaapi -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
            else
                YT_FILTERS="scale=${YOUTUBE_WIDTH}:${YOUTUBE_HEIGHT}"
                YT_HW_INIT=""
                YT_CODEC="-c:v libx264 -preset $SOFTWARE_PRESET -b:v $YOUTUBE_BITRATE -maxrate $YOUTUBE_BITRATE -bufsize 9000k -g 60"
            fi
            LOCAL_URL="rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live"
            while true; do
                if is_paused; then sleep 2; continue; fi
                honor_restart_hold
                trim_ffmpeg_log
                AUDIO_MODE=$(cat "/config/audio_mode" 2>/dev/null || echo "muted")
                if [ "$AUDIO_MODE" = "music" ] && ! generate_music_playlist; then
                    log "[Restreamer] No music files available, falling back to muted"
                    AUDIO_MODE="muted"
                fi
                rm -f "$FFMPEG_PROGRESS_FILE"; touch "$FFMPEG_PROGRESS_FILE"
                if [ "$AUDIO_MODE" = "unmuted" ]; then
                    ffmpeg -hide_banner -loglevel warning $YT_HW_INIT -rtsp_transport tcp -i "$LOCAL_URL" \
                        -vf "$YT_FILTERS" -map 0:v:0 -map 0:a:0? $YT_CODEC -c:a aac -b:a 128k -ac 2 \
                        $FFMPEG_PROGRESS_ARG $OUTPUT_EXTRA -f "$OUTPUT_FORMAT" "$OUTPUT_TARGET" 2> >(scrub_key | tee -a "$FFMPEG_LOG" >&2) &
                elif [ "$AUDIO_MODE" = "music" ]; then
                    ffmpeg -hide_banner -loglevel warning $YT_HW_INIT -rtsp_transport tcp -i "$LOCAL_URL" \
                        -stream_loop -1 -f concat -safe 0 -i "$MUSIC_PLAYLIST" \
                        -vf "$YT_FILTERS" -map 0:v:0 -map 1:a $YT_CODEC -c:a aac -b:a 128k -ac 2 \
                        $FFMPEG_PROGRESS_ARG $OUTPUT_EXTRA -f "$OUTPUT_FORMAT" "$OUTPUT_TARGET" 2> >(scrub_key | tee -a "$FFMPEG_LOG" >&2) &
                else
                    ffmpeg -hide_banner -loglevel warning $YT_HW_INIT -rtsp_transport tcp -i "$LOCAL_URL" \
                        -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
                        -vf "$YT_FILTERS" -map 0:v:0 -map 1:a:0 $YT_CODEC -c:a aac -b:a 128k \
                        $FFMPEG_PROGRESS_ARG $OUTPUT_EXTRA -f "$OUTPUT_FORMAT" "$OUTPUT_TARGET" 2> >(scrub_key | tee -a "$FFMPEG_LOG" >&2) &
                fi
                YT_PID=$!
                echo $YT_PID > "/config/youtube_restreamer.pid"
                log "[Restreamer] YouTube leg started (PID: $YT_PID, audio: $AUDIO_MODE)"
                YT_LOOPS=0
                while kill -0 $YT_PID 2>/dev/null; do
                    if is_paused; then
                        log "[Control] Broadcast stopped by operator - terminating YouTube leg"
                        kill $YT_PID 2>/dev/null; break
                    fi
                    YT_LOOPS=$((YT_LOOPS + 1))
                    # Cap progress file growth on long runs (~hourly at 2s/loop)
                    if [ $((YT_LOOPS % 1800)) -eq 0 ] && [ "$(wc -c < "$FFMPEG_PROGRESS_FILE" 2>/dev/null || echo 0)" -gt 10485760 ]; then
                        : > "$FFMPEG_PROGRESS_FILE"
                    fi
                    NEW_AUDIO=$(cat "/config/audio_mode" 2>/dev/null || echo "muted")
                    if [ "$NEW_AUDIO" != "$AUDIO_MODE" ]; then
                        log "[Restreamer] Audio change ($AUDIO_MODE -> $NEW_AUDIO). Restarting YouTube leg..."
                        kill $YT_PID 2>/dev/null
                        break
                    fi
                    sleep 2
                done
                wait $YT_PID 2>/dev/null
                sleep 3
            done
        ) &
    fi

    while true; do
        # Local encoder: camera + overlays -> MediaMTX. The -progress file is
        # owned by the YouTube restreamer leg above (that's the stream the
        # watchdog cares about), so it is not written here.
        ffmpeg -hide_banner -loglevel warning $HW_INIT $RTSP_INPUT_OPTS $OVERLAY_INPUTS -filter_complex "$FINAL_FILTERS" -map "[vfinal]" -map 0:a? $VIDEO_CODEC -c:a copy -f rtsp -rtsp_transport tcp "rtsp://$ADMIN_USER:$ADMIN_PASS@localhost:8554/live"
        log "FFmpeg exited, restarting in 5 seconds..."
        sleep 5
    done
fi
