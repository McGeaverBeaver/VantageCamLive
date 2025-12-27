# Vantage Cam Live v2.6
**Optional Hardware Acceleration, Alert Timestamps & Performance Optimizations**

---

## 🎉 New Features

### Optional Hardware Acceleration
**The #1 requested feature!** VantageCam now supports software-only encoding, removing the Intel QuickSync requirement.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `HARDWARE_ACCEL` | `true` | Set to `false` to use CPU encoding (no Intel GPU required) |
| `SOFTWARE_PRESET` | `faster` | x264 speed preset: `ultrafast`, `superfast`, `veryfast`, `faster`, `fast`, `medium` |
| `SOFTWARE_CRF` | `23` | Quality level (lower = better quality, 18-28 typical range) |

- **Auto-Fallback:** If VAAPI device is missing or fails initialization, the container automatically switches to software encoding instead of crashing.
- **Broader Compatibility:** Now works on AMD, ARM, cloud VMs, or any system without Intel integrated graphics.

> ⚠️ **Note:** Software encoding uses significantly more CPU. For 1440p streaming, expect 2-4 CPU cores at moderate-high usage depending on preset.

### Alert "Issued" Timestamps
Weather alerts now display the official issued time directly on the overlay, giving viewers critical context about when the warning was issued.

- **Environment Canada:** Extracts the `<summary>` tag from official XML feeds to retrieve the exact issued time (e.g., *"Issued: 8:12 PM EST Friday..."*).
- **Dynamic Text Scaling:** Timestamp text automatically resizes to fit the screen width, ensuring it never runs off the edges.
- **Three-Line Layout:** Alert box now displays Region (top), Warning (middle), and Timestamp (bottom) in a clean, readable format.
- **NWS Compatible:** US National Weather Service alerts maintain compatibility with the new data structure.

---

## ⚡ Performance Optimizations

### Combined Weather + Alert Overlay
- Weather and alert boxes are now pre-composited into a **single overlay image** in Python before being sent to FFmpeg.
- **Result:** Reduces FFmpeg overlay operations from 4 to 3, lowering GPU/CPU overhead.

### Intelligent Caching
- **Font Caching:** Fonts are now loaded once and reused across all renders (previously reloaded every 15 minutes).
- **Icon Caching:** Weather icons are cached in memory after first load, eliminating repeated disk reads.
- **Hash-Based Ad Updates:** Ad images are only re-processed if the source file has actually changed (detected via MD5 hash).

---

## 🛠️ Improvements

- **Graceful Shutdown:** Proper signal handling ensures clean termination of all background processes.
- **Timestamped Logging:** All log messages now include timestamps for easier debugging.
- **Health Check Endpoint:** Container includes a health check for better orchestration support (Docker Compose, Kubernetes, Unraid).
- **Organized Unraid Template:** Settings grouped logically with hardware options at top; advanced settings hidden by default.
- **Refactored Alert Layout:** Three-line layout (Region, Warning, Timestamp) with improved vertical spacing.

---

## 📋 New Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `HARDWARE_ACCEL` | `true` | Enable/disable Intel QuickSync VAAPI encoding |
| `SOFTWARE_PRESET` | `faster` | x264 preset (only used when `HARDWARE_ACCEL=false`) |
| `SOFTWARE_CRF` | `23` | x264 quality (only used when `HARDWARE_ACCEL=false`) |
| `VIDEO_FPS` | `30` | Output framerate (was hardcoded) |
| `VAAPI_DEVICE` | `/dev/dri/renderD128` | Override VAAPI device path (advanced) |

---

## 🐛 Bug Fixes

- Fixed potential race condition when updating ad overlays during mode transitions (DAY→NIGHT).
- Improved error handling in weather API calls to prevent overlay corruption on network timeouts.
- Alert timestamps now strip HTML tags from XML feed data for clean display.

---

## 📦 Docker Changes

### New Build Argument

```dockerfile
# Build with Intel drivers (default)
docker build -t vantagecam:latest .

# Build without Intel drivers (smaller image for software-only)
docker build --build-arg INCLUDE_INTEL=false -t vantagecam:software .
```

### Compose Example (Software Mode)

```yaml
vantagecam:
  image: ghcr.io/mcgeaverbeaver/vantagecamlive:latest
  container_name: vantagecam
  # NO devices section needed for software mode
  environment:
    - HARDWARE_ACCEL=false
    - SOFTWARE_PRESET=faster
    - RTSP_SOURCE=rtsp://user:pass@192.168.1.50:554/stream
    - ADMIN_USER=admin
    - ADMIN_PASS=change_me_please
    - WEATHER_LAT=40.7128
    - WEATHER_LON=-74.0060
    - WEATHER_LOCATION=My City
    - WEATHER_TIMEZONE=America/New_York
  volumes:
    - /mnt/user/appdata/vantagecam:/config
  ports:
    - 8554:8554
    - 9998:9998
  restart: unless-stopped
```

---

## ⬆️ Upgrade Notes

1. **No breaking changes** - All existing configurations continue to work as-is.
2. If you're currently using Intel QuickSync, no action needed.
3. To switch to software encoding, simply add `HARDWARE_ACCEL=false` to your environment variables and optionally remove the `/dev/dri` device mapping.

---

## 📥 Downloads

- **Full Package:** `vantagecam-optimized.zip` (includes all updated files)
- **Updated Files:**
  - `start.sh` - Main entrypoint with hardware detection
  - `weather.py` - Optimized overlay generation
  - `Dockerfile` - Optional Intel driver build
  - `compose.yaml` - Updated with new variables
  - `my-VantageCamLive.xml` - Unraid template

---

**Full Changelog:** [v2.5...v2.6](https://github.com/mcgeaverbeaver/vantagecamlive/compare/v2.5...v2.6)

---

## 👨‍💻 Developer Notes

### weather.py Changes
| Function | Change |
| :--- | :--- |
| `fetch_title_from_xml` | Renamed to `fetch_title_and_time_from_xml`. Now extracts `<summary>` tag for issued time. |
| `fetch_ec_alert` | Updated to return `issued_text` alongside title and color. |
| `fetch_nws_alert` | Return values updated to maintain compatibility with new 3-tuple structure. |
| `generate_alert_layer` | Refactored for 3-line layout. Region at y=10, Warning centered, Timestamp at y=110. |
| `generate_weather_layer` | New function - generates weather as PIL Image (not saved to disk). |
| `generate_combined` | New function - pre-composites weather + alerts into single overlay. |
