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

#### 1. Folder Structure
Before starting, create a folder on your host (e.g., `/mnt/user/appdata/vantagecam`) to store your images. The container will automatically create the sub-folders for you:
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

