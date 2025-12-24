#!/usr/bin/env python3
"""
Simple Audio Control API Server
Runs on port 9998 and provides endpoints to control YouTube stream audio
"""

import os
import signal
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

CONTROL_FILE = "/config/audio_mode"
RESTREAMER_PID_FILE = "/config/youtube_restreamer.pid"

def get_audio_mode():
    """Read current audio mode from control file"""
    try:
        with open(CONTROL_FILE, 'r') as f:
            mode = f.read().strip()
            return mode if mode in ['muted', 'unmuted'] else 'muted'
    except FileNotFoundError:
        return 'muted'

def set_audio_mode(mode):
    """Write audio mode to control file and restart restreamer"""
    with open(CONTROL_FILE, 'w') as f:
        f.write(mode)
    
    # Signal the restreamer to restart by killing its ffmpeg
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
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def do_GET(self):
        if self.path == '/audio/status':
            mode = get_audio_mode()
            self.send_json({
                'audio': mode,
                'muted': mode == 'muted'
            })
        elif self.path == '/health':
            self.send_json({'status': 'ok'})
        elif self.path == '/':
            self.send_json({
                'endpoints': {
                    'GET /audio/status': 'Get current audio mode',
                    'POST /audio/mute': 'Switch to silent audio',
                    'POST /audio/unmute': 'Switch to camera audio',
                    'POST /audio/toggle': 'Toggle audio mode',
                    'GET /health': 'Health check'
                }
            })
        else:
            self.send_json({'error': 'Not found'}, 404)
    
    def do_POST(self):
        if self.path == '/audio/mute':
            set_audio_mode('muted')
            self.send_json({
                'audio': 'muted',
                'muted': True,
                'message': 'Audio muted. Restreamer restarting...'
            })
        elif self.path == '/audio/unmute':
            set_audio_mode('unmuted')
            self.send_json({
                'audio': 'unmuted',
                'muted': False,
                'message': 'Audio unmuted. Restreamer restarting...'
            })
        elif self.path == '/audio/toggle':
            current = get_audio_mode()
            new_mode = 'unmuted' if current == 'muted' else 'muted'
            set_audio_mode(new_mode)
            self.send_json({
                'audio': new_mode,
                'muted': new_mode == 'muted',
                'message': f'Audio {"muted" if new_mode == "muted" else "unmuted"}. Restreamer restarting...'
            })
        else:
            self.send_json({'error': 'Not found'}, 404)
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

if __name__ == '__main__':
    if not os.path.exists(CONTROL_FILE):
        with open(CONTROL_FILE, 'w') as f:
            f.write('muted')
    
    server = HTTPServer(('0.0.0.0', 9998), AudioControlHandler)
    print(f"[Audio API] Server started on port 9998")
    print(f"[Audio API] Current mode: {get_audio_mode()}")
    server.serve_forever()