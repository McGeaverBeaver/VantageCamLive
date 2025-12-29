# Vantage Cam Live v2.8.2

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**OpenSource Automated Live Stream Broadcaster with Weather, Smart Alerts & Self-Healing**

> ?? **See it in action:** [https://simcoelocal.com/](https://simcoelocal.com/)

Transform a standard security camera feed into a professional broadcast without the hassle. Vantage Cam Live runs entirely in Docker and handles all the heavy lifting for you:

- ? **Automated Production** — Overlays real-time weather, government warnings, and rotating sponsor logos
- ?? **Universal Fit** — Smart scaling fixes aspect ratios (no more black bars!)
- ?? **Set & Forget** — Runs 24/7 with self-healing assets and automatic recovery
- ?? **Self-Healing** — Detects failures and auto-recovers with Discord notifications

---

## ?? Table of Contents

- [Key Features](#-key-features)
- [Getting Started](#-getting-started)
- [Docker Compose](#-docker-compose)
- [Direct-to-YouTube Mode](#-direct-to-youtube-mode)
- [Self-Healing Watchdog](#-self-healing-watchdog)
- [Discord Notifications](#-discord-notifications)
- [YouTube API Setup Guide](#-youtube-api-setup-guide)
- [Alert System](#-alert-system)
- [Sponsor Management](#-sponsor-management)
- [Advanced Configuration](#%EF%B8%8F-advanced-configuration)
- [Audio Control API](#%EF%B8%8F-audio-control-api)
- [Troubleshooting](#-troubleshooting)
- [Changelog](#-changelog)

---

## ?? Key Features

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
- **Audio Control API** — Remote mute/unmute via HTTP endpoints

### Reliability *(v2.8+)*
- **Self-Healing Watchdog** — Auto-detects failures and recovers streams
- **RTSP Health Check** — Verifies camera is reachable before restart attempts
- **Exponential Backoff** — Smart retry delays prevent hammering YouTube
- **Auto-PUBLIC** — Restores stream visibility after recovery via YouTube API
- **Discord Alerts** — Instant notifications for offline/recovery/errors

---

## ?? Getting Started

### Prerequisites

- Docker installed on your system
- RTSP camera feed URL
- YouTube stream key (for YouTube streaming)

### Folder Structure

Create a folder on your host for persistent data. The container auto-creates subfolders:

```
/config/
+-- ads/
¦   +-- topleft/
¦   ¦   +-- DAY/         # Daytime sponsor logos
¦   ¦   +-- NIGHT/       # Nighttime sponsor logos
¦   +-- topright/
¦       +-- DAY/
¦       +-- NIGHT/
+-- weather_icons/       # Auto-downloaded weather icons
+-- watchdog.log         # Self-healing activity log
+-- watchdog_state.json  # Persistent watchdog state
```

### Quick Start (Unraid)

1. Copy `my-VantageCamLive.xml` to `/boot/config/plugins/dockerMan/templates-user/`
2. Navigate to **Docker** ? **Add Container**
3. Select **VantageCamLive** from the Template dropdown
4. Configure required variables and click **Apply**

---

## ?? Docker Compose

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

> ?? **Note:** Software encoding uses significantly more CPU. Expect 2-4 cores at moderate-high usage for 1440p.

---

## ?? Direct-to-YouTube Mode

When streaming only to YouTube (no local preview), the container uses an optimized single-pipeline:

| Mode | Architecture | When Active |
|:-----|:-------------|:------------|
| **Direct** | Camera ? FFmpeg ? YouTube | `YOUTUBE_KEY` set + `ENABLE_LOCAL_STREAM=false` |
| **MediaMTX** | Camera ? FFmpeg ? RTSP ? FFmpeg ? YouTube | `ENABLE_LOCAL_STREAM=true` |

**Benefits of Direct mode:**
- ~50MB less RAM
- 1-2 fewer CPU cores
- Lower latency

---

## ?? Self-Healing Watchdog

The watchdog monitors your stream and automatically recovers from failures.

### How It Works

1. **Waits** for startup delay (default 180s) to let YouTube recognize the stream
2. **Detects** failure by polling your `youtube_status.php` endpoint
3. **Checks** RTSP source health before attempting restart (prevents loops when camera is down)
4. **Stops** FFmpeg gracefully (SIGINT ? SIGTERM ? SIGKILL)
5. **Waits** with exponential backoff (10s ? 20s ? 40s... up to 15 min)
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

### Recovery Flow

```
Stream OFFLINE detected (2 consecutive checks)
              ¦
              ?
+---------------------------------+
¦  Check RTSP source health       ¦
¦  (Skip restart if camera down)  ¦
+---------------------------------+
              ¦
        RTSP Healthy?
       +-------------+
       No            Yes
       ¦              ¦
       ?              ?
  Wait & retry   ?? Discord: "Stream Offline"
                 Stop FFmpeg gracefully
                 Wait with exponential backoff
                      ¦
                      ?
              +---------------------------------+
              ¦  FFmpeg auto-restarts           ¦
              ¦  Wait 20s for stabilization     ¦
              ¦  Verify LIVE for 30+ seconds    ¦
              +---------------------------------+
                      ¦
               +-------------+
               ¦             ¦
            SUCCESS       FAILED
               ¦             ¦
               ?             ?
         Reset backoff   Increase delay
         Set ? PUBLIC    Retry
         ?? "Recovered"
```

---

## ?? Discord Notifications

Get instant alerts on Discord for stream events and errors.

### Setup

1. **Create Webhook:**
   - Open Discord ? Server Settings ? Integrations ? Webhooks
   - Click **New Webhook**, name it, select channel
   - Copy the webhook URL

2. **Get Your User ID (for @mentions):**
   - Enable Developer Mode: Settings ? Advanced ? Developer Mode
   - Right-click your username ? Copy User ID

3. **Configure:**
   ```yaml
   environment:
     - DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxxx/xxxxx
     - DISCORD_USER_ID=123456789012345678
   ```

### Alert Types

| Event | Color | Mentions You? |
|:------|:------|:--------------|
| Watchdog Started | ?? Green | No |
| Stream Went Offline | ?? Orange | Yes |
| Stream Recovered | ?? Green | Yes |
| Broadcast Set to PUBLIC | ?? Green | No |
| RTSP Source Down | ?? Orange | Yes |
| Token Expired | ?? Red | Yes |
| Invalid Credentials | ?? Red | Yes |
| Scope Error | ?? Orange | Yes |

---

## ?? YouTube API Setup Guide

Enable auto-PUBLIC to automatically restore stream visibility after recovery.

> **Note:** This is optional. The watchdog works without it—streams just won't auto-change to PUBLIC.

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., "VantageCam")
3. Select the project

### Step 2: Enable YouTube Data API v3

1. Go to **APIs & Services** ? **Library**
2. Search for "YouTube Data API v3"
3. Click **Enable**

### Step 3: Configure OAuth Consent Screen

1. Go to **APIs & Services** ? **OAuth consent screen**
2. Select **External** ? **Create**
3. Fill in app name, support email, developer email
4. Add scope: `https://www.googleapis.com/auth/youtube`
5. Add yourself as a test user
6. Save

### Step 4: Create OAuth Credentials

1. Go to **APIs & Services** ? **Credentials**
2. Click **+ Create Credentials** ? **OAuth client ID**
3. Select **Web application**
4. Add Authorized redirect URI:
   ```
   https://developers.google.com/oauthplayground
   ```
5. Click **Create**
6. Copy your **Client ID** and **Client Secret**

### Step 5: Generate Refresh Token

1. Go to [OAuth Playground](https://developers.google.com/oauthplayground)
2. Click gear icon ?? ? Check "Use your own OAuth credentials"
3. Enter your Client ID and Client Secret
4. In "Input your own scopes", type:
   ```
   https://www.googleapis.com/auth/youtube
   ```
5. Click **Authorize APIs** ? Sign in ? Grant access
6. Click **Exchange authorization code for tokens**
7. Copy the **Refresh Token**

### Step 6: Configure Container

```yaml
environment:
  - YOUTUBE_CLIENT_ID=xxxxx.apps.googleusercontent.com
  - YOUTUBE_CLIENT_SECRET=GOCSPX-xxxxx
  - YOUTUBE_REFRESH_TOKEN=1//xxxxx
```

### Token Expiration

**Testing mode:** Tokens expire after 7 days. You can either:
- Regenerate the token weekly, OR
- Publish your app (OAuth consent screen ? Publish App)

> **Note:** Publishing your app does NOT give others access to your YouTube account. It only means others could use your app to authorize access to their own accounts. Your refresh token only works for your channel.

---

## ?? Alert System

Supports Environment Canada and US National Weather Service alerts:

| Alert Type | Color | Display |
|:-----------|:------|:--------|
| **Warning** (Extreme) | ?? Red + Flashing | Tornado, Severe Thunderstorm, Hurricane |
| **Warning** (Moderate) | ?? Orange | Freezing Rain, Wind, Rainfall, Snowfall |
| **Warning** (Minor) | ?? Yellow | Other warnings |
| **Watch** | Colored + Dashed | Same colors, dashed border |
| **Statement** | ? Grey | Compact half-height display |

---

## ?? Sponsor Management

Dynamic "watch folder" system for sponsor logos:

- **Auto-Resizing** — Any image size automatically scaled to fit
- **Top-Left** — Continuous rotation loop (primary sponsors)
- **Top-Right** — Popup style, 20s visible / 5min hidden (CTAs)
- **Day/Night** — Automatic switching based on configured hours
- **Formats:** PNG, JPG, JPEG

---

## ??? Advanced Configuration

### User Permissions (PUID/PGID)

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PUID` | `0` (root) | User ID for file ownership |
| `PGID` | `0` (root) | Group ID for file ownership |

> **Unraid Users:** Set `PUID=99` and `PGID=100` to match the "nobody:users" standard.

### Hardware & Encoding

| Variable | Default | Description |
|:---------|:--------|:------------|
| `HARDWARE_ACCEL` | `true` | `false` for software encoding |
| `VAAPI_DEVICE` | `/dev/dri/renderD128` | VAAPI device path |
| `SOFTWARE_PRESET` | `faster` | x264 preset (ultrafast?medium) |
| `SOFTWARE_CRF` | `23` | Quality (lower=better, 18-28) |

### Video Output

| Variable | Default | Description |
|:---------|:--------|:------------|
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

### Debug & Monitoring

| Variable | Default | Description |
|:---------|:--------|:------------|
| `WEATHER_DEBUG` | `false` | Verbose weather logging |
| `FFMPEG_PROGRESS_LOG` | `false` | Enable FFmpeg frame logging. **Warning:** File grows ~10MB/day. Only needed for local frame-stall detection. YouTube status API is the primary health check. |

### Fallback Mode (NEW in v2.8.2)

When enabled, VantageCam automatically shows a **"We'll Be Right Back"** screen when your camera's RTSP stream becomes unavailable. This keeps your YouTube stream alive instead of going offline, so viewers aren't bounced to other videos.

| Variable | Default | Description |
|:---------|:--------|:------------|
| `FALLBACK_ENABLED` | `true` | Enable automatic fallback screen when camera is unreachable |

**How it works:**
1. VantageCam monitors your camera's RTSP connection every 3 seconds
2. If the camera becomes unreachable, it instantly switches to a fallback image
3. The YouTube stream stays LIVE with the "We'll Be Right Back" screen
4. When the camera recovers, it automatically switches back to the live feed
5. Viewers never leave your stream!

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

## ??? Audio Control API

Control stream audio via HTTP:

| Action | Command |
|:-------|:--------|
| Status | `curl -H "X-API-Key: KEY" http://IP:9998/audio/status` |
| Unmute | `curl -X POST -H "X-API-Key: KEY" http://IP:9998/audio/unmute` |
| Mute | `curl -X POST -H "X-API-Key: KEY" http://IP:9998/audio/mute` |
| Toggle | `curl -X POST -H "X-API-Key: KEY" http://IP:9998/audio/toggle` |
| Health | `curl http://IP:9998/health` |

> Set `AUDIO_API_KEY` to require authentication. Health endpoint always works without auth.

---

## ?? Troubleshooting

### File Permissions (Unraid)

**Files owned by root instead of nobody:users**
- Set `PUID=99` and `PGID=100` in your container config
- Run once to fix existing files: `chown -R nobody:users /mnt/user/appdata/vantagecam`

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
- Normal during startup, usually resolves quickly

**"deprecated pixel format" warnings**
- Harmless FFmpeg warning, ignore

**Container shows "unhealthy"**
- Check if Audio API is responding: `curl http://IP:9998/health`
- Check FFmpeg is running: `docker exec vantagecam ps aux | grep ffmpeg`

---

## ?? Changelog

### v2.8.2 - PUID/PGID Support & Fallback Mode
- **New:** PUID/PGID support for proper file ownership (Unraid compatibility)
- **New:** **Fallback Mode** - Shows "We'll Be Right Back" screen when camera is unreachable
  - Keeps YouTube stream alive instead of going offline
  - Viewers stay on your stream instead of being bounced to other videos
  - Automatically switches back when camera recovers
  - Checks RTSP health every 3 seconds for fast detection
- **New:** `.dockerignore` for cleaner/faster builds
- **New:** Docker image labels (version, maintainer, source)
- **Fixed:** Processes now actually run as target user (not just file ownership)
- **Changed:** FFmpeg progress logging now disabled by default (`FFMPEG_PROGRESS_LOG=false`)
  - YouTube status API is the primary and more reliable health check
  - Enable if you need local frame-stall detection (grows ~10MB/day)
- **Improved:** Documentation for file permissions

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
- **Improved:** Graceful FFmpeg shutdown (SIGINT ? SIGTERM ? SIGKILL)
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

## ?? License

MIT License - See [LICENSE](LICENSE) for details.

---

## ?? Contributing

Contributions welcome! Please open an issue or submit a PR.

---

## ?? Support

- **Issues:** [GitHub Issues](https://github.com/McGeaverBeaver/VantageCamLive/issues)
- **Demo:** [https://simcoelocal.com/](https://simcoelocal.com/)