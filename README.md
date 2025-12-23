# VantageCamLive
OpenSource Professional Live Stream Broadcaster with Weather &amp; Community Sponsors Overlays.

Vantage Cam Live is a "set-it-and-forget-it" Docker container that transforms a standard security camera feed into a professional live broadcast. It handles weather overlays, community sponsor rotation, and YouTube Live streaming with automatic letterboxing—ensuring your stream looks perfect on any screen, regardless of your camera's aspect ratio.

### 🌟 Key Features

* **Universal Compatibility:** Automatically resizes and "letterboxes" any camera input (Wide, Ultrawide, Standard) to a perfect 1080p YouTube-ready format.
* **Live Weather Overlay:** Real-time local weather updates powered by Open-Meteo, displayed elegantly in the corner.
* **Dynamic Sponsor System:** "Watch folders" allow you to drag-and-drop sponsor logos for automatic rotation (Day/Night support) without restarting the stream.
* **Audio Control API:** Mute or unmute your stream remotely using simple web commands.
* **Hardware Accelerated:** Uses Intel QuickSync (VAAPI) for ultra-low CPU usage.

---

### 🚀 Getting Started

1) Folder Structure - Before starting, create a folder on your host (e.g., `/home/myuser/vantagecam`) to store your images. The container will automatically create the sub-folders for you:
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
---
📢 Sponsor Management

The system automatically watches your /config/ads folders. You do not need to restart the container when adding or removing images.
Auto-Resizing: You do not need to resize your images to fit the stream. The system will automatically scale any image you drop in (regardless of resolution) to fit the overlay area while maintaining its correct aspect ratio.
Top-Left (Rotating): These images display one by one in a continuous loop. This spot is ideal for primary partner logos.
Top-Right (Popup): These images appear for 20 seconds and then hide for 5 minutes. This spot is ideal for "Call to Action" messages or special events.
Day/Night Modes: The system automatically switches between the DAY and NIGHT folders based on the hours you define (Default: 6 AM - 8 PM).
Supported Formats: .png, .jpg, .jpeg
---
🛠️ Advanced Configuration
These variables can be added to your Docker template or Compose file to fine-tune the stream.
| Variable                 | Default | Description                                 |
| `VIDEO_BITRATE`          | 14M     | Output stream quality.                      |
| `SCALE_TL`               | 500     | Max width (px) of Top-Left images.          |
| `SCALE_TR`               | 400     | Max width (px) of Top-Right images.         |
| `DAY_START_HOUR`         | 6       | Hour (0-23) when Day mode begins.           |
| `DAY_END_HOUR`           | 20      | Hour (0-23) when Night mode begins.         |
| `OVERLAYAD_ROTATE_TIMER` | 30      | How many seconds each Top-Left ad displays. |
---
🎛️ Audio Control API
You can mute or unmute the YouTube stream remotely (e.g., via Home Assistant or a Stream Deck) using the built-in REST API.
| Action           | Command Example                                   |
| **Check Status** | `curl http://YOUR_IP:9998/audio/status`           |
| **Enable Audio** | `curl -X POST http://YOUR_IP:9998/audio/unmute`   |
| **Mute Audio**   | `curl -X POST http://YOUR_IP:9998/audio/mute`     |
| **Toggle**       | `curl -X POST http://YOUR_IP:9998/audio/toggle`   |
