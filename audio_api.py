#!/usr/bin/env python3
"""
Simple Audio Control API Server (Secured)
Runs on port 9998 and provides endpoints to control YouTube stream audio
"""

import os
import signal
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

CONTROL_FILE = "/config/audio_mode"
VOLUME_FILE = "/config/music_volume"
RESTREAMER_PID_FILE = "/config/youtube_restreamer.pid"
API_KEY = os.getenv("AUDIO_API_KEY")  # Read key from Docker Env

def get_audio_mode():
    try:
        with open(CONTROL_FILE, 'r') as f:
            mode = f.read().strip()
            return mode if mode in ['muted', 'unmuted', 'music'] else 'muted'
    except FileNotFoundError:
        return 'muted'

def get_volume():
    try:
        with open(VOLUME_FILE, 'r') as f:
            vol = int(f.read().strip())
            return max(0, min(100, vol))  # Clamp 0-100
    except (FileNotFoundError, ValueError):
        return 50  # Default 50%

def set_volume(vol, restart=True):
    vol = max(0, min(100, int(vol)))  # Clamp 0-100
    with open(VOLUME_FILE, 'w') as f:
        f.write(str(vol))
    
    if restart:
        # Signal the restreamer to restart (only if in music mode)
        if get_audio_mode() == 'music':
            try:
                with open(RESTREAMER_PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGTERM)
                return True
            except (FileNotFoundError, ProcessLookupError, ValueError):
                return False
    return True

def set_audio_mode(mode):
    with open(CONTROL_FILE, 'w') as f:
        f.write(mode)
    
    # Signal the restreamer to restart
    try:
        with open(RESTREAMER_PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        return True
    except (FileNotFoundError, ProcessLookupError, ValueError):
        return False

class AudioControlHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging
    
    def check_auth(self):
        # If no key is set in Docker, allow everyone (Open Mode)
        if not API_KEY:
            return True
        
        # Check for Header "X-API-Key"
        auth_header = self.headers.get('X-API-Key')
        if auth_header == API_KEY:
            return True
            
        return False

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
                'music': mode == 'music',
                'volume': get_volume()
            })
        elif self.path == '/audio/volume':
            self.send_json({'volume': get_volume()})
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
            self.send_json({'audio': 'music', 'muted': False, 'music': True, 'volume': get_volume()})
        elif self.path == '/audio/volume':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ''
                data = json.loads(body) if body else {}
                vol = data.get('volume')
                if vol is None:
                    self.send_json({'error': 'Missing volume parameter'}, 400)
                    return
                set_volume(vol)
                self.send_json({'volume': get_volume(), 'restarted': get_audio_mode() == 'music'})
            except (json.JSONDecodeError, ValueError) as e:
                self.send_json({'error': f'Invalid request: {str(e)}'}, 400)
        else:
            self.send_json({'error': 'Not found'}, 404)

if __name__ == '__main__':
    if not os.path.exists(CONTROL_FILE):
        with open(CONTROL_FILE, 'w') as f:
            f.write('muted')
    
    server = HTTPServer(('0.0.0.0', 9998), AudioControlHandler)
    print("[Audio API] Server started on port 9998")
    if API_KEY:
        print("[Audio API] Secured with API Key protection")
    else:
        print("[Audio API] WARNING: No API Key set. API is open to everyone.")
    server.serve_forever()