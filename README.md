# Vantage Cam Live v2.6
**OpenSource Automated Live Stream Broadcaster with Weather & Smart Alerts**

See a demo @ [https://simcoelocal.ca/](https://simcoelocal.ca/)

Transform a standard security camera feed into a professional broadcast without the hassle. Vantage Cam Live runs entirely in Docker and handles all the heavy lifting for you:

* **⚡ Automated Production:** Overlays real-time weather, active government warnings, and rotating sponsor logos automatically.
* **📺 Universal Fit:** Smart "Fill" scaling fixes aspect ratios, so even 4:3 or ultra-wide cameras look perfect on YouTube (No more black bars!).
* **🚀 Set & Forget:** Once configured, it runs 24/7 with self-healing assets and no maintenance required.

> **💡 HARDWARE OPTIONS:** This container supports both **Intel QuickSync (VAAPI)** hardware encoding and **software (x264)** encoding. Hardware encoding is recommended for best performance, but software mode allows the container to run on AMD, ARM, cloud VMs, or any system without Intel integrated graphics.

---
### 🌟 Key Features

* **Resolution Unlocked:** Stream in crisp **1440p (2K)** by default, or configure for 1080p/4K.
* **Smart Scaling Engine:** The `SCALING_MODE` automatically zooms and crops 4:3 camera signals to fill a 16:9 frame, eliminating "windowboxing" (black bars).
* **Live Weather Overlay:** Real-time local weather updates powered by Open-Meteo with **Self-Healing Assets** (icons are automatically downloaded/repaired on boot).
* **🚨 Smart Alert Stacking:**
    * **Dynamic Layout:** Weather alerts (Environment Canada / NWS) now stack cleanly **on top** of the weather widget, creating a unified information column that keeps your camera view clear.
    * **Deep Data Fetch:** Pulls detailed, region-specific warning titles directly from official XML feeds.
    * **Issued Timestamps:** Alerts display the official "Issued" time (e.g., *"Issued: 8:12 PM EST Friday..."*) with dynamic text scaling to fit perfectly.
    * **High Contrast:** Warnings use high-visibility color schemes (e.g., Black text on Golden Yellow) and auto-scale to fit the box perfectly.
* **🔧 Flexible Encoding:**
    * **Hardware Mode (Default):** Uses Intel QuickSync via VAAPI for minimal CPU usage.
    * **Software Mode:** Falls back to x264 encoding for systems without Intel GPUs.
    * **Auto-Fallback:** Automatically switches to software mode if VAAPI initialization fails.
* **Dynamic Sponsor System:** "Watch folders" allow you to drag-and-drop sponsor logos for automatic rotation (Day/Night support) without restarting the stream.
* **Audio Control API:** Mute or unmute your stream remotely using simple web commands.

---
### 🚀 Getting Started

**1. Folder Structure**
Before starting, create a folder on your host (e.g., `/home/myuser/vantagecam`) to store your images. The container will automatically create the sub-folders for you:

```text
/config/
├── ads/
│   ├── topleft/
│   │   ├── DAY/    <-- Drop Day logos here
│   │   └── NIGHT/  <-- Drop Night logos here
│   └── topright/
│       ├── DAY/
│       └── NIGHT/
└── weather_icons/  <-- Icons auto-download here (Self-Healing)
```

**2. Quick Start (Unraid)**

1.  **Install Template:**
    Copy the provided `my-VantageCamLive.xml` file to your Unraid USB drive at:
    `/boot/config/plugins/dockerMan/templates-user/`
2.  **Add Container:**
    * Navigate to the **Docker** tab in the Unraid WebUI.
    * Click **Add Container** at the bottom.
3.  **Select Template:**
    * Click the **Template** dropdown list.
    * Select **VantageCamLive**.
4.  **Configure & Launch:**
    * Update the required variables (RTSP Source, YouTube Key, Coordinates).
    * Click **Apply**.

---
### 📦 Docker Compose

#### Hardware Encoding (Intel QuickSync)
```yaml
version: "3"
services:
  vantagecam:
    image: ghcr.io/mcgeaverbeaver/vantagecamlive:latest
    container_name: vantagecam
    devices:
      - /dev/dri:/dev/dri # Intel QuickSync
    environment:
      # --- REQUIRED ---
      - RTSP_SOURCE=rtsp://user:pass@192.168.1.50:554/stream
      - ADMIN_USER=admin
      - ADMIN_PASS=change_me_please
      
      # --- HARDWARE ACCELERATION (default: true) ---
      - HARDWARE_ACCEL=true
      
      # --- LOCAL STREAM ---
      - ENABLE_LOCAL_STREAM=true
      
      # --- WEATHER & LOCATION ---
      - WEATHER_LAT=40.7128
      - WEATHER_LON=-74.0060
      - WEATHER_LOCATION=My City
      - WEATHER_TIMEZONE=America/New_York
      - CAMERA_HEADING=E
      
      # --- ALERTS ---
      - ALERTS_UPDATE_INTERVAL=900
      
      # --- YOUTUBE ---
      - YOUTUBE_URL=rtmp://a.rtmp.youtube.com/live2
      - YOUTUBE_KEY=xxxx-xxxx-xxxx-xxxx
      - YOUTUBE_WIDTH=2560
      - YOUTUBE_HEIGHT=1440
      - SCALING_MODE=fill
      
    volumes:
      - /mnt/user/appdata/vantagecam:/config
    ports:
      - 8554:8554 # Video Output
      - 9998:9998 # Audio API
    restart: unless-stopped
```

#### Software Encoding (No GPU Required)
```yaml
version: "3"
services:
  vantagecam:
    image: ghcr.io/mcgeaverbeaver/vantagecamlive:latest
    container_name: vantagecam
    # NO devices section needed
    environment:
      # --- REQUIRED ---
      - RTSP_SOURCE=rtsp://user:pass@192.168.1.50:554/stream
      - ADMIN_USER=admin
      - ADMIN_PASS=change_me_please
      
      # --- SOFTWARE ENCODING ---
      - HARDWARE_ACCEL=false
      - SOFTWARE_PRESET=faster  # ultrafast|superfast|veryfast|faster|fast|medium
      - SOFTWARE_CRF=23         # Quality: lower = better (18-28 typical)
      
      # --- LOCAL STREAM ---
      - ENABLE_LOCAL_STREAM=true
      
      # --- WEATHER & LOCATION ---
      - WEATHER_LAT=40.7128
      - WEATHER_LON=-74.0060
      - WEATHER_LOCATION=My City
      - WEATHER_TIMEZONE=America/New_York
      - CAMERA_HEADING=E
      
      # --- ALERTS ---
      - ALERTS_UPDATE_INTERVAL=900
      
    volumes:
      - /mnt/user/appdata/vantagecam:/config
    ports:
      - 8554:8554
      - 9998:9998
    restart: unless-stopped
```

> ⚠️ **Note:** Software encoding uses significantly more CPU. For 1440p streaming, expect 2-4 CPU cores at moderate-high usage depending on preset.

---

### 📢 Sponsor Management

The system features a **dynamic "watch folder" engine**. You can add, remove, or update sponsor images in real-time without restarting the stream.

* **⚡ Auto-Resizing:**
    Don't worry about pixel dimensions. The system automatically scales any image you drop in (4K, 1080p, or irregular sizes) to fit the overlay area perfectly while maintaining the correct aspect ratio.
* **🔄 Top-Left (Partner Rotation):**
    * *Behavior:* Displays images one by one in a continuous, endless loop.
    * *Best for:* Primary sponsors, partner logos, or station identification.
* **🔔 Top-Right (Popup / Call-to-Action):**
    * *Behavior:* Appears for **20 seconds**, then disappears for **5 minutes** (configurable).
    * *Best for:* Special event announcements, "Like & Subscribe" reminders, or premium spotlight ads.
* **☀️/🌙 Day & Night Modes:**
    The system automatically switches between the `DAY` and `NIGHT` folders based on your configured hours (Default: Day starts at 6 AM, Night starts at 8 PM).
* **Supported Formats:** `.png`, `.jpg`, `.jpeg`

---
### 🛠️ Advanced Configuration

These variables can be added to your Docker template or Compose file to fine-tune the stream.

#### Hardware & Encoding

| Variable | Default | Description |
| :--- | :--- | :--- |
| `HARDWARE_ACCEL` | `true` | Set to `false` for software encoding (no Intel GPU required) |
| `VAAPI_DEVICE` | `/dev/dri/renderD128` | VAAPI render device path (advanced) |
| `SOFTWARE_PRESET` | `faster` | x264 preset when using software encoding: `ultrafast`, `superfast`, `veryfast`, `faster`, `fast`, `medium` |
| `SOFTWARE_CRF` | `23` | x264 quality (lower = better, 18-28 typical). Only used with software encoding. |

#### Video Output

| Variable | Default | Description |
| :--- | :--- | :--- |
| `SCALING_MODE` | `fill` | Set to `fill` to zoom/crop 4:3 cameras to 16:9. Set to `fit` to keep original ratio with bars. |
| `VIDEO_BITRATE` | `14M` | Output stream quality. |
| `VIDEO_FPS` | `30` | Output framerate. |

#### Weather & Alerts

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ALERTS_UPDATE_INTERVAL` | `900` | How often (in seconds) to check for new weather/alerts data. |
| `CAMERA_HEADING` | `N` | Rotates the wind arrow. Accepts compass direction (`N`, `NE`, `SW`) or degrees (`0`-`360`). |
| `WEATHER_DEBUG` | `false` | Set to `true` to enable detailed logs in `/config/weather_debug.log`. |

#### YouTube

| Variable | Default | Description |
| :--- | :--- | :--- |
| `YOUTUBE_WIDTH` | `2560` | Output video width (2560 for 1440p, 1920 for 1080p). |
| `YOUTUBE_HEIGHT` | `1440` | Output video height. |
| `YOUTUBE_BITRATE` | `4500k` | Upload bitrate. Increase for 1440p/4K streams (e.g., `8000k`). |

#### Streaming

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ENABLE_LOCAL_STREAM` | `false` | Set to `true` to enable local RTSP viewing (Port 8554). |
| `AUDIO_API_KEY` | *None* | **Recommended:** Set a password/key to secure the Audio API. |

#### Sponsor Overlays

| Variable | Default | Description |
| :--- | :--- | :--- |
| `SCALE_TL` | `500` | Max width (px) of Top-Left images. |
| `SCALE_TR` | `400` | Max width (px) of Top-Right images. |
| `DAY_START_HOUR` | `6` | Hour (0-23) when Day mode begins. |
| `DAY_END_HOUR` | `20` | Hour (0-23) when Night mode begins. |
| `OVERLAYAD_ROTATE_TIMER` | `30` | How many seconds each Top-Left ad displays. |
| `TR_SHOW_SECONDS` | `20` | How long Top-Right ads are visible. |
| `TR_HIDE_SECONDS` | `300` | How long Top-Right ads are hidden. |

---

### 🎛️ Audio Control API

You can mute or unmute the YouTube stream remotely (e.g., via Home Assistant or a Stream Deck). If you set an `AUDIO_API_KEY`, you must provide it in the header.

| Action | Command Example (with API Key) |
| :--- | :--- |
| **Check Status** | `curl -H "X-API-Key: YOUR_KEY" http://YOUR_IP:9998/audio/status` |
| **Enable Audio** | `curl -X POST -H "X-API-Key: YOUR_KEY" http://YOUR_IP:9998/audio/unmute` |
| **Mute Audio** | `curl -X POST -H "X-API-Key: YOUR_KEY" http://YOUR_IP:9998/audio/mute` |
| **Toggle** | `curl -X POST -H "X-API-Key: YOUR_KEY" http://YOUR_IP:9998/audio/toggle` |
| **Health Check** | `curl http://YOUR_IP:9998/health` |

---

### 📋 Changelog

#### v2.6 - Optional Hardware Acceleration & Alert Timestamps
* **New:** Optional software encoding (`HARDWARE_ACCEL=false`) - no Intel GPU required
* **New:** Auto-fallback to software encoding if VAAPI fails
* **New:** Alert overlays now display "Issued" timestamps with dynamic text scaling
* **Improved:** Combined weather + alert overlay reduces FFmpeg operations
* **Improved:** Font and icon caching for better performance
* **Improved:** Hash-based ad updates (only re-process changed files)
* **Improved:** Graceful shutdown with proper signal handling
* **Fixed:** Race condition during DAY/NIGHT mode transitions

#### v2.5 - Smart Alert Stacking
* Initial release with stacked weather/alert overlays
* Environment Canada and NWS alert support
* Dynamic sponsor rotation system

---
