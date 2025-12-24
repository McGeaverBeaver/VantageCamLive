# Vantage Cam Live
**OpenSource Automated Live Stream Broadcaster with Weather & Sponsors Overlay**

See a demo @ [https://simcoelocal.ca/](https://simcoelocal.ca/)

Transform a standard security camera feed into a professional broadcast without the hassle. Vantage Cam Live runs entirely in Docker and handles all the heavy lifting for you:

* **⚡ Automated Production:** Overlays real-time weather and rotating sponsor logos automatically.
* **📺 Universal Fit:** Smart "letterboxing" fixes aspect ratios, so even ultra-wide cameras look perfect on YouTube.
* **🚀 Set & Forget:** Once configured, it runs 24/7 with no maintenance required.
---
### 🌟 Key Features

* **Universal Compatibility:** Automatically resizes and "letterboxes" any camera input (Wide, Ultrawide, Standard) to a perfect 1080p YouTube-ready format.
* **Live Weather Overlay:** Real-time local weather updates powered by Open-Meteo, displayed elegantly in the corner.
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
└── weather_icons/  <-- Place your weather icons here
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
      - WEATHER_LAT=40.7128
      - WEATHER_LON=-74.0060
      - WEATHER_LOCATION=My City
      - WEATHER_TIMEZONE=America/New_York
      - YOUTUBE_URL=rtmp://a.rtmp.youtube.com/live2
      - YOUTUBE_KEY=xxxx-xxxx-xxxx-xxxx
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
