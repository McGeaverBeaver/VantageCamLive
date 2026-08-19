#!/usr/bin/env python3
"""
Simple Audio Control API Server (Secured)
Runs on port 9998 and provides endpoints to control YouTube stream audio
"""

import os
import hmac
import time
import signal
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

CONTROL_FILE = "/config/audio_mode"
RESTREAMER_PID_FILE = "/config/youtube_restreamer.pid"
API_KEY = os.getenv("AUDIO_API_KEY")  # Read key from Docker Env

def get_audio_mode():
    try:
        with open(CONTROL_FILE, 'r') as f:
            mode = f.read().strip()
            return mode if mode in ['muted', 'unmuted', 'music'] else 'muted'
    except FileNotFoundError:
        return 'muted'

def _pid_is_ffmpeg(pid):
    """Guard against stale PID files / PID reuse before sending signals."""
    try:
        with open(f"/proc/{pid}/cmdline", 'rb') as f:
            return b'ffmpeg' in f.read()
    except OSError:
        return False

def set_audio_mode(mode):
    with open(CONTROL_FILE, 'w') as f:
        f.write(mode)

    # During a camera outage the PID belongs to the BRB keep-alive stream;
    # audio modes don't apply to it, so killing it would only interrupt the
    # broadcast. The saved mode is picked up when the camera stream returns.
    try:
        with open("/config/stream_mode", 'r') as f:
            if f.read().strip() == "fallback":
                return False
    except OSError:
        pass

    # Signal the restreamer to restart
    try:
        with open(RESTREAMER_PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        if not _pid_is_ffmpeg(pid):
            return False
        # Mark as a managed restart so the supervisor loop respawns in normal
        # mode immediately instead of detouring through the BRB fallback screen.
        with open("/config/restart_hold", 'w') as f:
            f.write(str(int(time.time()) + 2))
        os.kill(pid, signal.SIGTERM)
        return True
    except (FileNotFoundError, ProcessLookupError, ValueError, OSError):
        return False

class AudioControlHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def check_auth(self):
        # If no key is set in Docker, allow everyone (Open Mode)
        if not API_KEY:
            return True

        # Check for Header "X-API-Key" (constant-time comparison)
        auth_header = self.headers.get('X-API-Key') or ''
        return hmac.compare_digest(auth_header.encode(), API_KEY.encode())

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def do_GET(self):
        # Health check should always work without auth
        if self.path == '/health':
            self.send_json({'status': 'ok'})
            return

        if not self.check_auth():
            self.send_json({'error': 'Unauthorized'}, 401)
            return

        if self.path == '/audio/status':
            mode = get_audio_mode()
            self.send_json({
                'audio': mode,
                'muted': mode == 'muted',
                'music': mode == 'music'
            })
        else:
            self.send_json({'error': 'Not found'}, 404)
    
    def do_POST(self):
        if not self.check_auth():
            self.send_json({'error': 'Unauthorized'}, 401)
            return

        if self.path == '/audio/mute':
            set_audio_mode('muted')
            self.send_json({'audio': 'muted', 'muted': True, 'music': False})
        elif self.path == '/audio/unmute':
            set_audio_mode('unmuted')
            self.send_json({'audio': 'unmuted', 'muted': False, 'music': False})
        elif self.path == '/audio/toggle':
            current = get_audio_mode()
            new_mode = 'unmuted' if current == 'muted' else 'muted'
            set_audio_mode(new_mode)
            self.send_json({'audio': new_mode, 'muted': new_mode == 'muted', 'music': False})
        elif self.path == '/audio/music':
            set_audio_mode('music')
            self.send_json({'audio': 'music', 'muted': False, 'music': True})
        else:
            self.send_json({'error': 'Not found'}, 404)

if __name__ == '__main__':
    if not os.path.exists(CONTROL_FILE):
        with open(CONTROL_FILE, 'w') as f:
            f.write('muted')
    
    server = ThreadingHTTPServer(('0.0.0.0', 9998), AudioControlHandler)
    server.daemon_threads = True
    print("[Audio API] Server started on port 9998")
    if API_KEY:
        print("[Audio API] Secured with API Key protection")
    else:
        print("[Audio API] WARNING: No API Key set. API is open to everyone.")
    server.serve_forever()