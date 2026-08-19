# VantageCam Live v2.11.0

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
- [What's New in v2.11.0](#-whats-new-in-v2110)
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
- **Simulcast** — Push the same encode to Facebook/Twitch/anything RTMP alongside YouTube

### Broadcast Operations *(v2.10+)*
- **Admin WebUI** — One-page dashboard with live preview, start/stop, and visibility control
- **Solar Day/Night** — Sponsor rotation follows real sunrise/sunset, not a fixed clock
- **Auto-Unlist on Outage** — Hide the broadcast while the BRB screen is up, restore it on recovery
- **Sponsor Scheduling & Reporting** — Run-date windows per logo, impression/airtime totals, CSV export
- **Event Timeline & Sparklines** — See *when* things happened and how bitrate/FPS behaved

### Reliability *(v2.8+)*
- **Self-Healing Watchdog** — Auto-detects failures and recovers streams
- **"We'll Be Right Back" Mode** — Keeps YouTube alive during camera outages
- **Zombie Killer** — Detects frozen streams even when process is alive
- **RTSP Health Check** — Verifies camera is reachable before restart attempts
- **Exponential Backoff** — Smart retry delays prevent hammering YouTube
- **Auto-PUBLIC** — Restores stream visibility after recovery via YouTube API
- **Discord Alerts** — Instant notifications for offline/recovery/errors

---

## 🚀 What's New in v2.11.0

### 🌅 Sunrise/Sunset Day–Night Switching
A fixed `DAY_END_HOUR=20` is an hour early in June and three hours late in December.
Set `DAY_NIGHT_MODE=sun` and sponsor rotation follows **real solar times** for your
`WEATHER_LAT`/`WEATHER_LON` instead:

- Times come from Open-Meteo (no API key — same source as the weather overlay) and are
  cached per day, so it's **one HTTP call every 24 hours**.
- `SUN_OFFSET_MINUTES=30` switches 30 minutes *after* sunrise and *before* sunset — cameras
  usually go unusably dark before astronomical sunset.
- Any failure (no network, bad coordinates, polar latitudes) **falls back to the clock
  schedule**, so the overlays can never get stuck in the wrong mode.
- **Admin WebUI → Schedule & Airtime** shows which set is airing right now, today's
  sunrise/sunset, and says so plainly when it had to fall back to the clock.

### 🙈 Automatic Visibility During Outages
Viewers arriving from search should never land on a "technical difficulties" card. With
`AUTO_VISIBILITY_ENABLED=true`, the watchdog moves the broadcast to `OUTAGE_VISIBILITY`
(default `unlisted`) once the BRB screen has been up longer than `OUTAGE_GRACE_SECONDS`,
then **restores the visibility it found before the outage** after the camera has been
healthy for `RECOVERY_GRACE_SECONDS`.

Both grace periods mean a 20-second camera blip changes nothing, and the change is applied
once per state flip — never re-applied in a loop. Off by default; needs the YouTube API
credentials you already need for auto-PUBLIC.

### 📅 Sponsor Scheduling & Airtime Reporting
Sponsors are a paid product, so the software now tracks them like one. In **Admin WebUI →
Sponsors** each logo gets:

- **Run dates** (`start` / `end`) and an enable toggle — a logo outside its window is simply
  not loaded into the rotation, no need to move files around at midnight
- **Impressions and airtime** — how many times it was shown and for how long, all-time and
  over a rolling window
- **CSV export** — hand the advertiser a report: `GET /api/sponsors/report.csv?days=30`

Airtime accounting is `flock`-protected, so the concurrent writers behind the two overlay
slots can't lose counts.

### 🕒 Event Timeline
`/config/events.jsonl` now records **what happened and when** — boot, encoder start/failure,
camera down/up, BRB enter/exit, operator start/stop, audio changes, visibility changes,
solar mode switches. The Dashboard renders it as a timeline, so "it dropped again last
night" becomes a timestamp instead of a log-scrolling expedition. The file is self-trimming
(300 KB / 3000 lines) and control characters are stripped, so every line stays valid JSON.

### 📈 Bitrate & FPS Sparklines
The dashboard samples the encoder every 5 seconds and keeps 15 minutes of history. The
stat tiles now carry sparklines with a hover readout, and gaps are drawn as gaps — a
break in the line *is* the outage, which is exactly what you want to see at a glance.

### 📡 Simulcast to Facebook / Twitch / Anywhere
`SIMULCAST_URLS` takes a comma-separated list of complete RTMP URLs (each including its own
key). The encoder switches to FFmpeg's `tee` muxer with `onfail=ignore` on **every** leg, so
a dead Facebook endpoint can never take the YouTube broadcast down with it — FFmpeg logs
`continuing with 1/2 slaves` and YouTube keeps receiving frames. Simulcast keys are scrubbed
from the logs alongside the YouTube key.

---

## 🚀 What's New in v2.10.0

### 🎛️ Broadcast Controls — Start, Stop and Visibility
The dashboard now controls the broadcast itself, not just the encoder process:

- **Start / Stop Broadcast** — Stop really means stopped. It writes `/config/stream_paused`,
  which the supervisor, the watchdog and the Docker healthcheck all honour, so nothing
  respawns the encoder behind your back and the container is not marked unhealthy. The
  stop persists across container restarts.
- **Visibility switch** — flip the live broadcast between **Public / Unlisted / Private**
  straight from the dashboard (requires the YouTube API credentials you already need for
  the watchdog's auto-PUBLIC feature).
- **Live viewer count and broadcast title**, polled on a slow timer to respect the API quota.

### 🖥️ One-Page Dashboard
Live Preview and Broadcast Control now sit side by side at the top of the Dashboard, with
health cards underneath — no more hopping between two pages to see the picture and act on it.

### 🧹 Internal
`youtube_api.py` factors the OAuth/token/broadcast logic out of `watchdog.py` so the watchdog
and the WebUI share one implementation with consistent error classification.

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

### The Pages

| Page | What it's for |
|:-----|:--------------|
| **Dashboard** | Live preview and broadcast controls side by side, then health: bitrate/FPS/speed sparklines, camera, watchdog, system, and the event timeline |
| **Overlay Layout** | Drag and resize the sponsor and weather overlays on a scale model of the frame, then save (and optionally apply, which restarts the encoder) |
| **Sponsors** | Upload, preview and delete logos per slot and Day/Night mode |
| **Schedule & Airtime** | Run windows per logo, impression and airtime totals, CSV export, and which set is airing right now |
| **Weather & Alerts** | The rendered overlay PNGs straight from disk, plus an on-demand regenerate |
| **Audio** | Mute / camera audio / music playlist |
| **Diagnostics** | Ingest connection probe (DNS → TCP → TLS), stream-key sanity check, restart and retry-now controls |
| **Logs** | Tail `watchdog`, `ffmpeg` and `weather` logs with the stream key scrubbed out |
| **Settings** | The effective configuration as the container actually sees it |

### Broadcast Controls

- **Start / Stop Broadcast** — Stop writes `/config/stream_paused`, which the supervisor,
  the watchdog and the Docker healthcheck all honour, so nothing respawns the encoder
  behind your back and the container is not marked unhealthy. It persists across restarts.
- **Visibility** — flip the live broadcast between Public / Unlisted / Private (needs the
  YouTube API credentials).
- **Restart** — bounce the encoder without touching the broadcast.
- **Retry now** — cancel a pending watchdog backoff instead of waiting out the delay.
- Live **viewer count** and broadcast title, polled slowly to respect the API quota.

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
| `/api/health` | GET | Liveness probe (no auth) |
| `/api/status` | GET | Full status JSON (stream, camera, audio, watchdog, day/night, preview, system) |
| `/api/config` | GET | Effective configuration as the container sees it |
| `/api/preview/start?source=auto\|camera\|brb` | POST | Start the preview pipeline |
| `/api/preview/stop` | POST | Stop it (frees the CPU immediately) |
| `/api/preview/stream` | GET | MJPEG stream |
| `/api/preview/snapshot` | GET | Single JPEG frame |
| `/api/audio/{mute,unmute,music,toggle}` | POST | Audio control |
| `/api/stream/restart` | POST | Restart the broadcast FFmpeg |
| `/api/weather/refresh` | POST | Regenerate the weather overlay now |
| `/api/ads` / `/api/ads/upload` / `/api/ads/delete` | GET/POST | Sponsor logo management |
| `/api/ads/image?slot=&mode=&name=` | GET | One sponsor logo (thumbnails in the UI) |
| `/api/logs?name=watchdog\|ffmpeg\|weather` | GET | Tail logs |
| `/api/overlay/{weather,tl,tr,fallback}` | GET | Current overlay PNGs (zero CPU) |
| `/api/layout` | GET/POST | Overlay positions (`?apply=true` also restarts the encoder) |
| `/api/layout/reset` | POST | Restore default corner positions |
| `/api/ingest/check` | POST | DNS → TCP → TLS probe of the configured ingest |
| `/api/stream/start` \| `/api/stream/stop` | POST | Start/stop broadcasting (persists across restarts) |
| `/api/stream/retry-now` | POST | Cancel a pending watchdog backoff |
| `/api/youtube/broadcast` | GET | Current broadcast: title, visibility, viewers |
| `/api/youtube/privacy` | POST | `{"privacy":"public\|unlisted\|private"}` |
| `/api/events?limit=N` | GET | Event timeline (newest first, max 500) |
| `/api/metrics/history` | GET | Bitrate/FPS/speed samples for the sparklines |
| `/api/sponsors?days=N` | GET | Per-logo schedule, impressions and airtime |
| `/api/sponsors/report.csv?days=N` | GET | The same report as a CSV download |
| `/api/sponsors/schedule` | POST | Set a logo's enable flag, run dates and note |

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
| **All ok**, stream still won't start | The network path is fine, so the ingest is rejecting the *session* | Reset the key in YouTube Studio; make sure only one encoder is running |
| **Stream key format** flagged | An invisible character (usually a `\r` from editing a template) is in `YOUTUBE_KEY` | Re-paste the key with no trailing space or newline |

### Why the FFmpeg error alone can't tell you

With `rtmps://`, FFmpeg tunnels the **entire** RTMP session — handshake, connect,
and publish (which is where the stream key is sent) — through one `tls://` context.
Every read or write in that session reports failure through the same TLS error path,
so a message like:

```
[tls @ ...] IO error: End of file
Error opening output files: I/O error
```

means only *"the ingest closed the connection at some point"*. It does **not** tell you
whether that happened during the TLS handshake (network interception) or after your key
was sent (key rejected). Do not conclude "it's not the key" from this message.

To actually localise it, publish a synthetic test with verbose logging and no camera,
overlays or competing publisher:

```bash
docker stop vantagecam
docker run --rm --entrypoint ffmpeg ghcr.io/mcgeaverbeaver/vantagecamlive:latest \
  -hide_banner -loglevel verbose -re \
  -f lavfi -i testsrc2=s=1280x720:r=30 -f lavfi -i anullsrc=cl=stereo:r=44100 \
  -c:v libx264 -preset veryfast -b:v 2500k -g 60 -c:a aac -b:a 128k -t 30 \
  -f flv "$YOUTUBE_URL/YOUR_KEY"
```

| What you see | Meaning |
|:-------------|:--------|
| It streams, and YouTube Studio shows a preview | Key and ingest are both fine — the container's retry loop was the problem |
| RTMP lines (`Handshaking...`, `Server version`) **before** the EOF | TLS came up; YouTube rejected the **session** → reset the stream key |
| EOF with **no** RTMP lines at all | The TLS transport is being cut → network interception; try `rtmp://` on 1935 |

Stopping the container first is essential — a second publisher on the same key produces
the middle result and will mislead you.

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
│   │   ├── DAY/            # Daytime sponsor logos
│   │   └── NIGHT/          # Nighttime sponsor logos
│   ├── topright/
│   │   ├── DAY/
│   │   └── NIGHT/
│   ├── sponsors.json       # Run windows per logo (set in the WebUI)
│   └── sponsor_stats.json  # Impression + airtime counters
├── music/               # MP3 files for music streaming mode
├── weather_icons/       # Auto-downloaded weather icons
├── watchdog.log         # Self-healing activity log
├── ffmpeg.log           # FFmpeg stderr, stream key scrubbed (viewable in the WebUI)
├── events.jsonl         # Event timeline, self-trimming
├── watchdog_state.json  # Persistent watchdog state
├── overlay_layout.json  # Overlay positions saved from the WebUI
├── sun_times.json       # Cached sunrise/sunset for today
├── day_night            # Resolved "DAY" or "NIGHT"
├── audio_mode           # Current audio: "muted", "unmuted", or "music"
├── stream_mode          # Current mode: "normal" or "fallback"
└── stream_paused        # Present only while the broadcast is stopped from the WebUI
```

> Delete `stream_paused` (or press **Start Broadcast**) to resume a broadcast that was
> stopped from the dashboard — the stop is deliberately persistent across restarts.

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
      
      # === YOUTUBE API (Optional - for auto-PUBLIC, visibility control, viewer count) ===
      # - YOUTUBE_CLIENT_ID=xxxxx.apps.googleusercontent.com
      # - YOUTUBE_CLIENT_SECRET=GOCSPX-xxxxx
      # - YOUTUBE_REFRESH_TOKEN=1//xxxxx

      # === ADMIN WEBUI (dashboard + preview, port 9999) ===
      - ADMIN_WEBUI_ENABLED=true
      # - PREVIEW_LOW_CPU=false   # true = keyframes only, big CPU saving on 4K cams

      # === DAY / NIGHT SWITCHING ===
      # "sun" (default) follows real sunrise/sunset for WEATHER_LAT/LON;
      # "clock" keeps the fixed DAY_START_HOUR/DAY_END_HOUR schedule.
      # - DAY_NIGHT_MODE=sun
      # - SUN_OFFSET_MINUTES=0

      # === SIMULCAST (Optional) ===
      # Complete URLs including each service's own key. A failing destination
      # can never take the YouTube broadcast down with it.
      # - SIMULCAST_URLS=rtmp://live-api-s.facebook.com:80/rtmp/FB-KEY

      # === AUTOMATIC VISIBILITY (Optional, needs the YouTube API creds above) ===
      # Unlist the broadcast while the BRB screen is up, restore it on recovery.
      # - AUTO_VISIBILITY_ENABLED=true
      # - OUTAGE_VISIBILITY=unlisted
      # - HEALTHY_VISIBILITY=public

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
      - ADMIN_USER=admin
      - ADMIN_PASS=change_me_please
      # ... (same as above)
    volumes:
      - /mnt/user/appdata/vantagecam:/config
    ports:
      - 9998:9998  # Audio API
      - 9999:9999  # Admin WebUI
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
│   ├── DAY/      # sunrise → sunset (or DAY_START_HOUR → DAY_END_HOUR)
│   └── NIGHT/    # sunset → sunrise
└── topright/
    ├── DAY/
    └── NIGHT/
```

Which folder is airing is decided by `DAY_NIGHT_MODE` — solar times by default, the fixed
clock schedule if you set `clock`. **Admin WebUI → Schedule & Airtime** shows the current
answer and today's sunrise/sunset.

### Supported Formats
- PNG (recommended - supports transparency)
- JPEG
- WebP

### Behavior

| Position | Rotation | Notes |
|:---------|:---------|:------|
| Top-Left | Every 30s (configurable) | Always visible |
| Top-Right | Show 20s, hide 5 min | Periodic display |

> With `DAY_NIGHT_MODE=sun` the DAY/NIGHT folders switch at real sunrise/sunset for your
> coordinates instead of the fixed `DAY_START_HOUR`/`DAY_END_HOUR` clock.

### Scheduling & Reporting *(v2.11+)*

**Admin WebUI → Sponsors** manages the campaign side without touching the filesystem:

- **Enable / disable** a logo without deleting it
- **Run dates** — `start` and `end` (`YYYY-MM-DD`, either may be blank for open-ended).
  A logo outside its window is skipped when the rotation playlist is built.
- **Note** — free text, e.g. the invoice number or contact
- **Impressions & airtime** — counted as the logo is actually displayed, all-time and over
  a rolling window (default 30 days)
- **CSV export** — `Download report` in the UI, or
  `curl -u admin:pass http://host:9999/api/sponsors/report.csv?days=30 -o report.csv`

Schedules live in `/config/ads/sponsors.json` and stats in `/config/ads/sponsor_stats.json`;
both are updated under a file lock, so the two overlay slots can't clobber each other.

---

## ⚙️ Advanced Configuration

Every variable the container reads is listed below, with the default that is actually
compiled in. Anything not listed here is internal and not configurable.

### Required

| Variable | Default | Description |
|:---------|:--------|:------------|
| `RTSP_SOURCE` | `rtsp://192.168.1.100:8554/stream` | Your camera's RTSP URL. The placeholder default will not work — set this. |
| `ADMIN_USER` | `cam_admin` | Username for the Admin WebUI and the internal RTSP auth |
| `ADMIN_PASS` | `your_secure_password` | Password for both. **The WebUI refuses every request while this is unset or left at a shipped default** (`your_secure_password`, `change_me_please`). |
| `YOUTUBE_KEY` | - | Stream key. Without it the container still runs (preview, overlays, weather) but publishes nothing. |

### User Permissions

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PUID` | `0` (root) | User ID for file ownership |
| `PGID` | `0` (root) | Group ID for file ownership |

> **Unraid Users:** Set `PUID=99` and `PGID=100` to match the "nobody:users" standard.

### Video Output

| Variable | Default | Description |
|:---------|:--------|:------------|
| `HARDWARE_ACCEL` | `true` | Use VAAPI encoding (falls back to software automatically if VAAPI fails) |
| `VAAPI_DEVICE` | `/dev/dri/renderD128` | GPU device |
| `SOFTWARE_PRESET` | `faster` | x264 preset — only used when `HARDWARE_ACCEL=false` |
| `SOFTWARE_CRF` | `23` | x264 quality, lower is better — only used when `HARDWARE_ACCEL=false` |
| `SCALING_MODE` | `fill` | `fill` zooms/crops to 16:9, `fit` letterboxes |
| `VIDEO_BITRATE` | `14M` | Internal pipeline bitrate |
| `VIDEO_FPS` | `30` | Framerate |
| `ENABLE_LOCAL_STREAM` | `false` | Publish a local RTSP copy on 8554 via MediaMTX. Leave `false` for direct-to-YouTube (saves CPU/RAM). |

### YouTube

| Variable | Default | Description |
|:---------|:--------|:------------|
| `YOUTUBE_URL` | `rtmp://a.rtmp.youtube.com/live2` | RTMP ingest |
| `YOUTUBE_KEY` | - | Stream key |
| `YOUTUBE_WIDTH` | `2560` | Output width |
| `YOUTUBE_HEIGHT` | `1440` | Output height |
| `YOUTUBE_BITRATE` | `4500k` | Upload bitrate |

### Admin WebUI & Preview

| Variable | Default | Description |
|:---------|:--------|:------------|
| `ADMIN_WEBUI_ENABLED` | `true` | Enable the dashboard |
| `ADMIN_PORT` | `9999` | Port the dashboard listens on |
| `ADMIN_BIND` | `0.0.0.0` | Bind address. Set `127.0.0.1` to expose it only through a reverse proxy on the same host. |
| `PREVIEW_FPS` | `5` | Preview frame rate (1–15) |
| `PREVIEW_WIDTH` | `960` | Preview width in pixels |
| `PREVIEW_QUALITY` | `6` | MJPEG quality (2 best – 31 worst) |
| `PREVIEW_IDLE_TIMEOUT` | `120` | Seconds without viewers before the preview auto-stops |
| `PREVIEW_LOW_CPU` | `false` | Decode keyframes only (~1 fps, big CPU saving on 4K cameras) |

### Fallback Mode

| Variable | Default | Description |
|:---------|:--------|:------------|
| `FALLBACK_ENABLED` | `true` | Show the "We'll Be Right Back" screen when the camera is unreachable |

### Self-Healing Watchdog

The watchdog only starts when `WATCHDOG_ENABLED=true` **and** `YOUTUBE_KEY` is set — with
no key there is no broadcast to watch.

| Variable | Default | Description |
|:---------|:--------|:------------|
| `WATCHDOG_ENABLED` | `false` | Enable watchdog |
| `WATCHDOG_STATUS_URL` | - | Status endpoint URL (see [YouTube API Setup](#-youtube-api-setup-guide)) |
| `WATCHDOG_STARTUP_DELAY` | `180` | Wait before first check (seconds) |
| `WATCHDOG_CHECK_INTERVAL` | `30` | Check interval (seconds) |
| `WATCHDOG_INITIAL_DELAY` | `10` | Initial backoff delay, doubling each failure |
| `WATCHDOG_MAX_DELAY` | `900` | Backoff ceiling (15 min) |
| `WATCHDOG_STABILITY_THRESHOLD` | `30` | Stable seconds required to reset the backoff |
| `WATCHDOG_VERIFICATION_TIMEOUT` | `120` | Time to wait for YouTube to report "live" after a restart |
| `WATCHDOG_RTSP_CHECK` | `true` | Verify the camera is reachable before restarting |
| `WATCHDOG_VERBOSE` | `true` | Detailed logging |

### Discord Notifications

| Variable | Default | Description |
|:---------|:--------|:------------|
| `DISCORD_WEBHOOK_URL` | - | Webhook URL |
| `DISCORD_USER_ID` | - | Your user ID for @mentions |

### YouTube API

Needed for the watchdog's auto-PUBLIC recovery, the dashboard's visibility switch, the
viewer count, and automatic visibility during outages.

| Variable | Default | Description |
|:---------|:--------|:------------|
| `YOUTUBE_CLIENT_ID` | - | OAuth Client ID |
| `YOUTUBE_CLIENT_SECRET` | - | OAuth Client Secret |
| `YOUTUBE_REFRESH_TOKEN` | - | OAuth Refresh Token |

### Weather & Alerts

| Variable | Default | Description |
|:---------|:--------|:------------|
| `WEATHER_ENABLED` | `true` | Render the weather/alert overlay at all |
| `WEATHER_LAT` | `40.7128` | Latitude — also used for sunrise/sunset when `DAY_NIGHT_MODE=sun` |
| `WEATHER_LON` | `-74.0060` | Longitude |
| `WEATHER_LOCATION` | `My City` | Display name on the overlay |
| `WEATHER_TIMEZONE` | `America/Toronto` | Timezone (also sets the container's `TZ`) |
| `CAMERA_HEADING` | `E` (90°) | Direction the camera faces — compass point or degrees |
| `ALERTS_UPDATE_INTERVAL` | `900` | Update interval (seconds) |
| `ALERT_COUNTRY` | auto | Force alert source: `CA` (Environment Canada) or `US` (NWS). Recommended near the border. |
| `FLASH_ON_DURATION` | `0.7` | Seconds an extreme-alert overlay stays lit while flashing |
| `FLASH_OFF_DURATION` | `0.3` | Seconds it stays dark |
| `WEATHER_DEBUG` | `false` | Verbose weather logging |

### Sponsor Overlays

| Variable | Default | Description |
|:---------|:--------|:------------|
| `SCALE_TL` | `500` | Top-left max width (px) |
| `SCALE_TR` | `400` | Top-right max width (px) |
| `OVERLAYAD_ROTATE_TIMER` | `30` | Top-left rotation (seconds) |
| `TR_SHOW_SECONDS` | `20` | Top-right visible time |
| `TR_HIDE_SECONDS` | `300` | Top-right hidden time |
| `DAY_START_HOUR` | `6` | Day mode start — only used when `DAY_NIGHT_MODE=clock` |
| `DAY_END_HOUR` | `20` | Night mode start — only used when `DAY_NIGHT_MODE=clock` |

*Overlay positions and sizes are set in **Admin WebUI → Overlay Layout**, not by variables;
`SCALE_TL`/`SCALE_TR` are the fallback sizes used until you save a layout.*

### Day / Night Switching

| Variable | Default | Description |
|:---------|:--------|:------------|
| `DAY_NIGHT_MODE` | `sun` | `sun` follows real sunrise/sunset for `WEATHER_LAT`/`WEATHER_LON`; `clock` uses the fixed `DAY_START_HOUR`/`DAY_END_HOUR` |
| `SUN_OFFSET_MINUTES` | `0` | Positive switches that many minutes after sunrise and before sunset (a tighter day); negative widens it |

> ⚠️ **Changed in v2.11.0:** the default is now `sun`, so after upgrading your sponsor
> folders switch at real sunrise/sunset instead of 06:00/20:00. Set `DAY_NIGHT_MODE=clock`
> to keep the old fixed schedule.

*Falls back to the clock schedule automatically whenever the solar lookup fails, so a
network outage can never leave the overlays in the wrong mode.*

### Simulcast

| Variable | Default | Description |
|:---------|:--------|:------------|
| `SIMULCAST_URLS` | - | Comma-separated extra RTMP destinations, each a **complete** URL including its own key |

```yaml
- SIMULCAST_URLS=rtmp://live-api-s.facebook.com:80/rtmp/FB-KEY,rtmp://ingest.twitch.tv/app/TW-KEY
```

*Every leg (YouTube included) carries `onfail=ignore` — a destination that refuses the
connection is dropped and the rest keep publishing. Simulcast keys are scrubbed from the
logs just like `YOUTUBE_KEY`.*

### Automatic Visibility

Requires the YouTube API credentials above.

| Variable | Default | Description |
|:---------|:--------|:------------|
| `AUTO_VISIBILITY_ENABLED` | `false` | Hide the broadcast while the BRB screen is up |
| `OUTAGE_VISIBILITY` | `unlisted` | Visibility applied during an outage |
| `HEALTHY_VISIBILITY` | `public` | Fallback restore target if the pre-outage value can't be read |
| `OUTAGE_GRACE_SECONDS` | `120` | How long the outage must persist before hiding |
| `RECOVERY_GRACE_SECONDS` | `120` | How long health must hold before restoring |

### Audio API

| Variable | Default | Description |
|:---------|:--------|:------------|
| `AUDIO_API_KEY` | - | Require `X-API-Key` on the audio endpoints (port 9998). Unset means no auth — keep the port on your LAN. |

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

### v2.11.0 - Solar Switching, Sponsor Reporting, Timeline & Simulcast

**New Features:**
- **Sunrise/sunset day-night switching** (`DAY_NIGHT_MODE=sun`, `SUN_OFFSET_MINUTES`) — sponsor rotation follows real solar times for the camera's coordinates, cached per day, with automatic fallback to the clock schedule on any failure.
- **Automatic visibility during outages** (`AUTO_VISIBILITY_ENABLED`) — the broadcast is unlisted while the BRB screen is up and restored to its previous visibility on recovery, both sides gated by grace periods so brief blips change nothing.
- **Sponsor scheduling and airtime reporting** — per-logo enable/run-dates/notes plus impression and airtime totals, viewable in the WebUI and exportable as CSV.
- **Event timeline** — `/config/events.jsonl` records boot, encoder start/failure, camera down/up, BRB transitions, operator start/stop, audio and visibility changes; rendered as a timeline on the Dashboard. Self-trimming, control characters stripped.
- **Bitrate/FPS sparklines** — 15 minutes of encoder history sampled every 5s, drawn on the stat tiles with a hover readout and real gaps for outages.
- **Simulcast** (`SIMULCAST_URLS`) — publish the same encode to additional RTMP destinations via the `tee` muxer; every leg uses `onfail=ignore`, so a failing destination can't take YouTube down with it. Simulcast keys are scrubbed from the logs.

**New API endpoints:** `/api/events`, `/api/metrics/history`, `/api/sponsors`, `/api/sponsors/report.csv`, `/api/sponsors/schedule`.

### v2.10.0 - Broadcast Controls & One-Page Dashboard

**New Features:**
- **Start/Stop Broadcast** — writes `/config/stream_paused`, honoured by the supervisor, watchdog and Docker healthcheck, and persists across container restarts.
- **Visibility switch** — flip the live broadcast between Public/Unlisted/Private from the dashboard.
- **Live viewer count and broadcast title**, polled on a slow timer to respect the API quota.
- **One-page dashboard** — preview and broadcast controls side by side, health cards underneath.

**Internal:** `youtube_api.py` factors the OAuth/broadcast logic out of `watchdog.py` so the watchdog and WebUI share one implementation.

### v2.9.1 - Overlay Positioning & Ingest Diagnostics

**New Features:**
- **Drag-and-drop overlay positioning** — reposition and resize the sponsor and weather overlays in the WebUI; saved to `/config/overlay_layout.json` (defaults reproduce the old hardcoded corners exactly).
- **Ingest diagnostics** — layered DNS → TCP → TLS probe of the configured ingest (`/api/ingest/check`, `ingest_probe.py`). The stream key is never transmitted.
- **Stream-key sanity check** — reports format problems without revealing the key.
- **Redesigned admin UI** — sidebar navigation instead of one endless page.

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
