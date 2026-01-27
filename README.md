# VantageCam Live v2.8.5

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docker Build](https://github.com/McGeaverBeaver/VantageCamLive/actions/workflows/docker-build.yml/badge.svg)](https://github.com/McGeaverBeaver/VantageCamLive/actions/workflows/docker-build.yml)

**Open-Source Automated Live Stream Broadcaster with Weather, Smart Alerts & Self-Healing**

> 📺 **See it in action:** [https://simcoelocal.com/](https://simcoelocal.com/)

Transform a standard security camera feed into a professional broadcast without the hassle. VantageCam Live runs entirely in Docker and handles all the heavy lifting for you:

- 🎬 **Automated Production** — Overlays real-time weather, government warnings, and rotating sponsor logos
- 📐 **Universal Fit** — Smart scaling fixes aspect ratios (no more black bars!)
- 🔄 **Set & Forget** — Runs 24/7 with self-healing assets and automatic recovery
- 🛡️ **Self-Healing** — Detects failures and auto-recovers with Discord notifications
- 📺 **Never Goes Offline** — "We'll Be Right Back" screen keeps YouTube alive during camera outages

---

## 📋 Table of Contents

- [Key Features](#-key-features)
- [What's New in v2.8.5](#-whats-new-in-v285)
- [Getting Started](#-getting-started)
- [Docker Compose](#-docker-compose)
- [Direct-to-YouTube Mode](#-direct-to-youtube-mode)
- [Fallback Mode (BRB Screen)](#-fallback-mode-brb-screen)
- [Self-Healing Watchdog](#-self-healing-watchdog)
- [Discord Notifications](#-discord-notifications)
- [YouTube API Setup Guide](#-youtube-api-setup-guide)
- [Alert System](#-alert-system)
- [Sponsor Management](#-sponsor-management)
- [Advanced Configuration](#️-advanced-configuration)
- [Audio Control API](#️-audio-control-api)
- [Troubleshooting](#-troubleshooting)
- [Changelog](#-changelog)

---

## ⭐ Key Features

### Video & Encoding
- **Resolution Unlocked** — Stream in 1440p (2K) by default, or configure for 1080p/4K
- **Smart Scaling** — `SCALING_MODE=fill` zooms and crops 4:3 cameras to fill 16:9 frames
- **Flexible Encoding** — Hardware (Intel QuickSync/VAAPI) or software (x264) encoding
- **Auto-Fallback** — Automatically switches to software mode if VAAPI fails

### Weather & Alerts
- **Live Weather Overlay** — Real-time updates powered by Open-Meteo
- **Smart Alert System** — Full Environment Canada + NWS alert hierarchy
- **Flashing Warnings** — Extreme weather alerts flash red to grab attention
- **Self-Healing Assets** — Weather icons auto-download/repair on boot

### Streaming
- **Direct-to-YouTube Mode** — Single FFmpeg pipeline saves CPU/RAM when no local preview needed
- **Dynamic Sponsors** — Drag-and-drop logos with automatic Day/Night rotation
- **Audio Control API** — Remote mute/unmute/music via HTTP endpoints
- **Music Streaming** — Play background music from MP3 playlist instead of camera audio

### Reliability *(v2.8+)*
- **Self-Healing Watchdog** — Auto-detects failures and recovers streams
- **"We'll Be Right Back" Mode** — Keeps YouTube alive during camera outages
- **Zombie Killer** — Detects frozen streams even when process is alive
- **RTSP Health Check** — Verifies camera is reachable before restart attempts
- **Exponential Backoff** — Smart retry delays prevent hammering YouTube
- **Auto-PUBLIC** — Restores stream visibility after recovery via YouTube API
- **Discord Alerts** — Instant notifications for offline/recovery/errors

---

## 🚀 What's New in v2.8.5

### Latest Patch Highlights (Jan 27, 2026)
- **Music filename auto-fix**: Sanitizes problem characters (quotes/ampersands) on startup so bad names can’t freeze the concat demuxer.
- **Frame-based zombie detection**: If FFmpeg stays alive but frame count stops advancing (e.g., music demux errors), the watchdog now force-restarts to unfreeze the stream.
- **Safer recovery**: BRB fallback still keeps YouTube alive while music restarts.

### Music Streaming
Stream background music to your live feed instead of camera audio! Perfect for adding ambiance to your stream.

- **API Control** — Enable via `POST /audio/music` endpoint
- **Playlist Support** — Place multiple MP3 files in `/config/music/` folder
- **Auto-Loop** — Plays through all songs (1, 2, 3... N) then loops back to start
- **Graceful Fallback** — Falls back to muted if no music files found

```bash
# Enable music mode
curl -X POST -H "X-API-Key: KEY" http://IP:9998/audio/music

# Check current audio mode
curl -H "X-API-Key: KEY" http://IP:9998/audio/status
# Returns: {"audio": "music", "muted": false, "music": true}
```

### Automated Docker Builds
- GitHub Actions workflow builds and pushes Docker images
- Images available at `ghcr.io/mcgeaverbeaver/vantagecamlive:latest`
- **Intel-only** — Optimized for Intel QuickSync hardware acceleration (no software encoding variant)

---

## 🚀 Getting Started

### Prerequisites

- Docker installed on your system
- RTSP camera feed URL
- YouTube stream key (for YouTube streaming)

### Folder Structure

Create a folder on your host for persistent data. The container auto-creates subfolders:

```
/config/
├── ads/
│   ├── topleft/
│   │   ├── DAY/         # Daytime sponsor logos
│   │   └── NIGHT/       # Nighttime sponsor logos
│   └── topright/
│       ├── DAY/
│       └── NIGHT/
├── music/               # MP3 files for music streaming mode
├── weather_icons/       # Auto-downloaded weather icons
├── watchdog.log         # Self-healing activity log
├── watchdog_state.json  # Persistent watchdog state
├── audio_mode           # Current audio: "muted", "unmuted", or "music"
└── stream_mode          # Current mode: "normal" or "fallback"
```

### Quick Start (Unraid)

1. Copy `my-VantageCamLive.xml` to `/boot/config/plugins/dockerMan/templates-user/`
2. Navigate to **Docker** → **Add Container**
3. Select **VantageCamLive** from the Template dropdown
4. Configure required variables and click **Apply**

---

## 🐳 Docker Compose

### Hardware Encoding (Intel QuickSync)

```yaml
version: "3"
services:
  vantagecam:
    image: ghcr.io/mcgeaverbeaver/vantagecamlive:latest
    container_name: vantagecam
    devices:
      - /dev/dri:/dev/dri  # Intel QuickSync
    environment:
      # === USER PERMISSIONS (Unraid) ===
      - PUID=99
      - PGID=100
      
      # === REQUIRED ===
      - RTSP_SOURCE=rtsp://user:pass@192.168.1.50:554/stream
      - ADMIN_USER=admin
      - ADMIN_PASS=change_me_please
      
      # === WEATHER & LOCATION ===
      - WEATHER_LAT=40.7128
      - WEATHER_LON=-74.0060
      - WEATHER_LOCATION=My City
      - WEATHER_TIMEZONE=America/New_York
      - CAMERA_HEADING=E
      
      # === YOUTUBE ===
      - YOUTUBE_URL=rtmp://a.rtmp.youtube.com/live2
      - YOUTUBE_KEY=xxxx-xxxx-xxxx-xxxx
      - YOUTUBE_WIDTH=2560
      - YOUTUBE_HEIGHT=1440
      - SCALING_MODE=fill
      
      # === FALLBACK MODE ===
      - FALLBACK_ENABLED=true
      
      # === SELF-HEALING (Recommended) ===
      - WATCHDOG_ENABLED=true
      - WATCHDOG_STATUS_URL=https://yourdomain.com/youtube_status.php
      - WATCHDOG_STARTUP_DELAY=180
      - WATCHDOG_RTSP_CHECK=true
      
      # === DISCORD ALERTS (Optional) ===
      - DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxxx/xxxxx
      - DISCORD_USER_ID=123456789012345678
      
      # === YOUTUBE API (Optional - for auto-PUBLIC) ===
      # - YOUTUBE_CLIENT_ID=xxxxx.apps.googleusercontent.com
      # - YOUTUBE_CLIENT_SECRET=GOCSPX-xxxxx
      # - YOUTUBE_REFRESH_TOKEN=1//xxxxx
      
    volumes:
      - /mnt/user/appdata/vantagecam:/config
    ports:
      - 8554:8554  # RTSP (if ENABLE_LOCAL_STREAM=true)
      - 9998:9998  # Audio API
    restart: unless-stopped
```

### Software Encoding Option (via Environment Variable)

If you don't have Intel hardware, you can disable hardware acceleration:

```yaml
environment:
  - HARDWARE_ACCEL=false
  - SOFTWARE_PRESET=faster
  - SOFTWARE_CRF=23
```

> ⚠️ **Note:** Software encoding uses significantly more CPU. Expect 2-4 cores at moderate-high usage for 1440p.

---

## 🎯 Direct-to-YouTube Mode

When streaming only to YouTube (no local preview), the container uses an optimized single-pipeline:

| Mode | Architecture | When Active |
|:-----|:-------------|:------------|
| **Direct** | Camera → FFmpeg → YouTube | `YOUTUBE_KEY` set + `ENABLE_LOCAL_STREAM=false` |
| **MediaMTX** | Camera → FFmpeg → RTSP → FFmpeg → YouTube | `ENABLE_LOCAL_STREAM=true` |

**Benefits of Direct mode:**
- ~400MB less RAM
- 1-2 fewer CPU cores
- Lower latency

---

## 📺 Fallback Mode (BRB Screen)

When enabled, VantageCam automatically shows a **"We'll Be Right Back"** screen when your camera's RTSP stream becomes unavailable. This keeps your YouTube stream alive instead of going offline.

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  NORMAL MODE                                                     │
│  Camera RTSP → FFmpeg → YouTube (viewers watch live feed)       │
│                                                                  │
│  ↓ RTSP health check fails (every 3 seconds)                    │
│                                                                  │
│  FALLBACK MODE (instant switch!)                                │
│  "We'll Be Right Back" + Overlays → FFmpeg → YouTube            │
│  (YouTube stream stays ALIVE - viewers never bounce!)           │
│                                                                  │
│  ↓ RTSP health check succeeds                                   │
│                                                                  │
│  NORMAL MODE (seamless switch back)                             │
│  Camera RTSP → FFmpeg → YouTube                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Key Features

| Feature | Description |
|:--------|:------------|
| **Unified Overlays** | BRB screen shows Weather, Ads, and Time overlays — looks like your live stream |
| **Instant Recovery** | Switches back within 3 seconds of camera coming online |
| **Zombie Detection** | Detects frozen streams even if FFmpeg process is alive |
| **3-Retry Startup** | Won't immediately fall back if camera is slow to boot |

### Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `FALLBACK_ENABLED` | `true` | Enable automatic fallback screen |

### What You'll See in Logs

```
# When camera goes down:
[Fallback] RTSP Ping Failed - Killing PID 1234...
[Fallback] Starting 'We'll Be Right Back' stream (With Overlays)...

# When camera recovers:
[Fallback] RTSP Recovered! Killing BRB Stream (PID 5678) to switch...
FFmpeg started (PID: 9012)

# Zombie detection:
[ERROR] FFmpeg FROZEN (Size static at 12345 for 12s). Killing...
```

---

## 🛡️ Self-Healing Watchdog

The watchdog monitors your stream and automatically recovers from failures.

### How It Works

1. **Waits** for startup delay (default 180s) to let YouTube recognize the stream
2. **Detects** failure by polling your `youtube_status.php` endpoint
3. **Checks** RTSP source health before attempting restart (prevents loops when camera is down)
4. **Stops** FFmpeg gracefully (SIGINT → SIGTERM → SIGKILL)
5. **Waits** with exponential backoff (10s → 20s → 40s... up to 15 min)
6. **Restarts** via the existing start.sh loop
7. **Verifies** stream is stable for 30+ seconds
8. **Sets** broadcast to PUBLIC (if YouTube API configured)
9. **Notifies** via Discord (if configured)

### Quick Setup

```yaml
environment:
  - WATCHDOG_ENABLED=true
  - WATCHDOG_STATUS_URL=https://yourdomain.com/youtube_status.php
  - WATCHDOG_STARTUP_DELAY=180
  - WATCHDOG_RTSP_CHECK=true
```

Deploy the included `youtube_status.php` to your web server. It should return:
```json
{"status": "live", "viewers": 123}
// or
{"status": "offline"}
```

### Watchdog vs Fallback Mode

These two features work together but serve different purposes:

| Feature | Purpose | Trigger |
|:--------|:--------|:--------|
| **Fallback Mode** | Keep YouTube alive during camera outages | RTSP port unreachable |
| **Watchdog** | Recover from YouTube-side failures | YouTube API reports "offline" |

The watchdog recognizes when Fallback Mode is active and won't try to restart during a camera outage.

---

## 🔔 Discord Notifications

Get instant alerts for:
- 🔴 Stream went offline
- 🟢 Stream recovered
- 🟠 RTSP source unreachable
- 🔴 YouTube API errors

### Setup

1. Create a Discord webhook in your server settings
2. Add your User ID for @mentions (optional)

```yaml
environment:
  - DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxxx/xxxxx
  - DISCORD_USER_ID=123456789012345678
```

---

## 🔑 YouTube API Setup Guide

The YouTube API enables automatic stream visibility restoration after recovery.

### Step 1: Create OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable **YouTube Data API v3**
4. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Choose **Web application**
6. Add `https://developers.google.com/oauthplayground` to redirect URIs
7. Save your **Client ID** and **Client Secret**

### Step 2: Get Refresh Token

1. Go to [OAuth 2.0 Playground](https://developers.google.com/oauthplayground)
2. Click gear icon → Enable "Use your own OAuth credentials"
3. Enter your Client ID and Secret
4. In Step 1, manually type: `https://www.googleapis.com/auth/youtube`
5. Authorize and get your **Refresh Token**

### Step 3: Configure VantageCam

```yaml
environment:
  - YOUTUBE_CLIENT_ID=xxxxx.apps.googleusercontent.com
  - YOUTUBE_CLIENT_SECRET=GOCSPX-xxxxx
  - YOUTUBE_REFRESH_TOKEN=1//xxxxx
```

### Step 4: Deploy Status Endpoint

Upload `youtube_status.php` to your web server and create a config file:

```php
// /etc/vantagecam/youtube_config.php
define('YOUTUBE_CLIENT_ID', 'your_client_id');
define('YOUTUBE_CLIENT_SECRET', 'your_client_secret');
define('YOUTUBE_REFRESH_TOKEN', 'your_refresh_token');
```

---

## 🚨 Alert System

VantageCam supports government weather alerts from:
- **Environment Canada** (CAP alerts)
- **US National Weather Service** (via Open-Meteo)

### Alert Priority

| Priority | Examples | Display |
|:---------|:---------|:--------|
| 🔴 Extreme | Tornado Warning, Hurricane | Flashing red banner |
| 🟠 Severe | Thunderstorm Warning, Blizzard | Solid orange banner |
| 🟡 Moderate | Winter Storm Watch, Heat Advisory | Yellow banner |
| ⚪ Minor | Frost Advisory, Air Quality | Gray banner |

### Compact Statements

Long-duration events (Heat Waves, Air Quality Statements) display in a compact format to save screen space.

---

## 📢 Sponsor Management

### Folder Structure

```
/config/ads/
├── topleft/
│   ├── DAY/      # 6 AM - 8 PM
│   └── NIGHT/    # 8 PM - 6 AM
└── topright/
    ├── DAY/
    └── NIGHT/
```

### Supported Formats
- PNG (recommended - supports transparency)
- JPEG
- WebP

### Behavior

| Position | Rotation | Notes |
|:---------|:---------|:------|
| Top-Left | Every 30s (configurable) | Always visible |
| Top-Right | Show 20s, hide 5 min | Periodic display |

---

## ⚙️ Advanced Configuration

### User Permissions

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PUID` | `0` (root) | User ID for file ownership |
| `PGID` | `0` (root) | Group ID for file ownership |

> **Unraid Users:** Set `PUID=99` and `PGID=100` to match the "nobody:users" standard.

### Video Output

| Variable | Default | Description |
|:---------|:--------|:------------|
| `HARDWARE_ACCEL` | `true` | Use VAAPI encoding |
| `VAAPI_DEVICE` | `/dev/dri/renderD128` | GPU device |
| `SOFTWARE_PRESET` | `faster` | x264 preset |
| `SOFTWARE_CRF` | `23` | Quality (lower=better) |
| `SCALING_MODE` | `fill` | `fill` or `fit` |
| `VIDEO_BITRATE` | `14M` | Output bitrate |
| `VIDEO_FPS` | `30` | Framerate |

### YouTube

| Variable | Default | Description |
|:---------|:--------|:------------|
| `YOUTUBE_URL` | `rtmp://a.rtmp.youtube.com/live2` | RTMP ingest |
| `YOUTUBE_KEY` | - | Stream key |
| `YOUTUBE_WIDTH` | `2560` | Output width |
| `YOUTUBE_HEIGHT` | `1440` | Output height |
| `YOUTUBE_BITRATE` | `4500k` | Upload bitrate |

### Fallback Mode

| Variable | Default | Description |
|:---------|:--------|:------------|
| `FALLBACK_ENABLED` | `true` | Enable BRB screen when camera is unreachable |

### Self-Healing Watchdog

| Variable | Default | Description |
|:---------|:--------|:------------|
| `WATCHDOG_ENABLED` | `false` | Enable watchdog |
| `WATCHDOG_STATUS_URL` | - | Status endpoint URL |
| `WATCHDOG_STARTUP_DELAY` | `180` | Wait before first check (seconds) |
| `WATCHDOG_CHECK_INTERVAL` | `30` | Check interval (seconds) |
| `WATCHDOG_INITIAL_DELAY` | `10` | Initial backoff delay |
| `WATCHDOG_MAX_DELAY` | `900` | Max backoff (15 min) |
| `WATCHDOG_STABILITY_THRESHOLD` | `30` | Stability time to reset backoff |
| `WATCHDOG_VERIFICATION_TIMEOUT` | `120` | Time to wait for YouTube "live" |
| `WATCHDOG_RTSP_CHECK` | `true` | Check RTSP before restart |
| `WATCHDOG_VERBOSE` | `true` | Detailed logging |

### Discord Notifications

| Variable | Default | Description |
|:---------|:--------|:------------|
| `DISCORD_WEBHOOK_URL` | - | Webhook URL |
| `DISCORD_USER_ID` | - | Your user ID for @mentions |

### YouTube API

| Variable | Default | Description |
|:---------|:--------|:------------|
| `YOUTUBE_CLIENT_ID` | - | OAuth Client ID |
| `YOUTUBE_CLIENT_SECRET` | - | OAuth Client Secret |
| `YOUTUBE_REFRESH_TOKEN` | - | OAuth Refresh Token |

### Weather & Alerts

| Variable | Default | Description |
|:---------|:--------|:------------|
| `WEATHER_LAT` | - | Latitude |
| `WEATHER_LON` | - | Longitude |
| `WEATHER_LOCATION` | - | Display name |
| `WEATHER_TIMEZONE` | `America/Toronto` | Timezone |
| `CAMERA_HEADING` | `N` | Wind arrow direction |
| `ALERTS_UPDATE_INTERVAL` | `900` | Update interval (seconds) |

### Sponsor Overlays

| Variable | Default | Description |
|:---------|:--------|:------------|
| `SCALE_TL` | `500` | Top-left max width |
| `SCALE_TR` | `400` | Top-right max width |
| `DAY_START_HOUR` | `6` | Day mode start |
| `DAY_END_HOUR` | `20` | Night mode start |
| `OVERLAYAD_ROTATE_TIMER` | `30` | Top-left rotation (seconds) |
| `TR_SHOW_SECONDS` | `20` | Top-right visible time |
| `TR_HIDE_SECONDS` | `300` | Top-right hidden time |

---

## 🎛️ Audio Control API

Control stream audio via HTTP:

| Action | Command |
|:-------|:--------|
| Status | `curl -H "X-API-Key: KEY" http://IP:9998/audio/status` |
| Unmute | `curl -X POST -H "X-API-Key: KEY" http://IP:9998/audio/unmute` |
| Mute | `curl -X POST -H "X-API-Key: KEY" http://IP:9998/audio/mute` |
| Music | `curl -X POST -H "X-API-Key: KEY" http://IP:9998/audio/music` |
| Toggle | `curl -X POST -H "X-API-Key: KEY" http://IP:9998/audio/toggle` |
| Health | `curl http://IP:9998/health` |

### Audio Modes

| Mode | Description |
|:-----|:------------|
| `muted` | Silent audio (default) |
| `unmuted` | Camera's original audio |
| `music` | Stream MP3 playlist from `/config/music/` |

### Music Streaming Setup

1. Create the music folder: `/config/music/`
2. Add MP3 files to the folder
3. Enable music mode via API: `POST /audio/music`

The playlist plays all MP3 files in alphabetical order, then loops back to the beginning. Switching to music mode while no MP3 files exist will fall back to muted.

> Set `AUDIO_API_KEY` to require authentication. Health endpoint always works without auth.

---

## 🔧 Troubleshooting

### File Permissions (Unraid)

**Files owned by root instead of nobody:users**
- Set `PUID=99` and `PGID=100` in your container config
- Run once to fix existing files: `chown -R nobody:users /mnt/user/appdata/vantagecam`

### Fallback Mode Issues

**Stream goes to BRB immediately on boot**
- This can happen if your camera takes a long time to initialize
- The 3-retry mechanism should handle this, but check camera responsiveness

**"Ping Failed" loop during camera reboot**
- Fixed in v2.8.3 — the BRB stream is now explicitly killed when camera recovers

**BRB screen doesn't show overlays**
- Verify overlay files exist in `/config/`
- Check logs for overlay loading errors

### Watchdog Issues

**"YouTube API credentials not configured"**
- This is informational, not an error. Auto-PUBLIC is optional.

**Watchdog not starting**
- Verify `WATCHDOG_ENABLED=true`
- Verify `YOUTUBE_KEY` is set
- Check `WATCHDOG_STATUS_URL` is accessible

**RTSP source shows unreachable**
- Verify camera is powered on and network-accessible
- Check RTSP URL format: `rtsp://user:pass@ip:port/path`

### YouTube API Issues

**`redirect_uri_mismatch`**
- Add `https://developers.google.com/oauthplayground` to OAuth credentials redirect URIs

**`invalid_scope`**
- Don't use dropdown in OAuth Playground
- Manually type: `https://www.googleapis.com/auth/youtube`

**`insufficient authentication scopes`**
- Regenerate refresh token with correct scope

**Token expires after 7 days**
- Publish your app in OAuth consent screen, OR
- Regenerate token weekly

### Stream Issues

**"Could not find ref with POC" errors**
- Rare after v2.8.4 RTSP improvements
- If persistent, check network stability between camera and server

**"RTP: bad cseq" errors**
- Should be eliminated in v2.8.4 with TCP transport and buffering
- If still occurring, increase `buffer_size` in start.sh

**"deprecated pixel format" warnings**
- Harmless FFmpeg warning, ignore

**FFmpeg FROZEN detected**
- Zombie Killer detected a stalled stream and is recovering
- Check camera connection stability

**Container shows "unhealthy"**
- Check if Audio API is responding: `curl http://IP:9998/health`
- Check FFmpeg is running: `docker exec vantagecam ps aux | grep ffmpeg`

---

## 📜 Changelog

### v2.8.5 - Music Streaming & CI/CD

**New Features:**
- **Music Streaming Mode** — Stream background music from `/config/music/` folder instead of camera audio. Playlist loops through all MP3 files continuously.
- **Music API Endpoint** — New `POST /audio/music` endpoint to enable music mode via HTTP API.
- **GitHub Actions CI/CD** — Automated Docker builds on push to main. Images published to `ghcr.io/mcgeaverbeaver/vantagecamlive:latest`.
- **ARM64 Support** — Separate ARM64 builds available (`:latest-arm64`) for Raspberry Pi and ARM servers.

**Improvements:**
- Audio status API now includes `music` field in response
- Graceful fallback to muted mode if no music files found

### v2.8.4 - Multi-Alert Stacking & RTSP Reliability

**New Features:**
- **Multi-Alert Stacking** — Environment Canada alerts now stack when multiple are active (e.g., Snow Squall + Wind Warning). Each alert displays with its own color and timestamp.
- **Real-Time Visibility** — Weather visibility now uses current observations instead of hourly forecasts, accurate during rapidly changing conditions.

**Improvements:**
- **RTSP Reliability Overhaul** — 4MB buffer, 500ms max delay, corrupt frame discarding, and error tolerance. Eliminates decoder errors during network instability.
- **Doubled thread queue size** — Better handling of bursty network traffic.

**Fixed:**
- Visibility showing incorrect values during snow squalls/fog
- Only first alert displaying when multiple alerts active

### v2.8.3 - Fallback Mode & Zombie Killer

**Major Features:**
- **"Zombie Killer" Monitor** — Detects frozen streams (even when process is alive) by monitoring progress file size. Auto-restarts within 12 seconds.
- **Instant Camera Recovery** — Switches back to main camera the instant RTSP port opens, not waiting for full video decode.
- **Unified Overlay System** — BRB screen displays full Weather, Ads, and Time overlays (looks identical to live stream).
- **Reboot Loop Fix** — Solved "Ping Failed" loop by explicitly killing BRB process when camera recovers.
- **Startup Stability** — 3-attempt retry mechanism prevents falling back to BRB if camera is slow to boot.
- **PUID/PGID Support** — Run as non-root user for proper file ownership (Unraid compatibility).

**Improvements:**
- Cleaner code architecture with separated RTSP and overlay inputs
- Better logging with heartbeat status every 10 seconds
- Docker image labels for version tracking
- `.dockerignore` for faster builds

### v2.8.1 - RTSP Health Check & Smart Startup
- **New:** RTSP source health check before recovery attempts
- **New:** Configurable startup delay (YouTube needs time to recognize ingest)
- **New:** Extended verification timeout (120s default)
- **New:** Verbose logging option for debugging
- **Improved:** Won't restart if RTSP source is down (prevents loops)

### v2.8 - Self-Healing Watchdog & Auto-Recovery
- **New:** Self-healing watchdog with automatic stream recovery
- **New:** YouTube API integration for auto-PUBLIC restoration
- **New:** Discord webhook notifications for stream events
- **New:** Startup validation for credentials
- **New:** FFmpeg progress monitoring for stall detection
- **New:** Exponential backoff with jitter
- **New:** State persistence across restarts
- **Improved:** Graceful FFmpeg shutdown (SIGINT → SIGTERM → SIGKILL)
- **Fixed:** Health endpoint works with API key enabled

### v2.7 - Direct-to-YouTube Mode
- **New:** Direct-to-YouTube single-pipeline mode
- **New:** Extended alert classification
- **New:** Flashing red warnings
- **New:** Compact statement display
- **Improved:** MediaMTX disabled in direct mode

### v2.6 - Optional Hardware Acceleration
- **New:** Software encoding option
- **New:** Auto-fallback to software mode
- **New:** Alert timestamps
- **Improved:** Combined weather+alert overlay

### v2.5 - Smart Alert Stacking
- Initial release with stacked overlays
- Environment Canada and NWS support
- Dynamic sponsor rotation

---
## 📄 License

MIT License - See [LICENSE](LICENSE) for details.

---
## 🤝 Contributing

Contributions welcome! Please open an issue or submit a PR.

---
## 💬 Support

- **Issues:** [GitHub Issues](https://github.com/McGeaverBeaver/VantageCamLive/issues)
- **Demo:** [https://simcoelocal.com/](https://simcoelocal.com/)
