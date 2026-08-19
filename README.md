# VantageCam Live v2.9.1

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
- [What's New in v2.9.1](#-whats-new-in-v291)
- [Admin WebUI & Stream Preview](#-admin-webui--stream-preview)
- [Stream Won't Start?](#-stream-wont-start)
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

## 🚀 What's New in v2.9.1

### 📐 Drag-and-Drop Overlay Positioning
Overlay positions are no longer hardcoded to the corners. In **Admin WebUI → Overlay Layout**
you can drag each overlay anywhere, resize it from its corner, or hide it entirely — with the
live preview as the backdrop so you see exactly what you are arranging.

- Positions live in `/config/overlay_layout.json` and survive restarts
- Coordinates are in the 2560×1440 composition canvas, so one layout is correct at 1080p, 1440p and 4K
- Sponsor logos are re-rendered at the box size you choose, so resizing stays crisp
- Hiding an overlay removes its FFmpeg input entirely (a little less CPU)
- **Save** applies to the preview; **Save & Apply** also restarts the encoder to push it on air

### 🧪 Ingest Diagnostics
FFmpeg reports every publishing failure as a generic `I/O error`, which makes a blocked port,
a broken TLS path and a rejected stream key look identical. The new **Diagnostics** page (and a
boot-time check) walks the path one layer at a time — **DNS → TCP → TLS handshake** — and names
the layer that failed, with a specific remedy. It sends no stream key, so it is safe to run while live.

### 🖥️ Redesigned Admin UI
The dashboard is now a sectioned app with a sidebar (Dashboard, Live Preview, Overlay Layout,
Sponsors, Weather, Audio, Diagnostics, Logs, Settings) instead of one endless scrolling page.
Status pills stay pinned in the header on every page, sections deep-link via `#hash`, each
section loads only when opened, and the sidebar collapses to a menu on phones.

### 🐛 Fixes
- **No more BRB flapping when YouTube is the problem.** A failed startup used to switch to the
  "We'll Be Right Back" screen — but BRB publishes to the *same* output, so it failed instantly
  and bounced back, reconnecting to YouTube every couple of seconds. The supervisor now checks
  which leg actually failed and, for output-side failures, stays in normal mode with a growing
  backoff instead.
- **Stream keys are redacted from logs.** FFmpeg prints the full output URL (key included) on
  error, which landed in `docker logs` and `ffmpeg.log` in plaintext.
- **The watchdog no longer freezes a container that is already recovering** — it used to impose
  a restart hold even when no FFmpeg was running for it to restart.
- **The backoff counter resets on container start**, so a persisted attempt count from an old
  incident no longer puts a freshly-booted container straight at the 15-minute maximum delay.

---

## 🚀 What's New in v2.9.0

### 🖥️ Admin WebUI with Live Stream Preview
A full browser dashboard on port **9999**:

- **Live Preview** — See the *exact* composed output (camera + sponsors + weather overlays) before/while it broadcasts, without touching the live pipeline
- **Toggle to Save CPU** — The preview is a separate on-demand FFmpeg process; turn it off with one click, and it also auto-stops after 2 minutes with no viewers
- **Full monitoring** — Stream mode, encoder stats, watchdog state, camera reachability, CPU/RAM
- **One-click controls** — Audio mute/unmute/music, stream restart, weather refresh
- **Sponsor manager** — Upload/delete logos per slot and day/night mode from the browser
- **Log viewer** — Tail watchdog, FFmpeg, and weather logs

See [Admin WebUI & Stream Preview](#-admin-webui--stream-preview).

### 🐛 Major Bug Fixes
- **MediaMTX mode now reaches YouTube again** — the second FFmpeg leg (RTSP → YouTube) documented since v2.7 was lost in the v2.8.3 refactor; restored with full audio-mode support
- **Watchdog backoff is now real** — the exponential backoff previously never delayed anything because the supervisor loop restarted FFmpeg instantly; the watchdog now publishes a restart hold that the loop honors
- **Progress file growth capped** — `ffmpeg_progress.txt` grew ~10MB/day unbounded; frozen-stream detection is now mtime-based and the file is truncated periodically
- **PUID + MediaMTX fixed** — the MediaMTX config was written to root-owned `/usr/local/bin` after privileges were dropped
- **Container no longer permanently "unhealthy" without a YouTube key** — the Audio API (which the Docker healthcheck depends on) now always starts
- **US NWS alerts now stack** — multiple simultaneous NWS alerts display like Environment Canada alerts (previously only the first showed)
- **Border-town alert fix** — new `ALERT_COUNTRY=CA|US` override (the lat/lon heuristic misclassified Atlantic Canada as US and New England as Canada)

### 🔒 Security Hardening
- Admin WebUI refuses to serve while `ADMIN_PASS` is empty or a shipped default
- Timing-safe API-key comparison in the Audio API; threaded server so a stalled client can't wedge the Docker healthcheck
- PID-reuse guards before any signal is sent from the APIs or watchdog
- PHP status endpoint: unpredictable cache path + atomic cache writes

---

## 🖥️ Admin WebUI & Stream Preview

Open `http://<host>:9999/` and log in with `ADMIN_USER` / `ADMIN_PASS`.

> 🔒 The WebUI **refuses all requests** until `ADMIN_PASS` is set to something
> other than the shipped defaults. Keep port 9999 on your LAN — don't port-forward
> it to the internet (put it behind a reverse proxy with TLS if you need remote access).

### Live Preview

The preview spawns a **separate low-FPS FFmpeg pipeline** that composes the same
overlay playlists as the broadcast (sponsors top-left/top-right, weather
bottom-right, identical scaling) and serves it as MJPEG to your browser.

- The broadcast pipeline is **never touched** — start/stop the preview freely
- Auto-stops after `PREVIEW_IDLE_TIMEOUT` seconds with no viewers (default 120)
- **Auto source** mirrors the broadcast: shows the BRB screen when in fallback mode
- Preview the **BRB screen** on demand to check your fallback branding before an outage happens
- Works even before `YOUTUBE_KEY` is set — dial in your overlays *before* you go live

| Variable | Default | Description |
|:---------|:--------|:------------|
| `ADMIN_WEBUI_ENABLED` | `true` | Enable the dashboard |
| `ADMIN_PORT` | `9999` | Dashboard port |
| `PREVIEW_FPS` | `5` | Preview frame rate (1–15) |
| `PREVIEW_WIDTH` | `960` | Preview width in pixels |
| `PREVIEW_QUALITY` | `6` | MJPEG quality (2 best – 31 worst) |
| `PREVIEW_IDLE_TIMEOUT` | `120` | Seconds without viewers before auto-stop |
| `PREVIEW_LOW_CPU` | `false` | Decode keyframes only (~1 fps, big CPU saving on 4K cams) |

### API Endpoints (all require Basic auth)

| Endpoint | Method | Description |
|:---------|:-------|:------------|
| `/api/status` | GET | Full status JSON (stream, camera, audio, watchdog, system) |
| `/api/preview/start?source=auto\|camera\|brb` | POST | Start the preview pipeline |
| `/api/preview/stop` | POST | Stop it (frees the CPU immediately) |
| `/api/preview/stream` | GET | MJPEG stream |
| `/api/preview/snapshot` | GET | Single JPEG frame |
| `/api/audio/{mute,unmute,music,toggle}` | POST | Audio control |
| `/api/stream/restart` | POST | Restart the broadcast FFmpeg |
| `/api/weather/refresh` | POST | Regenerate the weather overlay now |
| `/api/ads` / `/api/ads/upload` / `/api/ads/delete` | GET/POST | Sponsor logo management |
| `/api/logs?name=watchdog\|ffmpeg\|weather` | GET | Tail logs |
| `/api/overlay/{weather,tl,tr,fallback}` | GET | Current overlay PNGs (zero CPU) |
| `/api/layout` | GET/POST | Overlay positions (`?apply=true` also restarts the encoder) |
| `/api/layout/reset` | POST | Restore default corner positions |
| `/api/ingest/check` | POST | DNS → TCP → TLS probe of the configured ingest |

---

## 🚑 Stream Won't Start?

FFmpeg collapses every publishing failure into `I/O error`, so start by identifying **which layer**
is broken. Open **Admin WebUI → Diagnostics → Test Ingest Connection**, or from a shell:

```bash
docker exec vantagecam python3 /ingest_probe.py --text "$YOUTUBE_URL"
```

| Probe result | Meaning | Fix |
|:-------------|:--------|:----|
| **DNS FAILED** | The container can't resolve the ingest host | Fix the container's DNS |
| **TCP FAILED** | The port is blocked before TLS is attempted | A firewall/ISP is blocking outbound `rtmps` 443 or `rtmp` 1935. Try the other ingest. |
| **TLS FAILED** (works without verification) | Stale/missing CA trust store | Refresh `ca-certificates` in the image |
| **TLS FAILED** (fails either way) | Something is terminating TLS on that port (deep packet inspection / transparent proxy) | Switch to `YOUTUBE_URL=rtmp://a.rtmp.youtube.com/live2` |
| **All ok**, stream still won't start | The endpoint is fine, so the *key* is being rejected | Reset the key in YouTube Studio; make sure no other encoder is using it |

### Telling the two apart in the FFmpeg log

The layer that fails is named in the error, and the two cases look different:

```
# Stream key rejected — TLS succeeded, YouTube dropped the RTMP handshake:
[rtmps @ ...] Cannot read RTMP handshake response
Error opening output files: End of file

# Network/TLS path broken — never got as far as RTMP:
[tls @ ...] IO error: End of file
Error opening output files: I/O error
```

> ⚠️ **Only one encoder may use a stream key at a time.** If an older container is still running
> (or several restarts overlapped), YouTube rejects the newcomer. Confirm with
> `docker ps | grep vantagecam` before hunting further.

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
├── ffmpeg.log           # FFmpeg stderr (viewable in the Admin WebUI)
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
      # ADMIN_USER/ADMIN_PASS protect the Admin WebUI and the local RTSP output.
      # Use letters/digits/-_. (the password is embedded in an RTSP URL in
      # MediaMTX mode, so characters like @ : / can break authentication there).
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
      - 9999:9999  # Admin WebUI (dashboard + stream preview)
    restart: unless-stopped
```

### Software Encoding (No GPU)

```yaml
version: "3"
services:
  vantagecam:
    image: ghcr.io/mcgeaverbeaver/vantagecamlive:latest
    container_name: vantagecam
    environment:
      - PUID=99
      - PGID=100
      - RTSP_SOURCE=rtsp://user:pass@192.168.1.50:554/stream
      - HARDWARE_ACCEL=false
      - SOFTWARE_PRESET=faster
      - SOFTWARE_CRF=23
      # ... (same as above)
    volumes:
      - /mnt/user/appdata/vantagecam:/config
    ports:
      - 9998:9998
    restart: unless-stopped
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

> ℹ️ Fallback mode applies to **Direct-to-YouTube mode** (`ENABLE_LOCAL_STREAM=false`).
> In MediaMTX mode, a camera outage stops the local RTSP feed and the YouTube leg
> retries until the camera returns.

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
| 🔴 Extreme | Tornado, Severe Thunderstorm, Hurricane, Blizzard, Extreme Cold, Heat Warnings | Flashing red banner |
| 🟠 Severe | Winter Storm / Snow Squall / Flash Flood Watches, unrecognized Warnings | Solid orange banner |
| 🟡 Moderate | Advisories, other Watches | Yellow banner |
| ⚪ Minor | Statements (compact), Ended notices | Gray banner |

Environment Canada alerts carry an official colour level, which takes priority over
the keyword classification above. Near the CA/US border, set `ALERT_COUNTRY=CA` or
`US` to pin the alert source.

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
| `CAMERA_HEADING` | `E` | Direction the camera faces (compass point or degrees) |
| `ALERTS_UPDATE_INTERVAL` | `900` | Update interval (seconds) |
| `ALERT_COUNTRY` | auto | Force alert source: `CA` (Environment Canada) or `US` (NWS). Recommended near the border. |

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

### v2.9.0 - Admin WebUI, Stream Preview & Reliability Overhaul

**New Features:**
- **Admin WebUI** (port 9999) — browser dashboard with live status, controls, sponsor management, and log viewer. Secured with `ADMIN_USER`/`ADMIN_PASS` (refuses to serve on default/empty passwords).
- **Live Stream Preview** — on-demand, low-FPS MJPEG preview of the exact composed output (overlays included) via a separate FFmpeg pipeline. Toggle off (or let it auto-stop after `PREVIEW_IDLE_TIMEOUT`) to save CPU. Preview the camera or the BRB screen, even before a YouTube key is configured.
- **FFmpeg log capture** — encoder stderr is tee'd to `/config/ffmpeg.log` (bounded, auto-trimmed) and viewable in the WebUI.
- **On-demand weather refresh** — regenerate the weather/alert overlay from the WebUI instead of waiting for the next cycle.
- **`ALERT_COUNTRY` override** — force `CA` or `US` alert sources near the border.

**Fixed:**
- **MediaMTX mode never pushed to YouTube** — the documented second FFmpeg leg (local RTSP → YouTube) was lost in the v2.8.3 refactor. Restored with muted/unmuted/music audio support.
- **Watchdog exponential backoff was a no-op** — start.sh restarted FFmpeg instantly after the watchdog killed it. The watchdog now writes a restart hold that the supervisor honors.
- **`ffmpeg_progress.txt` grew unbounded** (~10MB/day). Frozen-stream detection is now mtime-based and the file is truncated hourly past 10MB; the watchdog and healthcheck read only the file tail.
- **MediaMTX + PUID broken** — the generated config was written to root-owned `/usr/local/bin` after privileges were dropped; now written to `/tmp`.
- **Container reported "unhealthy" when no `YOUTUBE_KEY` was set** — the Docker healthcheck requires the Audio API, which only started with a key. It now always starts.
- **Only the first NWS alert displayed** — US alerts now stack like Environment Canada alerts.
- **Country detection misclassified border regions** — Atlantic Canada was treated as US, New England as Canada; box refined + explicit override added.
- **Stale-PID hazards** — audio API, admin API, and watchdog verify the target process is actually FFmpeg before signaling (guards against PID reuse after reboots).

**Security:**
- Timing-safe API-key comparison (Audio API) and Basic-auth credential comparison (Admin WebUI).
- Audio API switched to a threaded server so a slow client can't block the Docker healthcheck endpoint.
- Ad uploads are extension-whitelisted, size-capped, path-traversal-proofed, and validated as real images.
- PHP status endpoint: per-install cache path (no predictable `/tmp` name) and atomic cache writes.
- `.dockerignore` actually works now (the file was previously named `dockerignore` and ignored by Docker).

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
