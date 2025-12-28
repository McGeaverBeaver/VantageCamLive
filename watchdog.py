#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VantageCam Self-Healing Watchdog
Monitors YouTube stream status and automatically recovers failed streams.
Also handles setting the broadcast to PUBLIC after recovery.
"""

import os
import sys
import time
import json
import signal
import random
import subprocess
import logging
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

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

# ==============================================================================
#  LOGGING SETUP
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [Watchdog] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode='a')
    ]
)
logger = logging.getLogger(__name__)

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
        req.add_header('User-Agent', 'VantageCam-Watchdog/1.0')
        
        with urlopen(req, timeout=10) as response:
            return response.status == 204
    
    except Exception as e:
        logger.error(f"Failed to send Discord alert: {e}")
        return False


def alert_credential_error(error_type, details):
    """Send Discord alert for credential/API errors"""
    messages = {
        'token_expired': {
            'title': '?? YouTube API Token Expired',
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
            'title': '?? YouTube API Credentials Invalid',
            'message': (
                '**Your YouTube API credentials are invalid!**\n\n'
                'Check that `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` are correct.\n\n'
                f'```{details}```'
            )
        },
        'insufficient_scope': {
            'title': '?? YouTube API Scope Error',
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
            'title': '?? YouTube API Error',
            'message': f'**An error occurred with the YouTube API:**\n\n```{details}```'
        },
        'stream_offline': {
            'title': '?? Stream Went Offline',
            'message': (
                '**Your YouTube stream went offline!**\n\n'
                'The watchdog is attempting to recover the stream.\n\n'
                f'```{details}```'
            )
        },
        'stream_recovered': {
            'title': '?? Stream Recovered',
            'message': (
                '**Your YouTube stream is back online!**\n\n'
                f'```{details}```'
            )
        }
    }
    
    msg = messages.get(error_type, {
        'title': '?? VantageCam Alert',
        'message': details
    })
    
    # Use green color for recovery, red for errors, orange for warnings
    color = 65280 if error_type == 'stream_recovered' else (16776960 if 'scope' in error_type or error_type == 'stream_offline' else 16711680)
    
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
            "?? Broadcast Set to PUBLIC",
            f"**{broadcast['title']}**\n\nVisibility changed from `{broadcast['privacy']}` to `public`.",
            color=65280,  # Green
            mention_user=False
        )
    
    return success

# ==============================================================================
#  STREAM STATUS CHECKING
# ==============================================================================

def check_stream_status():
    """
    Check if the stream is live by querying the PHP status endpoint.
    Returns: 'live', 'offline', or 'error'
    """
    if not STATUS_URL:
        logger.warning("WATCHDOG_STATUS_URL not configured")
        return 'error'
    
    try:
        req = Request(STATUS_URL)
        req.add_header('User-Agent', 'VantageCam-Watchdog/1.0')
        
        with urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            status = data.get('status', 'unknown')
            
            if status == 'live':
                viewers = data.get('viewers', 0)
                logger.debug(f"Stream is LIVE with {viewers} viewers")
                return 'live'
            elif status == 'offline':
                logger.debug("Stream is OFFLINE")
                return 'offline'
            else:
                logger.warning(f"Unknown status from API: {status}")
                return 'error'
    
    except HTTPError as e:
        logger.error(f"HTTP error checking status: {e.code}")
        return 'error'
    except URLError as e:
        logger.error(f"URL error checking status: {e.reason}")
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
    Returns True if FFmpeg appears healthy, False otherwise.
    """
    try:
        if not os.path.exists(PROGRESS_FILE):
            return False
        
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
        time.sleep(2)
        
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            logger.info("FFmpeg stopped after SIGTERM")
            return
        
        # Step 3: SIGKILL (last resort)
        logger.warning("FFmpeg still running, sending SIGKILL...")
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
        logger.info("Sent SIGKILL to FFmpeg")
        
    except ProcessLookupError:
        logger.info("FFmpeg already stopped")
    except Exception as e:
        logger.error(f"Error stopping FFmpeg: {e}")


def calculate_backoff_delay():
    """
    Calculate delay using exponential backoff with jitter.
    Formula: min(base * 2^attempt, max_delay) +/- 30% jitter
    """
    base_delay = INITIAL_DELAY
    delay = min(base_delay * (2 ** state.attempt), MAX_DELAY)
    
    # Add +/- 30% jitter
    jitter = delay * 0.3 * (random.random() * 2 - 1)
    final_delay = delay + jitter
    
    return max(5, int(final_delay))  # Minimum 5 seconds


def restart_stream():
    """
    Restart the stream by stopping FFmpeg and letting start.sh restart it.
    The start.sh script has a loop that automatically restarts FFmpeg when it exits.
    """
    logger.info("=" * 50)
    logger.info("INITIATING STREAM RESTART")
    logger.info("=" * 50)
    
    state.increment_attempt()
    delay = calculate_backoff_delay()
    
    logger.info(f"Attempt #{state.attempt} - Total restarts: {state.total_restarts}")
    logger.info(f"Calculated backoff delay: {delay} seconds")
    
    # Stop FFmpeg gracefully
    stop_ffmpeg_gracefully()
    
    # Wait before allowing restart
    logger.info(f"Waiting {delay} seconds before allowing FFmpeg restart...")
    time.sleep(delay)
    
    # Clear the progress file to reset monitoring
    try:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
        if os.path.exists("/tmp/watchdog_last_frame"):
            os.remove("/tmp/watchdog_last_frame")
    except:
        pass
    
    logger.info("FFmpeg should auto-restart via start.sh loop")
    logger.info("=" * 50)


def verify_stream_recovery():
    """
    Wait for stream to come back online and verify stability.
    Returns True if stream recovered successfully, False otherwise.
    """
    logger.info("Waiting 20 seconds for stream to stabilize...")
    time.sleep(20)
    
    logger.info("Verifying stream status for up to 60 seconds...")
    stable_count = 0
    check_count = 0
    max_checks = 12  # 60 seconds / 5 second intervals
    
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
            logger.warning(f"Stream status: {status}")
        
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
        "The self-healing watchdog is now monitoring your stream.",
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
    
    logger.info("=" * 50)
    logger.info("VANTAGECAM SELF-HEALING WATCHDOG STARTED")
    logger.info("=" * 50)
    logger.info(f"Status URL: {STATUS_URL}")
    logger.info(f"Check interval: {CHECK_INTERVAL}s")
    logger.info(f"Initial delay: {INITIAL_DELAY}s")
    logger.info(f"Max backoff delay: {MAX_DELAY}s")
    logger.info(f"Stability threshold: {STABILITY_THRESHOLD}s")
    logger.info("=" * 50)
    
    # Validate Discord webhook first (so we can alert on credential errors)
    validate_discord_webhook()
    
    # Validate YouTube credentials
    validate_youtube_credentials()
    
    logger.info("=" * 50)
    
    # Initial delay to let everything start up
    logger.info("Waiting 60 seconds for initial stream startup...")
    time.sleep(60)
    
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
            if status == 'live' and not check_ffmpeg_progress():
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