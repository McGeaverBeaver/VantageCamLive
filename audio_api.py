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
RESTREAMER_PID_FILE = "/config/youtube_restreamer.pid"
API_KEY = os.getenv("AUDIO_API_KEY")  # Read key from Docker Env

def get_audio_mode():
    try:
        with open(CONTROL_FILE, 'r') as f:
            mode = f.read().strip()
            return mode if mode in ['muted', 'unmuted'] else 'muted'
    except FileNotFoundError:
        return 'muted'

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
        if not self.check_auth():
            self.send_json({'error': 'Unauthorized'}, 401)
            return

        if self.path == '/audio/status':
            mode = get_audio_mode()
            self.send_json({
                'audio': mode,
                'muted': mode == 'muted'
            })
        elif self.path == '/health':
            self.send_json({'status': 'ok'})
        else:
            self.send_json({'error': 'Not found'}, 404)
    
    def do_POST(self):
        if not self.check_auth():
            self.send_json({'error': 'Unauthorized'}, 401)
            return

        if self.path == '/audio/mute':
            set_audio_mode('muted')
            self.send_json({'audio': 'muted', 'muted': True})
        elif self.path == '/audio/unmute':
            set_audio_mode('unmuted')
            self.send_json({'audio': 'unmuted', 'muted': False})
        elif self.path == '/audio/toggle':
            current = get_audio_mode()
            new_mode = 'unmuted' if current == 'muted' else 'muted'
            set_audio_mode(new_mode)
            self.send_json({'audio': new_mode, 'muted': new_mode == 'muted'})
        else:
            self.send_json({'error': 'Not found'}, 404)

if __name__ == '__main__':
    if not os.path.exists(CONTROL_FILE):
        with open(CONTROL_FILE, 'w') as f:
            f.write('muted')
    
    server = HTTPServer(('0.0.0.0', 9998), AudioControlHandler)
    print(f"[Audio API] Server started on port 9998")
    if API_KEY:
        print(f"[Audio API] Secured with API Key protection")
    else:
        print(f"[Audio API] WARNING: No API Key set. API is open to everyone.")
    server.serve_forever()