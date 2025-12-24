
# Vantage Cam Live v2.0
**OpenSource Automated Live Stream Broadcaster with Weather & Sponsors Overlay**

See a demo @ [https://simcoelocal.ca/](https://simcoelocal.ca/)

Transform a standard security camera feed into a professional broadcast without the hassle. Vantage Cam Live runs entirely in Docker and handles all the heavy lifting for you:

* **⚡ Automated Production:** Overlays real-time weather and rotating sponsor logos automatically.
* **📺 Universal Fit:** Smart "Fill" scaling fixes aspect ratios, so even 4:3 or ultra-wide cameras look perfect on YouTube (No more black bars!).
* **🚀 Set & Forget:** Once configured, it runs 24/7 with self-healing assets and no maintenance required.
---
### 🌟 Key Features

* **Resolution Unlocked:** Stream in crisp **1440p (2K)** by default, or configure for 1080p/4K. No longer limited to low-res streams.
* **Smart Scaling Engine:** The new `SCALING_MODE` automatically zooms and crops 4:3 camera signals to fill a 16:9 frame, eliminating "windowboxing" (black bars) on desktop viewers.
* **Live Weather Overlay:** Real-time local weather updates powered by Open-Meteo with **Self-Healing Assets** (icons are automatically downloaded/repaired on boot).
* **Dynamic Sponsor System:** "Watch folders" allow you to drag-and-drop sponsor logos for automatic rotation (Day/Night support) without restarting the stream.
* **Audio Control API:** Mute or unmute your stream remotely using simple web commands.
* **Hardware Accelerated:** Uses Intel QuickSync (VAAPI) for ultra-low CPU usage.

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
**2. Quick Start**
Copy the my-VantageCamLive.xml on UnRAID -> /boot/config/plugins/dockerMan/templates-user 
Navigate in Unraid to Docker, and click Add Container. Find in the list VantageCamLive. Update variables , run & enjoy.

```
#### 2. Configuration & Launch
Copy the following configuration into your Docker Compose file.

```yaml
version: "3"
services:
  vantagecam:
    image: ghcr.io/mcgeaverbeaver/vantagecamlive:latest
    container_name: vantagecam
    devices:
      - /dev/dri:/dev/dri # Intel QuickSync (Required)
    environment:
      - RTSP_SOURCE=rtsp://user:pass@192.168.1.50:554/stream
      - ADMIN_USER=admin
      - ADMIN_PASS=change_me_please
      - ENABLE_LOCAL_STREAM=true # Enable local viewing on port 8554
      
      # Weather Settings
      - WEATHER_LAT=40.7128
      - WEATHER_LON=-74.0060
      - WEATHER_LOCATION=My City
      - WEATHER_TIMEZONE=America/New_York
      
      # YouTube Settings
      - YOUTUBE_URL=rtmp://[a.rtmp.youtube.com/live2](https://a.rtmp.youtube.com/live2)
      - YOUTUBE_KEY=xxxx-xxxx-xxxx-xxxx
      - YOUTUBE_WIDTH=2560  # Default 1440p
      - YOUTUBE_HEIGHT=1440 # Default 1440p
      - SCALING_MODE=fill   # 'fill' removes black bars, 'fit' adds padding
      
    volumes:
      - /mnt/user/appdata/vantagecam:/config
    ports:
      - 8554:8554 # Video Output
      - 9998:9998 # Audio API
    restart: unless-stopped
```
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

| Variable | Default | Description |
| :--- | :--- | :--- |
| `SCALING_MODE` | `fill` | Set to `fill` to zoom/crop 4:3 cameras to 16:9. Set to `fit` to keep original ratio with bars. |
| `YOUTUBE_WIDTH` | `2560` | Output video width (2560 for 1440p, 1920 for 1080p). |
| `YOUTUBE_HEIGHT` | `1440` | Output video height. |
| `YOUTUBE_BITRATE` | `4500k` | Upload bitrate. Increase for 1440p/4K streams (e.g., `8000k`). |
| `ENABLE_LOCAL_STREAM` | `false` | Set to `true` to enable local RTSP viewing (Port 8554). |
| `AUDIO_API_KEY` | *None* | **Recommended:** Set a password/key to secure the Audio API. |
| `VIDEO_BITRATE` | `14M` | Output stream quality. |
| `SCALE_TL` | `500` | Max width (px) of Top-Left images. |
| `SCALE_TR` | `400` | Max width (px) of Top-Right images. |
| `DAY_START_HOUR` | `6` | Hour (0-23) when Day mode begins. |
| `DAY_END_HOUR` | `20` | Hour (0-23) when Night mode begins. |
| `OVERLAYAD_ROTATE_TIMER` | `30` | How many seconds each Top-Left ad displays. |
---

### 🎛️ Audio Control API

You can mute or unmute the YouTube stream remotely (e.g., via Home Assistant or a Stream Deck). If you set an `AUDIO_API_KEY`, you must provide it in the header.

| Action | Command Example (with API Key) |
| :--- | :--- |
| **Check Status** | `curl -H "X-API-Key: YOUR_KEY" http://YOUR_IP:9998/audio/status` |
| **Enable Audio** | `curl -X POST -H "X-API-Key: YOUR_KEY" http://YOUR_IP:9998/audio/unmute` |
| **Mute Audio** | `curl -X POST -H "X-API-Key: YOUR_KEY" http://YOUR_IP:9998/audio/mute` |
| **Toggle** | `curl -X POST -H "X-API-Key: YOUR_KEY" http://YOUR_IP:9998/audio/toggle` |
---
