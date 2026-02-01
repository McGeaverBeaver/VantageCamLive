#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VantageCam Self-Healing Watchdog v2.9.0
Monitors YouTube stream status and automatically recovers failed streams.
Also handles setting the broadcast to PUBLIC after recovery.

v2.9.0 Changes:
- CRITICAL FIX: RTSP health check now validates actual video frames using ffprobe
- Previously only TCP port check was used, which would pass even if camera had no video
- This caused infinite restart loops when source was "reachable" but not providing video
- Now properly detects "TCP up but no video" scenarios (internet outage, camera freeze)

v2.8.1 Changes:
- Added RTSP source health check before attempting recovery
- Extended verification window (120s default, configurable)
- Added verbose logging of status check responses
- Added RTSP_SOURCE logging at startup and during checks
- Added pre-flight RTSP connectivity test before FFmpeg restart
- Smarter recovery: won't restart if RTSP source is down
"""

import os
import sys
import time
import json
import signal
import random
import subprocess
import socket
import logging
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse

# ==============================================================================
#  CONFIGURATION (from environment variables)
# ==============================================================================

# Watchdog settings
WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "true").lower() == "true"
STATUS_URL = os.getenv("WATCHDOG_STATUS_URL", "")
CHECK_INTERVAL = int(os.getenv("WATCHDOG_CHECK_INTERVAL", "30"))
INITIAL_DELAY = int(os.getenv("WATCHDOG_INITIAL_DELAY", "10"))
MAX_DELAY = int(os.getenv("WATCHDOG_MAX_DELAY", "900"))  # 15 minutes max
STABILITY_THRESHOLD = int(os.getenv("WATCHDOG_STABILITY_THRESHOLD", "30"))

# RTSP Source (for health checking)
RTSP_SOURCE = os.getenv("RTSP_SOURCE", "")

# Verification settings (NEW)
VERIFICATION_TIMEOUT = int(os.getenv("WATCHDOG_VERIFICATION_TIMEOUT", "120"))  # Extended from 60s
RTSP_CHECK_ENABLED = os.getenv("WATCHDOG_RTSP_CHECK", "true").lower() == "true"
VERBOSE_LOGGING = os.getenv("WATCHDOG_VERBOSE", "true").lower() == "true"

# Initial startup delay - how long to wait before first check after boot
# YouTube can take 3-5+ minutes to recognize a new ingest
STARTUP_DELAY = int(os.getenv("WATCHDOG_STARTUP_DELAY", "180"))  # Default 3 minutes

# YouTube API settings (for setting broadcast to PUBLIC)
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "")

# Discord notification settings
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_USER_ID = os.getenv("DISCORD_USER_ID", "")  # For @mention alerts

# Internal paths
PID_FILE = "/config/youtube_restreamer.pid"
PROGRESS_FILE = "/config/ffmpeg_progress.txt"
WATCHDOG_STATE_FILE = "/config/watchdog_state.json"
LOG_FILE = "/config/watchdog.log"
STREAM_MODE_FILE = "/config/stream_mode"  # Tracks "normal" or "fallback"

# ==============================================================================
#  LOGGING SETUP
# ==============================================================================

logging.basicConfig(
    level=logging.DEBUG if VERBOSE_LOGGING else logging.INFO,
    format='[%(asctime)s] [Watchdog] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode='a')
    ]
)
logger = logging.getLogger(__name__)

# ==============================================================================
#  RTSP SOURCE HEALTH CHECK (NEW)
# ==============================================================================

def parse_rtsp_url(rtsp_url):
    """Parse RTSP URL to extract host and port"""
    try:
        # Handle rtsp://user:pass@host:port/path format
        if '@' in rtsp_url:
            # Split off credentials
            parts = rtsp_url.split('@')
            host_part = parts[1]
        else:
            host_part = rtsp_url.replace('rtsp://', '')

        # Extract host and port
        if '/' in host_part:
            host_port = host_part.split('/')[0]
        else:
            host_port = host_part

        if ':' in host_port:
            host, port = host_port.rsplit(':', 1)
            port = int(port)
        else:
            host = host_port
            port = 554  # Default RTSP port

        return host, port
    except Exception as e:
        logger.error(f"Failed to parse RTSP URL: {e}")
        return None, None


def check_rtsp_tcp_only(host, port):
    """
    Quick TCP-only check for RTSP port connectivity.
    Returns True if TCP port is reachable, False otherwise.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False


def check_rtsp_source_health():
    """
    Check if the RTSP source is actually providing valid video.

    IMPORTANT: This now uses ffprobe to verify actual video frames, not just TCP connectivity.
    This fixes the issue where TCP port is open but video is invalid (internet outage, camera freeze, etc.)

    Returns: 'healthy', 'unreachable', or 'unknown'
    """
    if not RTSP_SOURCE:
        logger.warning("RTSP_SOURCE not configured - skipping RTSP health check")
        return 'unknown'

    if not RTSP_CHECK_ENABLED:
        return 'unknown'

    host, port = parse_rtsp_url(RTSP_SOURCE)
    if not host:
        return 'unknown'

    # Mask credentials in log output
    safe_url = RTSP_SOURCE
    if '@' in safe_url:
        parts = safe_url.split('@')
        protocol = parts[0].split('://')[0]
        safe_url = f"{protocol}://***@{parts[1]}"

    logger.info(f"Checking RTSP source: {safe_url} ({host}:{port})")

    # Step 1: Quick TCP check first
    if not check_rtsp_tcp_only(host, port):
        logger.warning(f"RTSP source UNREACHABLE - TCP connection to {host}:{port} failed")
        return 'unreachable'

    logger.debug(f"TCP connection to {host}:{port} succeeded, now validating video stream...")

    # Step 2: Use ffprobe to validate actual video frames (critical for catching "TCP up but no video" scenarios)
    ffprobe_status = check_rtsp_with_ffprobe()
    if ffprobe_status == 'healthy':
        logger.info(f"RTSP source HEALTHY - TCP connected AND video stream validated")
        return 'healthy'
    elif ffprobe_status == 'unreachable':
        logger.warning(f"RTSP source UNHEALTHY - TCP port open but NO VALID VIDEO (camera freeze, network issue, etc.)")
        return 'unreachable'
    else:
        # ffprobe not available or unknown error - fall back to TCP-only result
        logger.info(f"RTSP source TCP HEALTHY (ffprobe unavailable for video validation)")
        return 'healthy'


def is_fallback_mode():
    """
    Check if VantageCam is currently in fallback mode (showing "We'll Be Right Back").
    In fallback mode, the watchdog should NOT try to restart FFmpeg since start.sh is handling it.
    """
    try:
        if os.path.exists(STREAM_MODE_FILE):
            with open(STREAM_MODE_FILE, 'r') as f:
                mode = f.read().strip()
                return mode == "fallback"
    except:
        pass
    return False


def check_rtsp_with_ffprobe():
    """
    Validate RTSP stream by checking for actual video frames using ffprobe.
    This catches scenarios where TCP port is open but no valid video is available.

    Returns: 'healthy', 'unreachable', or 'unknown'
    """
    if not RTSP_SOURCE:
        return 'unknown'

    try:
        # Use ffprobe with a short timeout to test RTSP stream
        # This validates we can actually READ video frames, not just connect
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-rtsp_transport', 'tcp',
             '-timeout', '8000000',  # 8 seconds in microseconds
             '-i', RTSP_SOURCE,
             '-show_entries', 'stream=codec_type,codec_name,width,height',
             '-of', 'json'],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode == 0:
            # Parse output to verify we got video stream info
            try:
                data = json.loads(result.stdout)
                streams = data.get('streams', [])
                video_streams = [s for s in streams if s.get('codec_type') == 'video']

                if video_streams:
                    v = video_streams[0]
                    codec = v.get('codec_name', 'unknown')
                    width = v.get('width', '?')
                    height = v.get('height', '?')
                    logger.info(f"RTSP ffprobe: HEALTHY - Video stream found ({codec} {width}x{height})")
                    return 'healthy'
                else:
                    logger.warning(f"RTSP ffprobe: UNREACHABLE - Connected but NO VIDEO STREAM in response")
                    return 'unreachable'
            except json.JSONDecodeError:
                logger.warning("RTSP ffprobe: UNREACHABLE - Invalid JSON response")
                return 'unreachable'
        else:
            # ffprobe failed - extract meaningful error message
            stderr = result.stderr.strip() if result.stderr else "No error message"
            # Truncate long error messages
            if len(stderr) > 200:
                stderr = stderr[:200] + "..."
            logger.warning(f"RTSP ffprobe: UNREACHABLE - ffprobe exit code {result.returncode}")
            logger.debug(f"ffprobe error: {stderr}")
            return 'unreachable'

    except subprocess.TimeoutExpired:
        logger.warning("RTSP ffprobe: UNREACHABLE - Timed out after 15s (no video response)")
        return 'unreachable'
    except FileNotFoundError:
        logger.debug("ffprobe not available, cannot validate video stream")
        return 'unknown'
    except Exception as e:
        logger.error(f"RTSP ffprobe error: {e}")
        return 'unknown'

# ==============================================================================
#  DISCORD NOTIFICATIONS
# ==============================================================================

def send_discord_alert(title, message, color=16711680, mention_user=True):
    """
    Send an alert to Discord via webhook.
    color: 16711680 = red, 16776960 = yellow, 65280 = green
    """
    if not DISCORD_WEBHOOK_URL:
        return False

    try:
        # Build the message content
        content = ""
        if mention_user and DISCORD_USER_ID:
            content = f"<@{DISCORD_USER_ID}>"

        embed = {
            "title": title,
            "description": message,
            "color": color,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "VantageCam Watchdog"}
        }

        payload = {
            "content": content,
            "embeds": [embed]
        }

        data = json.dumps(payload).encode()
        req = Request(DISCORD_WEBHOOK_URL, data=data, method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('User-Agent', 'VantageCam-Watchdog/2.9.0')

        with urlopen(req, timeout=10) as response:
            return response.status == 204

    except Exception as e:
        logger.error(f"Failed to send Discord alert: {e}")
        return False


def alert_credential_error(error_type, details):
    """Send Discord alert for credential/API errors"""
    messages = {
        'token_expired': {
            'title': '[ERROR] YouTube API Token Expired',
            'message': (
                '**Your YouTube refresh token has expired!**\n\n'
                'The watchdog cannot set streams to PUBLIC until you regenerate it.\n\n'
                '**To fix:**\n'
                '1. Go to [OAuth Playground](https://developers.google.com/oauthplayground)\n'
                '2. Use your OAuth credentials\n'
                '3. Authorize scope: `https://www.googleapis.com/auth/youtube`\n'
                '4. Copy the new Refresh Token\n'
                '5. Update `YOUTUBE_REFRESH_TOKEN` in your container\n\n'
                f'```{details}```'
            )
        },
        'invalid_credentials': {
            'title': '[ERROR] YouTube API Credentials Invalid',
            'message': (
                '**Your YouTube API credentials are invalid!**\n\n'
                'Check that `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` are correct.\n\n'
                f'```{details}```'
            )
        },
        'insufficient_scope': {
            'title': '[WARNING] YouTube API Scope Error',
            'message': (
                '**Your refresh token has insufficient permissions!**\n\n'
                'The token was generated with read-only scope.\n\n'
                '**To fix:**\n'
                '1. Go to [OAuth Playground](https://developers.google.com/oauthplayground)\n'
                '2. Enter scope manually: `https://www.googleapis.com/auth/youtube`\n'
                '3. Regenerate and update your refresh token\n\n'
                f'```{details}```'
            )
        },
        'api_error': {
            'title': '[ERROR] YouTube API Error',
            'message': f'**An error occurred with the YouTube API:**\n\n```{details}```'
        },
        'stream_offline': {
            'title': '[WARNING] Stream Went Offline',
            'message': (
                '**Your YouTube stream went offline!**\n\n'
                'The watchdog is attempting to recover the stream.\n\n'
                f'```{details}```'
            )
        },
        'stream_recovered': {
            'title': '[OK] Stream Recovered',
            'message': (
                '**Your YouTube stream is back online!**\n\n'
                f'```{details}```'
            )
        },
        'rtsp_down': {
            'title': '[ERROR] RTSP Source Unreachable',
            'message': (
                '**The camera RTSP source is unreachable!**\n\n'
                'The watchdog will wait for the source to come back online before attempting recovery.\n\n'
                f'```{details}```'
            )
        },
        'rtsp_recovered': {
            'title': '[OK] RTSP Source Recovered',
            'message': (
                '**The camera RTSP source is back online!**\n\n'
                'Proceeding with stream recovery.\n\n'
                f'```{details}```'
            )
        }
    }

    msg = messages.get(error_type, {
        'title': '[ALERT] VantageCam Alert',
        'message': details
    })

    # Use green color for recovery, red for errors, orange for warnings
    color = 65280 if 'recovered' in error_type else (16776960 if 'scope' in error_type or error_type == 'stream_offline' else 16711680)

    send_discord_alert(msg['title'], msg['message'], color=color)

# ==============================================================================
#  STATE MANAGEMENT
# ==============================================================================

class WatchdogState:
    """Persistent state for the watchdog"""
    def __init__(self):
        self.attempt = 0
        self.last_healthy = None
        self.last_restart = None
        self.total_restarts = 0
        self.rtsp_was_down = False  # Track RTSP state for alerting
        self.load()

    def load(self):
        """Load state from disk"""
        try:
            if os.path.exists(WATCHDOG_STATE_FILE):
                with open(WATCHDOG_STATE_FILE, 'r') as f:
                    data = json.load(f)
                    self.attempt = data.get('attempt', 0)
                    self.total_restarts = data.get('total_restarts', 0)
                    if data.get('last_healthy'):
                        self.last_healthy = datetime.fromisoformat(data['last_healthy'])
                    if data.get('last_restart'):
                        self.last_restart = datetime.fromisoformat(data['last_restart'])
        except Exception as e:
            logger.warning(f"Could not load state: {e}")

    def save(self):
        """Save state to disk"""
        try:
            data = {
                'attempt': self.attempt,
                'total_restarts': self.total_restarts,
                'last_healthy': self.last_healthy.isoformat() if self.last_healthy else None,
                'last_restart': self.last_restart.isoformat() if self.last_restart else None
            }
            with open(WATCHDOG_STATE_FILE, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Could not save state: {e}")

    def reset_backoff(self):
        """Reset backoff counter after stable connection"""
        self.attempt = 0
        self.last_healthy = datetime.now()
        self.save()

    def increment_attempt(self):
        """Increment attempt counter for backoff"""
        self.attempt += 1
        self.total_restarts += 1
        self.last_restart = datetime.now()
        self.save()

state = WatchdogState()

# ==============================================================================
#  YOUTUBE API FUNCTIONS
# ==============================================================================

def get_access_token():
    """Get a fresh access token using the refresh token"""
    if not all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN]):
        logger.warning("YouTube API credentials not configured - cannot set stream to PUBLIC")
        return None

    try:
        data = urlencode({
            'client_id': YOUTUBE_CLIENT_ID,
            'client_secret': YOUTUBE_CLIENT_SECRET,
            'refresh_token': YOUTUBE_REFRESH_TOKEN,
            'grant_type': 'refresh_token'
        }).encode()

        req = Request('https://oauth2.googleapis.com/token', data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')

        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            return result.get('access_token')

    except HTTPError as e:
        error_body = e.read().decode()
        try:
            error_data = json.loads(error_body)
            error_desc = error_data.get('error_description', error_data.get('error', 'Unknown error'))
        except:
            error_desc = error_body

        if e.code == 400:
            if 'invalid_grant' in error_body or 'Token has been expired' in error_body:
                logger.error("YouTube API: Refresh token EXPIRED! Regenerate it in OAuth Playground.")
                alert_credential_error('token_expired', error_desc)
            elif 'invalid_client' in error_body:
                logger.error("YouTube API: Invalid client credentials! Check CLIENT_ID and CLIENT_SECRET.")
                alert_credential_error('invalid_credentials', error_desc)
            else:
                logger.error(f"YouTube API: Bad request - {error_desc}")
                alert_credential_error('api_error', error_desc)
        elif e.code == 401:
            logger.error("YouTube API: Unauthorized - credentials are invalid!")
            alert_credential_error('invalid_credentials', error_desc)
        else:
            logger.error(f"YouTube API: HTTP {e.code} - {error_desc}")
            alert_credential_error('api_error', f"HTTP {e.code}: {error_desc}")
        return None

    except Exception as e:
        logger.error(f"Failed to get access token: {e}")
        return None


def get_active_broadcast(access_token):
    """Get the currently active broadcast ID and its privacy status"""
    try:
        params = urlencode({
            'part': 'id,status,snippet',
            'broadcastStatus': 'active',
            'broadcastType': 'all'
        })

        req = Request(f'https://www.googleapis.com/youtube/v3/liveBroadcasts?{params}')
        req.add_header('Authorization', f'Bearer {access_token}')

        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())

            if result.get('items'):
                broadcast = result['items'][0]
                return {
                    'id': broadcast['id'],
                    'title': broadcast['snippet']['title'],
                    'privacy': broadcast['status']['privacyStatus']
                }
        return None

    except Exception as e:
        logger.error(f"Failed to get active broadcast: {e}")
        return None


def set_broadcast_public(access_token, broadcast_id, title):
    """Set a broadcast to PUBLIC visibility"""
    try:
        # Only update the status - don't touch snippet fields on active broadcasts
        data = json.dumps({
            'id': broadcast_id,
            'status': {
                'privacyStatus': 'public'
            }
        }).encode()

        params = urlencode({'part': 'status'})
        req = Request(
            f'https://www.googleapis.com/youtube/v3/liveBroadcasts?{params}',
            data=data,
            method='PUT'
        )
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', 'application/json')

        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            new_privacy = result.get('status', {}).get('privacyStatus')
            logger.info(f"Broadcast visibility updated to: {new_privacy}")
            return new_privacy == 'public'

    except HTTPError as e:
        error_body = e.read().decode()
        try:
            error_data = json.loads(error_body)
            error_msg = error_data.get('error', {}).get('message', error_body)
            error_reason = error_data.get('error', {}).get('errors', [{}])[0].get('reason', '')
        except:
            error_msg = error_body
            error_reason = ''

        if e.code == 401:
            logger.error("YouTube API: Access token expired or invalid!")
            alert_credential_error('token_expired', error_msg)
        elif e.code == 403:
            if 'insufficientPermissions' in error_body or 'ACCESS_TOKEN_SCOPE_INSUFFICIENT' in error_body:
                logger.error("YouTube API: Insufficient scope! Regenerate token with full youtube scope.")
                alert_credential_error('insufficient_scope', error_msg)
            else:
                logger.error(f"YouTube API: Forbidden - {error_msg}")
                alert_credential_error('api_error', f"403 Forbidden: {error_msg}")
        else:
            logger.error(f"Failed to set broadcast public: {e.code} - {error_msg}")
            alert_credential_error('api_error', f"HTTP {e.code}: {error_msg}")
        return False

    except Exception as e:
        logger.error(f"Failed to set broadcast public: {e}")
        return False


def ensure_broadcast_public():
    """Check if broadcast is public and set it if not"""
    access_token = get_access_token()
    if not access_token:
        return False

    broadcast = get_active_broadcast(access_token)
    if not broadcast:
        logger.warning("No active broadcast found")
        return False

    logger.info(f"Active broadcast: '{broadcast['title']}' - Privacy: {broadcast['privacy']}")

    if broadcast['privacy'] == 'public':
        logger.info("Broadcast is already PUBLIC")
        return True

    logger.info(f"Broadcast is {broadcast['privacy'].upper()}, changing to PUBLIC...")
    success = set_broadcast_public(access_token, broadcast['id'], broadcast['title'])

    if success:
        send_discord_alert(
            "[OK] Broadcast Set to PUBLIC",
            f"**{broadcast['title']}**\n\nVisibility changed from `{broadcast['privacy']}` to `public`.",
            color=65280,  # Green
            mention_user=False
        )

    return success

# ==============================================================================
#  STREAM STATUS CHECKING (IMPROVED)
# ==============================================================================

def check_stream_status():
    """
    Check if the stream is live by querying the PHP status endpoint.
    Returns: 'live', 'offline', or 'error'

    v2.8.1: Now logs full response for debugging
    """
    if not STATUS_URL:
        logger.warning("WATCHDOG_STATUS_URL not configured")
        return 'error'

    try:
        logger.debug(f"Checking status URL: {STATUS_URL}")
        req = Request(STATUS_URL)
        req.add_header('User-Agent', 'VantageCam-Watchdog/2.9.0')

        with urlopen(req, timeout=15) as response:
            raw_data = response.read().decode()
            data = json.loads(raw_data)
            status = data.get('status', 'unknown')

            # Log the full response for debugging
            if VERBOSE_LOGGING:
                viewers = data.get('viewers', 'N/A')
                title = data.get('title', 'N/A')
                logger.debug(f"Status API response: status={status}, viewers={viewers}, title={title}")

            if status == 'live':
                viewers = data.get('viewers', 0)
                logger.info(f"Stream is LIVE with {viewers} viewers")
                return 'live'
            elif status == 'offline':
                logger.debug("Stream status: OFFLINE")
                return 'offline'
            elif status == 'error':
                error_msg = data.get('message', 'Unknown error')
                logger.warning(f"Status API returned error: {error_msg}")
                return 'error'
            else:
                logger.warning(f"Unknown status from API: {status} (full response: {raw_data[:200]})")
                return 'error'

    except HTTPError as e:
        logger.error(f"HTTP error checking status: {e.code} - URL: {STATUS_URL}")
        return 'error'
    except URLError as e:
        logger.error(f"URL error checking status: {e.reason} - URL: {STATUS_URL}")
        return 'error'
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from status endpoint: {e}")
        return 'error'
    except Exception as e:
        logger.error(f"Error checking stream status: {e}")
        return 'error'


def check_ffmpeg_progress():
    """
    Check if FFmpeg is actually producing output by monitoring the progress file.
    Returns True if FFmpeg appears healthy, False if stalled, None if not available.
    """
    try:
        if not os.path.exists(PROGRESS_FILE):
            # Progress logging may be disabled - this is expected
            return None

        # Check file age
        file_age = time.time() - os.path.getmtime(PROGRESS_FILE)
        if file_age > 60:  # Progress file older than 60 seconds
            logger.warning(f"Progress file is {file_age:.0f}s old - FFmpeg may be stalled")
            return False

        # Check frame count advancement
        with open(PROGRESS_FILE, 'r') as f:
            content = f.read()

        # Look for frame count
        for line in content.split('\n'):
            if line.startswith('frame='):
                frame = int(line.split('=')[1])

                # Compare to last known frame
                last_frame_file = "/tmp/watchdog_last_frame"
                last_frame = 0
                if os.path.exists(last_frame_file):
                    with open(last_frame_file, 'r') as f:
                        try:
                            last_frame = int(f.read().strip())
                        except:
                            pass

                # Save current frame
                with open(last_frame_file, 'w') as f:
                    f.write(str(frame))

                # If frame hasn't advanced and file is > 10s old, stalled
                if frame == last_frame and file_age > 10:
                    logger.warning(f"FFmpeg stalled at frame {frame}")
                    return False

                logger.debug(f"FFmpeg progress: frame={frame}, age={file_age:.1f}s")
                return True

        return True  # Progress file exists but no frame info yet

    except Exception as e:
        logger.error(f"Error checking FFmpeg progress: {e}")
        return True  # Don't trigger restart on check errors

# ==============================================================================
#  STREAM RESTART FUNCTIONS
# ==============================================================================

def get_ffmpeg_pid():
    """Get the FFmpeg PID from the PID file"""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                return int(f.read().strip())
    except (ValueError, FileNotFoundError):
        pass
    return None


def stop_ffmpeg_gracefully():
    """
    Stop FFmpeg gracefully using SIGINT first, then SIGTERM, then SIGKILL.
    """
    pid = get_ffmpeg_pid()
    if not pid:
        logger.warning("No FFmpeg PID found")
        # Try to find FFmpeg by name
        try:
            result = subprocess.run(['pgrep', '-f', 'ffmpeg.*rtmp'], capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for p in pids:
                    try:
                        os.kill(int(p), signal.SIGINT)
                    except:
                        pass
                logger.info(f"Sent SIGINT to FFmpeg processes: {pids}")
                time.sleep(3)
        except:
            pass
        return

    logger.info(f"Stopping FFmpeg (PID: {pid}) gracefully...")

    try:
        # Step 1: SIGINT (like pressing 'q')
        os.kill(pid, signal.SIGINT)
        logger.info("Sent SIGINT to FFmpeg")

        # Wait up to 5 seconds for graceful shutdown
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)  # Check if still running
            except ProcessLookupError:
                logger.info("FFmpeg stopped gracefully")
                return

        # Step 2: SIGTERM
        logger.warning("FFmpeg didn't stop, sending SIGTERM...")
        os.kill(pid, signal.SIGTERM)

        # Wait up to 3 more seconds
        for _ in range(6):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                logger.info("FFmpeg stopped after SIGTERM")
                return

        # Step 3: SIGKILL (last resort)
        logger.warning("FFmpeg still running, sending SIGKILL...")
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
        logger.info("FFmpeg killed")

    except ProcessLookupError:
        logger.info("FFmpeg already stopped")
    except Exception as e:
        logger.error(f"Error stopping FFmpeg: {e}")


def get_backoff_delay():
    """
    Calculate backoff delay with exponential increase and jitter.
    """
    base_delay = INITIAL_DELAY * (2 ** state.attempt)

    # Add jitter (+/-30%)
    jitter = base_delay * 0.3
    delay = base_delay + random.uniform(-jitter, jitter)

    # Cap at max delay
    delay = min(delay, MAX_DELAY)

    return int(delay)


def wait_for_rtsp_source(max_wait=300):
    """
    Wait for RTSP source to become available.
    Returns True if source came back, False if timed out.

    v2.8.1: New function to wait for camera to come back online
    """
    if not RTSP_SOURCE or not RTSP_CHECK_ENABLED:
        return True

    logger.info(f"Waiting up to {max_wait}s for RTSP source to become available...")
    start_time = time.time()
    check_count = 0

    while (time.time() - start_time) < max_wait:
        check_count += 1

        # Try TCP check first (faster)
        tcp_status = check_rtsp_source_health()

        if tcp_status == 'healthy':
            # Double-check with ffprobe if TCP succeeded
            ffprobe_status = check_rtsp_with_ffprobe()
            if ffprobe_status == 'healthy':
                logger.info(f"RTSP source recovered after {check_count} checks ({time.time() - start_time:.0f}s)")

                # Alert if it was previously down
                if state.rtsp_was_down:
                    alert_credential_error('rtsp_recovered',
                        f"Camera RTSP source is back online after {time.time() - start_time:.0f} seconds")
                    state.rtsp_was_down = False

                return True
            elif ffprobe_status == 'unknown':
                # ffprobe not available, trust TCP check
                logger.info(f"RTSP source recovered (TCP check) after {check_count} checks")
                if state.rtsp_was_down:
                    alert_credential_error('rtsp_recovered',
                        f"Camera RTSP source is back online after {time.time() - start_time:.0f} seconds")
                    state.rtsp_was_down = False
                return True

        # Wait 10 seconds between checks
        elapsed = time.time() - start_time
        logger.info(f"RTSP source still unreachable (check #{check_count}, {elapsed:.0f}s elapsed)")
        time.sleep(10)

    logger.warning(f"RTSP source did not recover within {max_wait}s")
    return False


def restart_stream():
    """
    Initiate stream restart by stopping FFmpeg and letting start.sh restart it.

    v2.8.1: Now checks RTSP source before attempting restart
    """
    logger.info("=" * 50)
    logger.info("INITIATING STREAM RESTART")
    logger.info("=" * 50)

    state.increment_attempt()
    logger.info(f"Attempt #{state.attempt} - Total restarts: {state.total_restarts}")

    # Calculate backoff delay
    delay = get_backoff_delay()
    logger.info(f"Calculated backoff delay: {delay} seconds")

    # NEW: Check RTSP source health before restarting
    if RTSP_CHECK_ENABLED and RTSP_SOURCE:
        logger.info("Checking RTSP source health before restart...")
        rtsp_status = check_rtsp_source_health()

        if rtsp_status == 'unreachable':
            logger.warning("RTSP source is unreachable - waiting for it to come back...")

            # Send alert if this is first detection
            if not state.rtsp_was_down:
                safe_url = RTSP_SOURCE
                if '@' in safe_url:
                    parts = safe_url.split('@')
                    protocol = parts[0].split('://')[0]
                    safe_url = f"{protocol}://***@{parts[1]}"

                alert_credential_error('rtsp_down',
                    f"RTSP Source: {safe_url}\n"
                    f"The watchdog will wait for the camera to come back online.")
                state.rtsp_was_down = True

            # Wait for RTSP to come back (up to 5 minutes)
            if not wait_for_rtsp_source(300):
                logger.warning("RTSP source still unreachable - will retry on next loop")
                return
        else:
            logger.info("RTSP source is healthy, proceeding with restart")

    # Stop FFmpeg
    stop_ffmpeg_gracefully()

    # Wait for backoff period
    logger.info(f"Waiting {delay} seconds before allowing FFmpeg restart...")
    time.sleep(delay)

    # FFmpeg will auto-restart via start.sh loop
    logger.info("FFmpeg should auto-restart via start.sh loop")
    logger.info("=" * 50)


def verify_stream_recovery():
    """
    Wait for stream to come back online and verify stability.
    Returns True if stream recovered successfully, False otherwise.

    v2.8.1: Extended verification window (default 120s instead of 60s)
    """
    logger.info("Waiting 20 seconds for stream to stabilize...")
    time.sleep(20)

    max_wait = VERIFICATION_TIMEOUT
    logger.info(f"Verifying stream status for up to {max_wait} seconds...")
    stable_count = 0
    check_count = 0
    max_checks = max_wait // 5  # 5 second intervals

    while check_count < max_checks:
        status = check_stream_status()

        if status == 'live':
            stable_count += 1
            logger.info(f"Stream LIVE (stable count: {stable_count}/{STABILITY_THRESHOLD // 5})")

            # Need 30 seconds of stable live status
            if stable_count * 5 >= STABILITY_THRESHOLD:
                logger.info("[OK] Stream verified stable!")
                return True
        else:
            stable_count = 0  # Reset if not live
            logger.info(f"Stream status: {status}")

        check_count += 1
        time.sleep(5)

    logger.warning("Stream did not recover within verification window")
    return False


def validate_youtube_credentials():
    """
    Validate YouTube API credentials on startup.
    Returns True if valid or not configured, False if configured but invalid.
    """
    if not all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN]):
        logger.info("YouTube API: Not configured (auto-PUBLIC disabled)")
        return True  # Not configured is OK - feature is optional

    logger.info("YouTube API: Validating credentials...")

    token = get_access_token()
    if not token:
        logger.error("YouTube API: CREDENTIAL VALIDATION FAILED!")
        logger.error("YouTube API: The watchdog will continue but cannot set streams to PUBLIC.")
        logger.error("YouTube API: Check the errors above and fix your credentials.")
        return False

    logger.info("YouTube API: Credentials validated successfully!")
    return True


def validate_discord_webhook():
    """
    Validate Discord webhook on startup by sending a test message.
    """
    if not DISCORD_WEBHOOK_URL:
        logger.info("Discord Alerts: Not configured")
        return True

    logger.info("Discord Alerts: Testing webhook...")

    success = send_discord_alert(
        "VantageCam Watchdog Started",
        "The self-healing watchdog is now monitoring your stream.\n\n"
        f"**Configuration:**\n"
        f"- Startup delay: {STARTUP_DELAY}s\n"
        f"- Check interval: {CHECK_INTERVAL}s\n"
        f"- Verification timeout: {VERIFICATION_TIMEOUT}s\n"
        f"- RTSP health check: {'Enabled' if RTSP_CHECK_ENABLED else 'Disabled'}\n"
        f"- Verbose logging: {'Enabled' if VERBOSE_LOGGING else 'Disabled'}",
        color=65280,  # Green
        mention_user=False
    )

    if success:
        logger.info("Discord Alerts: Webhook validated successfully!")
    else:
        logger.warning("Discord Alerts: Could not send test message - check webhook URL")

    return success

# ==============================================================================
#  MAIN WATCHDOG LOOP
# ==============================================================================

def run_watchdog():
    """Main watchdog loop"""
    if not WATCHDOG_ENABLED:
        logger.info("Watchdog is DISABLED (WATCHDOG_ENABLED=false)")
        return

    if not STATUS_URL:
        logger.error("WATCHDOG_STATUS_URL not set - watchdog cannot function")
        return

    # Mask RTSP credentials for logging
    safe_rtsp = RTSP_SOURCE
    if RTSP_SOURCE and '@' in RTSP_SOURCE:
        parts = RTSP_SOURCE.split('@')
        protocol = parts[0].split('://')[0]
        safe_rtsp = f"{protocol}://***@{parts[1]}"

    logger.info("=" * 50)
    logger.info("VANTAGECAM SELF-HEALING WATCHDOG v2.9.0 STARTED")
    logger.info("=" * 50)
    logger.info(f"Status URL: {STATUS_URL}")
    logger.info(f"RTSP Source: {safe_rtsp or 'Not configured'}")
    logger.info(f"Check interval: {CHECK_INTERVAL}s")
    logger.info(f"Initial delay: {INITIAL_DELAY}s")
    logger.info(f"Max backoff delay: {MAX_DELAY}s")
    logger.info(f"Stability threshold: {STABILITY_THRESHOLD}s")
    logger.info(f"Verification timeout: {VERIFICATION_TIMEOUT}s")
    logger.info(f"Startup delay: {STARTUP_DELAY}s")
    logger.info(f"RTSP health check: {'Enabled' if RTSP_CHECK_ENABLED else 'Disabled'}")
    logger.info(f"Verbose logging: {'Enabled' if VERBOSE_LOGGING else 'Disabled'}")
    logger.info("=" * 50)

    # Validate Discord webhook first (so we can alert on credential errors)
    validate_discord_webhook()

    # Validate YouTube credentials
    validate_youtube_credentials()

    # Check RTSP source at startup
    if RTSP_CHECK_ENABLED and RTSP_SOURCE:
        logger.info("Performing initial RTSP source health check...")
        rtsp_status = check_rtsp_source_health()
        logger.info(f"Initial RTSP status: {rtsp_status}")

    logger.info("=" * 50)

    # Initial delay to let everything start up
    logger.info(f"Waiting {STARTUP_DELAY} seconds for initial stream startup...")
    time.sleep(STARTUP_DELAY)

    consecutive_offline = 0
    last_public_check = datetime.now() - timedelta(hours=1)  # Force initial check
    alerted_offline = False  # Track if we've already sent offline alert

    while True:
        try:
            status = check_stream_status()

            if status == 'live':
                # Stream is healthy
                if consecutive_offline > 0:
                    logger.info(f"Stream recovered! Was offline for {consecutive_offline} checks")
                    if alerted_offline:
                        alert_credential_error('stream_recovered',
                            f"Stream back online after {consecutive_offline} offline checks.\n"
                            f"Total restarts this session: {state.total_restarts}")
                        alerted_offline = False
                consecutive_offline = 0

                # Check if we've been stable long enough to reset backoff
                if state.last_healthy:
                    time_since_healthy = (datetime.now() - state.last_healthy).total_seconds()
                    if time_since_healthy < STABILITY_THRESHOLD and state.attempt > 0:
                        pass  # Still in recovery validation
                else:
                    state.reset_backoff()

                if state.attempt > 0:
                    state.reset_backoff()
                    logger.info("Backoff counter reset after stable connection")

                # Periodically check/set broadcast to PUBLIC (every 5 minutes while live)
                if (datetime.now() - last_public_check).total_seconds() > 300:
                    ensure_broadcast_public()
                    last_public_check = datetime.now()

            elif status == 'offline':
                consecutive_offline += 1
                logger.warning(f"Stream OFFLINE (consecutive: {consecutive_offline})")

                # Require 2 consecutive offline checks before restart (to avoid false positives)
                if consecutive_offline >= 2:
                    # Check if we're in fallback mode - if so, start.sh is handling recovery
                    if is_fallback_mode():
                        logger.info("In fallback mode - start.sh is handling camera recovery, skipping watchdog restart")
                        consecutive_offline = 0  # Reset counter since this is expected
                        continue
                    
                    logger.warning("Stream confirmed OFFLINE - initiating recovery")

                    # Send Discord alert (only once per offline event)
                    if not alerted_offline:
                        alert_credential_error('stream_offline',
                            f"Stream went offline. Attempting recovery...\n"
                            f"Attempt #{state.attempt + 1}")
                        alerted_offline = True

                    restart_stream()

                    # Verify recovery
                    if verify_stream_recovery():
                        consecutive_offline = 0

                        # Ensure broadcast is PUBLIC after recovery
                        logger.info("Checking broadcast visibility after recovery...")
                        time.sleep(10)  # Give YouTube a moment
                        ensure_broadcast_public()
                        last_public_check = datetime.now()

                        # Send recovery alert
                        alert_credential_error('stream_recovered',
                            f"Stream successfully recovered!\n"
                            f"Total restarts this session: {state.total_restarts}")
                        alerted_offline = False
                    else:
                        logger.warning("Recovery verification failed - will retry on next loop")

            else:  # status == 'error'
                # Don't restart on errors - could be network issue with status endpoint
                logger.warning("Status check returned error - will retry")

            # Also check FFmpeg progress as secondary health indicator
            progress_status = check_ffmpeg_progress()
            if status == 'live' and progress_status is False:
                logger.warning("FFmpeg progress check failed despite 'live' status - monitoring...")

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Watchdog stopped by user")
            break
        except Exception as e:
            logger.error(f"Watchdog error: {e}")
            time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    run_watchdog()