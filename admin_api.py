#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VantageCam Admin WebUI & API Server
====================================
Serves a browser dashboard (port 9999 by default) that lets the admin:

  - See a live PREVIEW of the exact composed output (camera + ad overlays +
    weather overlay) BEFORE / WHILE it is broadcast to YouTube.
  - Toggle the preview off to save CPU cycles. The preview runs a separate,
    on-demand FFmpeg process (low fps, MJPEG) that never touches the
    broadcast pipeline, and it auto-stops after PREVIEW_IDLE_TIMEOUT seconds
    with no viewers.
  - Monitor stream health: mode (normal/fallback), encoder stats parsed from
    the FFmpeg progress file, watchdog state, RTSP reachability, CPU/RAM.
  - Control audio mode (mute / unmute / music), restart the stream, and
    refresh the weather overlay on demand.
  - Manage sponsor logos (list / upload / delete per slot + day/night).
  - Tail the watchdog / ffmpeg / weather logs.

Security:
  - HTTP Basic auth using ADMIN_USER / ADMIN_PASS (timing-safe comparison).
  - Refuses to serve anything except a setup notice while ADMIN_PASS is
    unset or still one of the shipped defaults.
  - No CORS headers on purpose: same-origin only.

Stdlib-only on purpose (matches the rest of the project - no new deps).
"""

import os
import io
import re
import json
import time
import hmac
import base64
import signal
import shutil
import socket
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import overlay_layout
import scenes
import scene_schedule
import ingest_probe
import youtube_api
import sponsors
import events

# ==============================================================================
#  CONFIGURATION
# ==============================================================================

CONFIG_DIR = os.getenv("VANTAGECAM_CONFIG_DIR", "/config")

ADMIN_USER = os.getenv("ADMIN_USER", "cam_admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "")
ADMIN_PORT = int(os.getenv("ADMIN_PORT", "9999"))
ADMIN_BIND = os.getenv("ADMIN_BIND", "0.0.0.0")

# Passwords that ship in examples/templates - never accept them.
_KNOWN_DEFAULT_PASSWORDS = {"", "your_secure_password", "change_me_please"}

RTSP_SOURCE = os.getenv("RTSP_SOURCE", "")
SCALING_MODE = os.getenv("SCALING_MODE", "fill")
WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "true").lower() == "true"

# "sun" resolves DAY/NIGHT from real sunrise/sunset; anything else is the
# fixed DAY_START_HOUR/DAY_END_HOUR clock schedule.
DAY_NIGHT_MODE = os.getenv("DAY_NIGHT_MODE", "sun").strip().lower()
SCALE_TL = os.getenv("SCALE_TL", "500")
SCALE_TR = os.getenv("SCALE_TR", "400")
YOUTUBE_KEY = os.getenv("YOUTUBE_KEY", "")
YOUTUBE_WIDTH = os.getenv("YOUTUBE_WIDTH", "2560")
YOUTUBE_HEIGHT = os.getenv("YOUTUBE_HEIGHT", "1440")
HARDWARE_ACCEL = os.getenv("HARDWARE_ACCEL", "true").lower() == "true"
ENABLE_LOCAL_STREAM = os.getenv("ENABLE_LOCAL_STREAM", "false").lower() == "true"
WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "false").lower() == "true"
FALLBACK_ENABLED = os.getenv("FALLBACK_ENABLED", "true").lower() == "true"

# Preview tuning
PREVIEW_FPS = max(1, min(15, int(os.getenv("PREVIEW_FPS", "5"))))
PREVIEW_WIDTH = max(320, min(1920, int(os.getenv("PREVIEW_WIDTH", "960"))))
PREVIEW_QUALITY = max(2, min(31, int(os.getenv("PREVIEW_QUALITY", "6"))))
PREVIEW_IDLE_TIMEOUT = max(15, int(os.getenv("PREVIEW_IDLE_TIMEOUT", "120")))
# Low-CPU mode decodes keyframes only (choppier preview, big CPU saving on 4K cams)
PREVIEW_LOW_CPU = os.getenv("PREVIEW_LOW_CPU", "false").lower() == "true"

# Paths shared with start.sh / other components
AUDIO_MODE_FILE = os.path.join(CONFIG_DIR, "audio_mode")
STREAM_MODE_FILE = os.path.join(CONFIG_DIR, "stream_mode")
ENCODER_MODE_FILE = os.path.join(CONFIG_DIR, "encoder_mode")
PID_FILE = os.path.join(CONFIG_DIR, "youtube_restreamer.pid")
PROGRESS_FILE = os.path.join(CONFIG_DIR, "ffmpeg_progress.txt")
WATCHDOG_STATE_FILE = os.path.join(CONFIG_DIR, "watchdog_state.json")
FALLBACK_IMAGE = os.path.join(CONFIG_DIR, "fallback.png")
ADS_BASE = os.path.join(CONFIG_DIR, "ads")
MUSIC_DIR = os.path.join(CONFIG_DIR, "music")

AD_PLAYLIST_TL = os.path.join(CONFIG_DIR, "ad_playlist_tl.txt")
AD_PLAYLIST_TR = os.path.join(CONFIG_DIR, "ad_playlist_tr.txt")
WEATHER_LIST = os.path.join(CONFIG_DIR, "weather_list.txt")
WEATHER_COMBINED = os.path.join(CONFIG_DIR, "weather_combined.png")
WEATHER_COMBINED_FLASH = os.path.join(CONFIG_DIR, "weather_combined_flash.png")
WEATHER_META = os.path.join(CONFIG_DIR, "weather_combined_meta.txt")
AD_FINAL_TL = os.path.join(CONFIG_DIR, "current_ad_tl.png")
AD_FINAL_TR = os.path.join(CONFIG_DIR, "current_ad_tr.png")

LOG_FILES = {
    "watchdog": os.path.join(CONFIG_DIR, "watchdog.log"),
    "ffmpeg": os.path.join(CONFIG_DIR, "ffmpeg.log"),
    "weather": os.path.join(CONFIG_DIR, "weather_debug.log"),
}


def _scrub_secrets(line):
    """Redact the stream key and RTSP credentials from log lines before they
    reach the browser (ffmpeg prints output URLs in error messages)."""
    if YOUTUBE_KEY:
        line = line.replace(YOUTUBE_KEY, "[REDACTED]")
    # Greedy match through the LAST '@' so '@' inside the password is covered
    line = re.sub(r"(rtsps?://)[^/\s]+@", r"\1****@", line)
    return line

# Preview scratch lives in shared memory so it never wears the config disk
PREVIEW_DIR = "/dev/shm/vantagecam_preview" if os.path.isdir("/dev/shm") else "/tmp/vantagecam_preview"
PREVIEW_JPG = os.path.join(PREVIEW_DIR, "preview.jpg")

UI_FILE_CANDIDATES = [
    "/admin_ui.html",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin_ui.html"),
]

ALLOWED_AD_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()-]{0,120}$")

FLASH_ON_DURATION = os.getenv("FLASH_ON_DURATION", "0.7")
FLASH_OFF_DURATION = os.getenv("FLASH_OFF_DURATION", "0.3")


def log(msg):
    print(f"[Admin] {msg}", flush=True)


# ==============================================================================
#  SMALL HELPERS
# ==============================================================================

def read_text(path, default=""):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return default


def pid_is_ffmpeg(pid):
    """True if pid is alive AND is an ffmpeg process (guards PID reuse)."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return b"ffmpeg" in f.read()
    except OSError:
        return False


def get_broadcast_pid():
    try:
        pid = int(read_text(PID_FILE, "0"))
    except ValueError:
        return None
    if pid > 0 and pid_is_ffmpeg(pid):
        return pid
    return None


def proc_start_time(pid):
    """Process start time as a unix timestamp (via /proc)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        starttime_ticks = int(fields[19])  # field 22, minus the 2 consumed before ')'
        hertz = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as f:
            uptime = float(f.read().split()[0])
        boot_time = time.time() - uptime
        return boot_time + starttime_ticks / hertz
    except (OSError, ValueError, IndexError):
        return None


class CpuSampler:
    """Per-process and system CPU%% via /proc deltas between /api/status calls."""

    def __init__(self):
        self.lock = threading.Lock()
        self.prev_total = None
        self.prev_idle = None
        self.prev_procs = {}

    @staticmethod
    def _proc_jiffies(pid):
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return int(fields[11]) + int(fields[12])  # utime + stime

    def sample(self, pids):
        """Returns {pid: cpu_percent} plus overall system percent under key 'system'."""
        out = {}
        try:
            with self.lock:
                with open("/proc/stat") as f:
                    parts = [int(p) for p in f.readline().split()[1:]]
                total = sum(parts)
                idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
                ncpu = os.cpu_count() or 1
                if self.prev_total is not None and total > self.prev_total:
                    dt = total - self.prev_total
                    d_idle = idle - self.prev_idle
                    out["system"] = round(max(0.0, (dt - d_idle) / dt * 100.0), 1)
                    for pid in pids:
                        try:
                            pj = self._proc_jiffies(pid)
                            prev = self.prev_procs.get(pid)
                            if prev is not None and pj >= prev:
                                out[pid] = round((pj - prev) / dt * 100.0 * ncpu, 1)
                            self.prev_procs[pid] = pj
                        except OSError:
                            self.prev_procs.pop(pid, None)
                else:
                    for pid in pids:
                        try:
                            self.prev_procs[pid] = self._proc_jiffies(pid)
                        except OSError:
                            pass
                self.prev_total = total
                self.prev_idle = idle
        except OSError:
            pass
        return out


cpu_sampler = CpuSampler()


class RtspProbe:
    """Cached TCP reachability check of the camera (never hammers it)."""

    def __init__(self, source, ttl=5.0):
        self.ttl = ttl
        self.lock = threading.Lock()
        self.last = 0.0
        self.state = "unknown"
        self.host, self.port = self._parse(source)

    @staticmethod
    def _parse(url):
        """Split on the LAST '@' so '@' inside the password can't shift the host."""
        if not url:
            return None, None
        hostport = url.split("://", 1)[-1].rsplit("@", 1)[-1].split("/", 1)[0]
        if hostport.startswith("["):  # IPv6
            host, _, rest = hostport[1:].partition("]")
            port = int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else 554
            return host or None, port
        if ":" in hostport:
            host, _, p = hostport.rpartition(":")
            return host or None, int(p) if p.isdigit() else 554
        return hostport or None, 554

    def check(self):
        if not self.host:
            return "unknown"
        with self.lock:
            now = time.monotonic()
            if now - self.last < self.ttl:
                return self.state
            try:
                with socket.create_connection((self.host, self.port), timeout=1.5):
                    self.state = "reachable"
            except OSError:
                self.state = "unreachable"
            self.last = now
            return self.state


rtsp_probe = RtspProbe(RTSP_SOURCE)


def parse_progress():
    """Parse the newest key=value block from FFmpeg's -progress file."""
    try:
        size = os.path.getsize(PROGRESS_FILE)
        age = time.time() - os.path.getmtime(PROGRESS_FILE)
        with open(PROGRESS_FILE, "rb") as f:
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    stats = {}
    for line in tail.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            stats[k.strip()] = v.strip()
    out = {"age_seconds": round(age, 1), "file_bytes": size}
    if "frame" in stats:
        out["frame"] = stats.get("frame")
    if "fps" in stats:
        out["fps"] = stats.get("fps")
    if "bitrate" in stats:
        out["bitrate"] = stats.get("bitrate")
    if "speed" in stats:
        out["speed"] = stats.get("speed")
    if "out_time" in stats:
        out["out_time"] = stats.get("out_time")
    elif "out_time_ms" in stats:
        try:
            secs = int(stats["out_time_ms"]) / 1_000_000
            out["out_time"] = time.strftime("%H:%M:%S", time.gmtime(secs))
        except ValueError:
            pass
    return out


RESTART_HOLD_FILE = os.path.join(CONFIG_DIR, "restart_hold")
STREAM_PAUSED_FILE = os.path.join(CONFIG_DIR, "stream_paused")
# MediaMTX mode only: the local encoder that composes the overlays. In that
# mode youtube_restreamer.pid is just the re-streaming leg, which draws nothing.
COMPOSITOR_PID_FILE = os.path.join(CONFIG_DIR, "compositor.pid")
SCENE_LAYER_LIST = os.path.join(CONFIG_DIR, "scene_layer.txt")


def get_compositor_pid():
    try:
        pid = int(read_text(COMPOSITOR_PID_FILE, "0"))
    except ValueError:
        return None
    return pid if pid > 0 and pid_is_ffmpeg(pid) else None


def broadcast_is_paused():
    return os.path.exists(STREAM_PAUSED_FILE)


def stop_broadcast():
    """Stop publishing and keep it stopped (the supervisor honours the flag)."""
    with open(STREAM_PAUSED_FILE, "w") as f:
        f.write(str(int(time.time())))
    pid = get_broadcast_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    log("Broadcast STOPPED by operator")
    events.record("operator_stop", "Broadcast stopped from the WebUI", "warn")
    return True, "Broadcast stopped. It will stay stopped until you press Start."


def start_broadcast():
    """Clear the pause flag (and any pending backoff) so publishing resumes."""
    existed = broadcast_is_paused()
    for path in (STREAM_PAUSED_FILE, RESTART_HOLD_FILE):
        try:
            os.remove(path)
        except OSError:
            pass
    log("Broadcast STARTED by operator")
    events.record("operator_start", "Broadcast started from the WebUI", "success")
    return True, ("Broadcast starting - the encoder comes up within a few seconds."
                  if existed else "Broadcast was already running.")


def signal_broadcast_restart(reason):
    """Ask start.sh's supervision loop to restart the encoder(s).

    start.sh rebuilds the FFmpeg filter graph from the layout on disk before
    every launch, so this is also how a saved overlay layout reaches the air.
    In MediaMTX mode the overlays are drawn by a separate local compositor, so
    that process is signalled as well - restarting only the YouTube leg would
    change nothing visible.
    """
    targets = [(p, name) for p, name in ((get_broadcast_pid(), "broadcast"),
                                          (get_compositor_pid(), "compositor")) if p]
    if not targets:
        return False, "No running broadcast FFmpeg process found"
    try:
        # A short hold marks this as a managed restart so the supervisor skips
        # the fallback-screen detour and respawns in normal mode right away.
        with open(RESTART_HOLD_FILE, "w") as f:
            f.write(str(int(time.time()) + 2))
        for pid, name in targets:
            os.kill(pid, signal.SIGTERM)
            log(f"Sent SIGTERM to {name} ffmpeg pid {pid} ({reason})")
        return True, "Restart signal sent to " + ", ".join(f"{n} PID {p}" for p, n in targets)
    except OSError as e:
        return False, f"Failed to signal FFmpeg: {e}"


def set_audio_mode(mode):
    if mode not in ("muted", "unmuted", "music"):
        return False, "invalid mode"
    with open(AUDIO_MODE_FILE, "w") as f:
        f.write(mode)
    # Don't interrupt the BRB keep-alive stream during a camera outage - audio
    # modes don't apply to it; the saved mode applies when the camera returns.
    if read_text(STREAM_MODE_FILE) == "fallback":
        return True, "Mode saved; applies when the camera stream returns (BRB active)"
    # start.sh polls the file every second in direct mode and restarts on change;
    # nudging FFmpeg makes the switch immediate.
    ok, detail = signal_broadcast_restart(f"audio -> {mode}")
    return True, detail if ok else "Mode saved; stream will pick it up when (re)started"


# ==============================================================================
#  PROGRAM / PREVIEW BUSES
# ==============================================================================

_snap_lock = threading.Lock()
_snap_cache = {"at": 0.0, "failed_at": 0.0, "error": "",
               "path": os.path.join(CONFIG_DIR, "camera_snapshot.jpg")}


def mask_rtsp(text):
    """Never echo camera credentials into the UI or the log."""
    return re.sub(r"//[^/@\s]*:[^/@\s]*@", "//***:***@", text or "")
SNAPSHOT_TTL = 10.0
# A failing grab can take ~10s to give up. Without a cooldown the Broadcast
# page's 5s refresh would pile up an FFmpeg process per poll against a camera
# that is already struggling.
SNAPSHOT_FAIL_COOLDOWN = 30.0


def camera_snapshot(force=False):
    """One JPEG frame straight from the camera, cached briefly.

    The Preview bus needs to show the camera while an away card is on air. A
    whole second MJPEG pipeline for that would double the preview CPU, so a
    single-frame grab every few seconds is used instead.
    """
    path = _snap_cache["path"]
    with _snap_lock:
        now = time.monotonic()
        fresh = now - _snap_cache["at"] < SNAPSHOT_TTL
        if not force and fresh and os.path.exists(path):
            return path
        if not RTSP_SOURCE:
            _snap_cache["error"] = "RTSP_SOURCE is not set"
            return None
        if not force and now - _snap_cache["failed_at"] < SNAPSHOT_FAIL_COOLDOWN:
            # Still in the cooldown after a failure: serve the last good frame
            # if there is one, and keep reporting why rather than hammering.
            return path if os.path.exists(path) else None
        tmp = path + ".tmp"
        # Mirror start.sh's RTSP_INPUT_OPTS. Without discardcorrupt/ignore_err a
        # single lost reference frame aborts the grab, which is exactly what
        # happens on an HEVC camera with any packet loss ("Could not find ref
        # with POC n"). The generous timeout covers waiting for a keyframe on a
        # long-GOP stream.
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-thread_queue_size", "512",
               "-rtsp_transport", "tcp",
               "-buffer_size", "4194304",
               "-max_delay", "500000",
               "-fflags", "+genpts+discardcorrupt",
               "-err_detect", "ignore_err",
               "-timeout", "8000000",
               "-i", RTSP_SOURCE,
               "-frames:v", "1", "-q:v", "4", "-an", tmp]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, timeout=25)
            rc = proc.returncode
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        except subprocess.TimeoutExpired:
            _snap_cache["failed_at"] = time.monotonic()
            _snap_cache["error"] = "the camera did not deliver a frame within 25s"
            return path if os.path.exists(path) else None
        except OSError as e:
            _snap_cache["failed_at"] = time.monotonic()
            _snap_cache["error"] = f"could not run ffmpeg: {e}"
            return path if os.path.exists(path) else None
        if rc == 0 and os.path.exists(tmp):
            os.replace(tmp, path)
            _snap_cache["at"] = time.monotonic()
            _snap_cache["failed_at"] = 0.0
            _snap_cache["error"] = ""
            return path
        # Keep the real reason - "unreachable" is not a diagnosis, and the
        # message is shown in the UI so the operator can act on it.
        last = mask_rtsp(err.splitlines()[-1]) if err else f"ffmpeg exited {rc}"
        _snap_cache["failed_at"] = time.monotonic()
        _snap_cache["error"] = last[:200]
        log(f"Camera snapshot failed: {last[:200]}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return path if os.path.exists(path) else None


def compose_still(bus_target, width=None):
    """Render what a bus would look like, as JPEG bytes.

    Composited in Pillow from the same overlay PNGs and the same layout the
    encoder uses, so it is an honest proof of the composition without paying
    for a second FFmpeg. Returns (bytes, detail) or (None, reason).
    """
    from PIL import Image
    width = width or PREVIEW_WIDTH
    canvas_w, canvas_h = overlay_layout.CANVAS_W, overlay_layout.CANVAS_H
    layout = overlay_layout.load()

    if bus_target == "live":
        snap = camera_snapshot()
        if not snap:
            return None, (_snap_cache.get("error")
                          or "camera snapshot unavailable")
        try:
            with Image.open(snap) as raw:
                cam = raw.convert("RGB")
        except (OSError, ValueError):
            return None, "camera snapshot unreadable"
        # Match the broadcast's fill/fit behaviour so framing is not a surprise
        if SCALING_MODE == "fill":
            scale = max(canvas_w / cam.width, canvas_h / cam.height)
            cam = cam.resize((max(1, int(cam.width * scale)), max(1, int(cam.height * scale))),
                             Image.Resampling.BILINEAR)
            left, top = (cam.width - canvas_w) // 2, (cam.height - canvas_h) // 2
            base = cam.crop((left, top, left + canvas_w, top + canvas_h)).convert("RGBA")
        else:
            scale = min(canvas_w / cam.width, canvas_h / cam.height)
            cam = cam.resize((max(1, int(cam.width * scale)), max(1, int(cam.height * scale))),
                             Image.Resampling.BILINEAR)
            base = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 255))
            base.paste(cam.convert("RGBA"),
                       ((canvas_w - cam.width) // 2, (canvas_h - cam.height) // 2))
    else:
        card = os.path.join(scenes.SCENES_DIR, f"{bus_target}.png")
        if not os.path.exists(card):
            try:
                scenes.render_to_disk(bus_target)
            except Exception:
                return None, f"scene '{bus_target}' could not be rendered"
        try:
            with Image.open(card) as raw:
                base = raw.convert("RGBA").resize((canvas_w, canvas_h))
        except (OSError, ValueError):
            return None, "scene card unreadable"

    # Sponsors and weather sit on top in both buses, matching the pipeline
    for slot, png in (("tl", AD_FINAL_TL), ("tr", AD_FINAL_TR),
                      ("weather", WEATHER_COMBINED)):
        if slot == "weather" and not WEATHER_ENABLED:
            continue
        box = layout.get(slot) or {}
        if not box.get("enabled") or not os.path.exists(png):
            continue
        try:
            with Image.open(png) as raw:
                ov = raw.convert("RGBA")
        except (OSError, ValueError):
            continue
        ratio = min(box["w"] / ov.width, box["h"] / ov.height)
        if ratio <= 0:
            continue
        ov = ov.resize((max(1, int(ov.width * ratio)), max(1, int(ov.height * ratio))),
                       Image.Resampling.LANCZOS)
        base.alpha_composite(ov, (box["x"], box["y"]))

    out = base.convert("RGB")
    out = out.resize((width, max(1, round(width * canvas_h / canvas_w))),
                     Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=82, optimize=True)
    return buf.getvalue(), "ok"


# ==============================================================================
#  PREVIEW PIPELINE
# ==============================================================================

class PreviewManager:
    """
    On-demand FFmpeg that mirrors the broadcast composition (same overlay
    playlists, same canvas + scaling mode) into low-fps MJPEG snapshots.
    Runs only while someone is watching; auto-stops after idle timeout.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.source = "auto"
        self.started_at = None
        self.last_access = 0.0
        self.viewers = 0
        self.last_error = ""
        threading.Thread(target=self._reaper, daemon=True, name="preview-reaper").start()

    # ---- command construction ------------------------------------------------

    def _build_cmd(self, source):
        canvas_w, canvas_h = overlay_layout.CANVAS_W, overlay_layout.CANVAS_H
        fps = 1 if PREVIEW_LOW_CPU else PREVIEW_FPS
        layout = overlay_layout.load()

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]

        if source == "brb":
            # -re: read the looped image at realtime rate, otherwise ffmpeg
            # encodes as fast as it can and burns a full core
            cmd += ["-re", "-loop", "1", "-framerate", str(fps), "-i", FALLBACK_IMAGE]
            base = f"[0:v]scale={canvas_w}:{canvas_h},format=yuv420p[base]"
        else:
            if PREVIEW_LOW_CPU:
                cmd += ["-skip_frame", "nokey"]
            cmd += [
                "-thread_queue_size", "512",
                "-rtsp_transport", "tcp",
                "-buffer_size", "1048576",
                "-max_delay", "500000",
                "-fflags", "+genpts+discardcorrupt",
                "-err_detect", "ignore_err",
                "-timeout", "3000000",
                "-i", RTSP_SOURCE,
            ]
            if SCALING_MODE == "fill":
                base = (f"[0:v]fps={fps},scale={canvas_w}:{canvas_h}:"
                        f"force_original_aspect_ratio=increase:flags=bilinear,"
                        f"crop={canvas_w}:{canvas_h},format=yuv420p[base]")
            else:
                base = (f"[0:v]fps={fps},scale={canvas_w}:{canvas_h}:"
                        f"force_original_aspect_ratio=decrease:flags=bilinear,"
                        f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p[base]")

        # Overlay inputs - identical playlists AND identical positions to the
        # broadcast pipeline, so the preview is a faithful proof of what airs.
        # The scene layer leads, exactly as in start.sh: without it the Program
        # monitor would keep showing the camera while an away card was on air.
        # "auto" mirrors what is going out, so it carries the scene layer and an
        # away card covers the picture. An explicit "camera" pick must NOT: the
        # whole point of choosing it is to check the camera while a card is on
        # air, and painting the card over it makes the camera look dead.
        overlays = []
        if source == "auto" and os.path.exists(SCENE_LAYER_LIST):
            overlays.append((SCENE_LAYER_LIST,
                             f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease",
                             "0:0"))
        for slot, playlist in (("tl", AD_PLAYLIST_TL), ("tr", AD_PLAYLIST_TR),
                               ("weather", WEATHER_LIST)):
            if slot == "weather" and not WEATHER_ENABLED:
                continue
            if not layout[slot]["enabled"]:
                continue
            scale_cmd, coords = overlay_layout.filter_spec(layout, slot)
            overlays.append((playlist, scale_cmd, coords))

        chain = base
        last = "base"
        idx = 1
        for playlist, scale_cmd, coords in overlays:
            cmd += ["-f", "concat", "-safe", "0", "-stream_loop", "-1", "-i", playlist]
            chain += (f";[{idx}:v]{scale_cmd},format=rgba[ovr{idx}]"
                      f";[{last}][ovr{idx}]overlay={coords}:eof_action=pass:shortest=0[v{idx}]")
            last = f"v{idx}"
            idx += 1

        chain += f";[{last}]scale={PREVIEW_WIDTH}:-2[vout]"

        cmd += [
            "-filter_complex", chain,
            "-map", "[vout]", "-an",
            "-q:v", str(PREVIEW_QUALITY),
            "-f", "image2", "-update", "1", "-atomic_writing", "1",
            PREVIEW_JPG,
        ]
        return cmd

    # ---- lifecycle -----------------------------------------------------------

    def _resolve_source(self, requested):
        if requested in ("camera", "brb"):
            return requested
        # auto: mirror what is currently being broadcast
        if read_text(STREAM_MODE_FILE) == "fallback" and os.path.exists(FALLBACK_IMAGE):
            return "brb"
        return "camera"

    def start(self, requested_source="auto"):
        with self.lock:
            source = self._resolve_source(requested_source)
            if self.proc and self.proc.poll() is None:
                if source == self.source:
                    self.last_access = time.monotonic()
                    return True, "already running"
                self._stop_locked()
            if source == "camera" and not RTSP_SOURCE:
                return False, "RTSP_SOURCE is not configured"

            os.makedirs(PREVIEW_DIR, exist_ok=True)
            try:
                os.remove(PREVIEW_JPG)
            except OSError:
                pass

            cmd = self._build_cmd(source)
            log(f"Starting preview ffmpeg (source={source}, fps={1 if PREVIEW_LOW_CPU else PREVIEW_FPS}, width={PREVIEW_WIDTH})")
            try:
                self.proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
            except OSError as e:
                self.last_error = f"failed to launch ffmpeg: {e}"
                return False, self.last_error
            self.source = source
            self.started_at = time.time()
            self.last_access = time.monotonic()
            self.last_error = ""
            threading.Thread(target=self._stderr_drain, args=(self.proc,),
                             daemon=True, name="preview-stderr").start()
            return True, f"preview started (source={source})"

    def _stderr_drain(self, proc):
        try:
            data = proc.stderr.read() if proc.stderr else b""
            if data:
                tail = data.decode("utf-8", "replace").strip().splitlines()[-5:]
                msg = " | ".join(tail)
                with self.lock:
                    if proc is self.proc or self.last_error == "":
                        self.last_error = msg[-500:]
                log(f"preview ffmpeg stderr: {msg[-500:]}")
        except Exception:
            pass

    def _stop_locked(self):
        proc = self.proc
        self.proc = None
        self.started_at = None
        if proc and proc.poll() is None:
            try:
                # Kill the whole process group (started with start_new_session)
                # so no child of the preview pipeline can outlive it.
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        proc.kill()
                    proc.wait(timeout=2)
            except OSError:
                pass
        try:
            os.remove(PREVIEW_JPG)
        except OSError:
            pass

    def stop(self):
        with self.lock:
            was_running = self.proc is not None and self.proc.poll() is None
            self._stop_locked()
        if was_running:
            log("Preview stopped")
        return was_running

    def touch(self):
        self.last_access = time.monotonic()

    def _reaper(self):
        while True:
            time.sleep(5)
            with self.lock:
                if self.proc is None:
                    continue
                if self.proc.poll() is not None:
                    # ffmpeg died on its own (camera drop etc.)
                    rc = self.proc.returncode
                    log(f"Preview ffmpeg exited (code {rc})")
                    self.proc = None
                    self.started_at = None
                    continue
                idle = time.monotonic() - self.last_access
                if self.viewers <= 0 and idle > PREVIEW_IDLE_TIMEOUT:
                    log(f"Preview idle for {int(idle)}s - stopping to save CPU")
                    self._stop_locked()

    # ---- state ---------------------------------------------------------------

    def status(self):
        with self.lock:
            running = self.proc is not None and self.proc.poll() is None
            pid = self.proc.pid if running else None
            frame_age = None
            has_frame = os.path.exists(PREVIEW_JPG)
            if has_frame:
                try:
                    frame_age = round(time.time() - os.path.getmtime(PREVIEW_JPG), 1)
                except OSError:
                    has_frame = False
            return {
                "running": running,
                "pid": pid,
                "source": self.source if running else None,
                "viewers": self.viewers,
                "uptime_seconds": int(time.time() - self.started_at) if running and self.started_at else 0,
                "has_frame": has_frame,
                "frame_age_seconds": frame_age,
                "idle_timeout_seconds": PREVIEW_IDLE_TIMEOUT,
                "fps": 1 if PREVIEW_LOW_CPU else PREVIEW_FPS,
                "width": PREVIEW_WIDTH,
                "low_cpu_mode": PREVIEW_LOW_CPU,
                "last_error": self.last_error,
            }


preview = PreviewManager()


# ==============================================================================
#  WEATHER REFRESH (on demand)
# ==============================================================================

_weather_refresh_lock = threading.Lock()


def refresh_weather_now():
    """Regenerate the combined weather overlay immediately (same steps as the
    background manager in start.sh: render to temp, atomically swap, update
    the flash playlist)."""
    if not _weather_refresh_lock.acquire(blocking=False):
        return False, "refresh already in progress"
    try:
        temp = os.path.join(CONFIG_DIR, "weather_temp.png")
        proc = subprocess.run(
            ["python3", "/weather.py", "combined", temp],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0 or not os.path.exists(temp):
            err = (proc.stderr or b"").decode("utf-8", "replace")[-300:]
            return False, f"weather.py failed: {err or 'no output produced'}"
        os.replace(temp, WEATHER_COMBINED)
        flash_temp = temp.replace(".png", "_flash.png")
        if os.path.exists(flash_temp):
            os.replace(flash_temp, WEATHER_COMBINED_FLASH)
        elif os.path.exists(WEATHER_COMBINED_FLASH):
            # Never delete a frame the running encoder's playlist may still
            # reference - overwrite it with the normal frame instead.
            shutil.copyfile(WEATHER_COMBINED, WEATHER_COMBINED_FLASH + ".tmp")
            os.replace(WEATHER_COMBINED_FLASH + ".tmp", WEATHER_COMBINED_FLASH)
        meta_temp = temp.replace(".png", "_meta.txt")
        needs_flash = "0"
        if os.path.exists(meta_temp):
            for line in read_text(meta_temp).splitlines():
                if line.startswith("needs_flash="):
                    needs_flash = line.split("=", 1)[1].strip()
            os.replace(meta_temp, WEATHER_META)
        _write_weather_playlist(needs_flash == "1")
        return True, "weather overlay refreshed"
    except subprocess.TimeoutExpired:
        return False, "weather.py timed out"
    finally:
        _weather_refresh_lock.release()


def _write_weather_playlist(flash):
    if flash and os.path.exists(WEATHER_COMBINED_FLASH):
        pair = (f"file '{WEATHER_COMBINED}'\nduration {FLASH_ON_DURATION}\n"
                f"file '{WEATHER_COMBINED_FLASH}'\nduration {FLASH_OFF_DURATION}\n")
        content = pair * 4 + f"file '{WEATHER_COMBINED}'\n"
    else:
        content = f"file '{WEATHER_COMBINED}'\nduration 10\nfile '{WEATHER_COMBINED}'\n"
    with open(WEATHER_LIST, "w") as f:
        f.write(content)


# ==============================================================================
#  SPONSOR (AD) MANAGEMENT
# ==============================================================================

AD_SLOTS = ("topleft", "topright")
AD_MODES = ("DAY", "NIGHT")


def _ad_dir(slot, mode):
    if slot not in AD_SLOTS or mode not in AD_MODES:
        return None
    path = os.path.join(ADS_BASE, slot, mode)
    os.makedirs(path, exist_ok=True)
    return path


def _safe_ad_path(slot, mode, name):
    directory = _ad_dir(slot, mode)
    if directory is None:
        return None
    name = os.path.basename(name or "")
    if not SAFE_NAME_RE.match(name):
        return None
    if os.path.splitext(name)[1].lower() not in ALLOWED_AD_EXT:
        return None
    path = os.path.realpath(os.path.join(directory, name))
    if not path.startswith(os.path.realpath(directory) + os.sep):
        return None
    return path


def list_ads():
    out = {}
    for slot in AD_SLOTS:
        out[slot] = {}
        for mode in AD_MODES:
            directory = _ad_dir(slot, mode)
            files = []
            try:
                for name in sorted(os.listdir(directory)):
                    full = os.path.join(directory, name)
                    if (os.path.isfile(full)
                            and os.path.splitext(name)[1].lower() in ALLOWED_AD_EXT):
                        st = os.stat(full)
                        files.append({"name": name, "bytes": st.st_size,
                                      "modified": int(st.st_mtime)})
            except OSError:
                pass
            out[slot][mode] = files
    return out


def validate_image_bytes(data):
    """Best-effort validation that an upload really is an image (PIL is in the
    container image; degrade gracefully if unavailable)."""
    try:
        from PIL import Image
    except ImportError:
        return True
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:
        return False


def parse_multipart(body, content_type):
    """Minimal multipart/form-data parser: returns (fields, files) where files
    maps field name -> (filename, bytes)."""
    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        return {}, {}
    boundary = b"--" + m.group(1).encode()
    fields, files = {}, {}
    for part in body.split(boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, payload = part.split(b"\r\n\r\n", 1)
        headers = raw_headers.decode("utf-8", "replace")
        name_m = re.search(r'name="([^"]*)"', headers)
        if not name_m:
            continue
        file_m = re.search(r'filename="([^"]*)"', headers)
        if file_m:
            files[name_m.group(1)] = (file_m.group(1), payload)
        else:
            fields[name_m.group(1)] = payload.decode("utf-8", "replace")
    return fields, files


# ==============================================================================
#  STATUS AGGREGATION
# ==============================================================================

def build_status():
    now = time.time()
    stream_mode = read_text(STREAM_MODE_FILE, "unknown")
    audio_mode = read_text(AUDIO_MODE_FILE, "muted")
    encoder_mode = read_text(ENCODER_MODE_FILE, "vaapi" if HARDWARE_ACCEL else "software")

    pid = get_broadcast_pid()
    started = proc_start_time(pid) if pid else None
    pstatus = preview.status()

    pids = [p for p in (pid, pstatus.get("pid")) if p]
    cpu = cpu_sampler.sample(pids)

    mem = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("MemTotal", "MemAvailable"):
                    mem[k] = int(v.split()[0]) * 1024
    except OSError:
        pass

    watchdog_state = None
    try:
        with open(WATCHDOG_STATE_FILE) as f:
            watchdog_state = json.load(f)
    except (OSError, ValueError):
        pass

    direct_mode = bool(YOUTUBE_KEY) and not ENABLE_LOCAL_STREAM

    hold_remaining = 0
    try:
        hold_remaining = max(0, int(read_text(RESTART_HOLD_FILE, "0") or 0) - int(now))
    except ValueError:
        hold_remaining = 0

    return {
        "time": int(now),
        "stream": {
            "mode": stream_mode,
            "restart_hold_seconds": hold_remaining,
            "paused": broadcast_is_paused(),
            "broadcasting": pid is not None,
            "pid": pid,
            "uptime_seconds": int(now - started) if started else 0,
            "direct_youtube_mode": direct_mode,
            "youtube_configured": bool(YOUTUBE_KEY),
            "local_stream_enabled": ENABLE_LOCAL_STREAM,
            "fallback_enabled": FALLBACK_ENABLED,
            "encoder": encoder_mode,
            "resolution": f"{YOUTUBE_WIDTH}x{YOUTUBE_HEIGHT}",
            "cpu_percent": cpu.get(pid),
            "progress": parse_progress(),
        },
        "camera": {
            "rtsp_configured": bool(RTSP_SOURCE),
            "rtsp_status": rtsp_probe.check(),
        },
        "audio": {
            "mode": audio_mode,
            "muted": audio_mode == "muted",
            "music": audio_mode == "music",
            "music_files": _count_music_files(),
        },
        "youtube": youtube_broadcast_info(),
        "watchdog": {
            "enabled": WATCHDOG_ENABLED,
            "state": watchdog_state,
        },
        "day_night": day_night_info(),
        "program": program_summary(),
        "preview": {**pstatus, "cpu_percent": cpu.get(pstatus.get("pid"))},
        "system": {
            "load": _loadavg(),
            "cpu_percent": cpu.get("system"),
            "mem_total_bytes": mem.get("MemTotal"),
            "mem_available_bytes": mem.get("MemAvailable"),
            "cpu_count": os.cpu_count(),
        },
    }


_day_night_cache = {"at": 0.0, "data": None}
_day_night_lock = threading.Lock()
DAY_NIGHT_POLL_SECONDS = 60.0


def day_night_info():
    """Which sponsor set is airing, and why. Cached - the UI polls status often.

    Mirrors start.sh's get_mode(): with DAY_NIGHT_MODE=sun the resolved mode is
    read from sun_times.py (which caches the solar lookup per day and falls back
    to the clock on any failure); otherwise it is the plain clock schedule.
    """
    global _day_night_cache
    with _day_night_lock:
        if _day_night_cache["data"] is not None and \
                time.monotonic() - _day_night_cache["at"] < DAY_NIGHT_POLL_SECONDS:
            return _day_night_cache["data"]
        info = {"configured_mode": DAY_NIGHT_MODE}
        try:
            import sun_times
            if DAY_NIGHT_MODE == "sun":
                mode, source = sun_times.resolve_mode()
                cache = sun_times._load_cache() or {}
                info.update({
                    "mode": mode,
                    "source": source,          # "sun", or "clock" if the lookup failed
                    "sunrise": cache.get("sunrise"),
                    "sunset": cache.get("sunset"),
                    "offset_minutes": sun_times.SUN_OFFSET_MINUTES,
                })
            else:
                info.update({"mode": sun_times._clock_mode(), "source": "clock",
                             "day_start_hour": sun_times.DAY_START_HOUR,
                             "day_end_hour": sun_times.DAY_END_HOUR})
        except Exception as e:                 # never break the status payload
            info.update({"mode": None, "source": "unavailable", "error": str(e)[:120]})
        _day_night_cache = {"at": time.monotonic(), "data": info}
        return info


def _loadavg():
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return None


def _count_music_files():
    try:
        return sum(1 for n in os.listdir(MUSIC_DIR) if n.lower().endswith(".mp3"))
    except OSError:
        return 0


# ---------------------------------------------------------------- metrics
# Encoder telemetry sampled on a fixed cadence, independent of how often a
# browser happens to poll, so the trend is evenly spaced and survives a closed
# tab. ~15 minutes of history at 5s resolution.
METRICS_INTERVAL = 5.0
METRICS_POINTS = 180


class MetricsHistory:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples = []

    @staticmethod
    def _kbps(bitrate):
        """FFmpeg reports e.g. '4300.2kbits/s'; 'N/A' while starting up."""
        if not bitrate:
            return None
        m = re.match(r"\s*([0-9.]+)\s*([kM]?)bits/s", str(bitrate))
        if not m:
            return None
        value = float(m.group(1))
        return value * 1000 if m.group(2) == "M" else value

    @staticmethod
    def _num(value):
        try:
            return float(str(value).rstrip("x"))
        except (TypeError, ValueError):
            return None

    def sample_once(self):
        progress = parse_progress()
        broadcasting = get_broadcast_pid() is not None
        point = {"t": int(time.time())}
        if progress and broadcasting:
            point["bitrate"] = self._kbps(progress.get("bitrate"))
            point["fps"] = self._num(progress.get("fps"))
            point["speed"] = self._num(progress.get("speed"))
        else:
            point["bitrate"] = point["fps"] = point["speed"] = None
        with self.lock:
            self.samples.append(point)
            if len(self.samples) > METRICS_POINTS:
                del self.samples[:-METRICS_POINTS]

    def history(self):
        with self.lock:
            return list(self.samples)

    def run(self):
        while True:
            try:
                self.sample_once()
            except Exception:
                pass
            time.sleep(METRICS_INTERVAL)


metrics = MetricsHistory()


# YouTube broadcast info is polled on a slow timer of its own: /api/status is
# hit every few seconds by the browser, and the Data API has a daily quota.
_youtube_cache = {"at": 0.0, "data": None}
_youtube_lock = threading.Lock()
YOUTUBE_POLL_SECONDS = 30.0


def program_summary():
    """Just the on-air facts, cheap enough for the 3s status poll."""
    try:
        st = scenes.state()
        return {"program": st["program"], "program_name": st["program_name"],
                "on_air": st["on_air"], "preview": st["preview"],
                "preview_name": st["preview_name"]}
    except Exception as e:
        return {"program": None, "on_air": "unknown", "error": str(e)[:120]}


def scene_payload():
    """Scene library plus bus state, as the WebUI and MQTT bridge both want it."""
    state = scenes.state()
    state["backgrounds"] = scenes.list_backgrounds()
    return {"scenes_state": state}


def youtube_broadcast_info(force=False):
    """Current broadcast (title, visibility, viewers), cached.

    Never raises: the WebUI degrades to 'unavailable' with the reason rather
    than failing the whole status payload.
    """
    yt = youtube_api.client()
    if not yt.configured:
        return {"configured": False,
                "note": "Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and "
                        "YOUTUBE_REFRESH_TOKEN to control the broadcast from here."}
    with _youtube_lock:
        age = time.monotonic() - _youtube_cache["at"]
        if not force and _youtube_cache["data"] is not None and age < YOUTUBE_POLL_SECONDS:
            return _youtube_cache["data"]
        try:
            broadcast = yt.get_active_broadcast()
            if broadcast is None:
                data = {"configured": True, "available": True, "broadcast": None,
                        "note": "No active or upcoming broadcast on this channel."}
            else:
                viewers = None
                if broadcast.get("state") == "active":
                    try:
                        viewers = yt.get_viewers(broadcast["id"])
                    except youtube_api.YouTubeError:
                        viewers = None
                data = {"configured": True, "available": True,
                        "broadcast": {**broadcast, "viewers": viewers}}
        except youtube_api.YouTubeError as e:
            data = {"configured": True, "available": False,
                    "kind": e.kind, "note": e.message}
        _youtube_cache["at"] = time.monotonic()
        _youtube_cache["data"] = data
        return data


def _inspect_stream_key():
    """Sanity-check YOUTUBE_KEY without ever revealing it.

    A key pasted through a template editor can pick up a trailing CR, newline
    or space. FFmpeg then publishes to a URL that is not the one you think,
    and the ingest closes the session - which looks identical to every other
    publishing failure. This catches that in one glance.
    """
    key = YOUTUBE_KEY
    if not key:
        return {"configured": False, "ok": None, "note": "YOUTUBE_KEY is not set"}
    stripped = key.strip()
    problems = []
    if key != stripped:
        problems.append("has leading/trailing whitespace (likely a stray newline or space from an edit)")
    if any(ord(c) < 32 or ord(c) == 127 for c in key):
        problems.append("contains control characters (e.g. a Windows carriage return)")
    if " " in stripped:
        problems.append("contains an internal space")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", stripped or "x"):
        problems.append("contains characters outside the usual letters/digits/dashes")
    if not (16 <= len(stripped) <= 64):
        problems.append(f"is {len(stripped)} characters long (YouTube keys are typically 20-24)")
    return {
        "configured": True,
        "ok": not problems,
        "length": len(key),
        "problems": problems,
        "note": "looks well-formed" if not problems else "; ".join(problems),
    }


def build_config_view():
    """Effective configuration with every secret masked."""
    def mask(value):
        return "•••• (set)" if value else "(not set)"

    def mask_rtsp(url):
        if not url:
            return "(not set)"
        return re.sub(r"//[^@/]+@", "//****:****@", url)

    return {
        "rtsp_source": mask_rtsp(RTSP_SOURCE),
        "scaling_mode": SCALING_MODE,
        "hardware_accel": HARDWARE_ACCEL,
        "encoder_active": read_text(ENCODER_MODE_FILE, "unknown"),
        "resolution": f"{YOUTUBE_WIDTH}x{YOUTUBE_HEIGHT}",
        "youtube_url": os.getenv("YOUTUBE_URL", "rtmp://a.rtmp.youtube.com/live2"),
        "youtube_key": mask(YOUTUBE_KEY),
        "youtube_bitrate": os.getenv("YOUTUBE_BITRATE", "4500k"),
        "direct_youtube_mode": bool(YOUTUBE_KEY) and not ENABLE_LOCAL_STREAM,
        "enable_local_stream": ENABLE_LOCAL_STREAM,
        "fallback_enabled": FALLBACK_ENABLED,
        "weather_enabled": WEATHER_ENABLED,
        "weather_location": os.getenv("WEATHER_LOCATION", ""),
        "weather_lat": os.getenv("WEATHER_LAT", ""),
        "weather_lon": os.getenv("WEATHER_LON", ""),
        "weather_timezone": os.getenv("WEATHER_TIMEZONE", ""),
        "camera_heading": os.getenv("CAMERA_HEADING", ""),
        "alerts_update_interval": os.getenv("ALERTS_UPDATE_INTERVAL", "900"),
        "watchdog_enabled": WATCHDOG_ENABLED,
        "watchdog_status_url": os.getenv("WATCHDOG_STATUS_URL", "(not set)"),
        "discord_webhook": mask(os.getenv("DISCORD_WEBHOOK_URL", "")),
        "youtube_api": mask(os.getenv("YOUTUBE_REFRESH_TOKEN", "")),
        "audio_api_key": mask(os.getenv("AUDIO_API_KEY", "")),
        "preview": {
            "fps": PREVIEW_FPS,
            "width": PREVIEW_WIDTH,
            "idle_timeout_seconds": PREVIEW_IDLE_TIMEOUT,
            "low_cpu_mode": PREVIEW_LOW_CPU,
        },
        "day_start_hour": os.getenv("DAY_START_HOUR", "6"),
        "day_end_hour": os.getenv("DAY_END_HOUR", "20"),
    }


# ==============================================================================
#  HTTP HANDLER
# ==============================================================================

OVERLAY_FILES = {
    "weather": WEATHER_COMBINED,
    "weather_flash": WEATHER_COMBINED_FLASH,
    "tl": AD_FINAL_TL,
    "tr": AD_FINAL_TR,
    "fallback": FALLBACK_IMAGE,
}

MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".html": "text/html; charset=utf-8"}


def password_is_usable():
    return ADMIN_PASS not in _KNOWN_DEFAULT_PASSWORDS


class AdminHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "VantageCamAdmin"

    def log_message(self, fmt, *args):
        pass

    # ---- plumbing ------------------------------------------------------------

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        # frame-src is the only outbound allowance: it lets the dashboard embed
        # the YouTube player so the operator can see what actually arrives at
        # the destination. Scripts, styles and XHR stay same-origin.
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data: https://i.ytimg.com; "
                         "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                         "connect-src 'self'; "
                         "frame-src https://www.youtube-nocookie.com https://www.youtube.com")

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, data, content_type, status=200, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def check_auth(self):
        if not password_is_usable():
            body = (b"<html><body style='font-family:sans-serif;background:#111;color:#eee;"
                    b"display:flex;align-items:center;justify-content:center;height:100vh'>"
                    b"<div style='max-width:540px'><h2>&#128274; Admin WebUI is locked</h2>"
                    b"<p>Set a real <code>ADMIN_PASS</code> (and <code>ADMIN_USER</code>) "
                    b"environment variable on the container, then restart it. The default/"
                    b"empty password is rejected on purpose.</p></div></body></html>")
            self.send_bytes(body, "text/html; charset=utf-8", 503)
            return False
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
                user, _, password = decoded.partition(":")
                user_ok = hmac.compare_digest(user.encode(), ADMIN_USER.encode())
                pass_ok = hmac.compare_digest(password.encode(), ADMIN_PASS.encode())
                if user_ok and pass_ok:
                    return True
            except (ValueError, UnicodeDecodeError):
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="VantageCam Admin"')
        self.send_header("Content-Length", "0")
        self._security_headers()
        self.end_headers()
        return False

    # ---- GET -----------------------------------------------------------------

    def do_GET(self):
        try:
            self._route_get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"GET {self.path} error: {e}")
            try:
                self.send_json({"error": "internal error"}, 500)
            except OSError:
                pass

    def _route_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/health":
            self.send_json({"status": "ok"})
            return
        if not self.check_auth():
            return

        if path in ("/", "/index.html"):
            self._serve_ui()
        elif path == "/api/status":
            self.send_json(build_status())
        elif path == "/api/config":
            self.send_json(build_config_view())
        elif path == "/api/preview/stream":
            self._serve_preview_stream()
        elif path == "/api/preview/snapshot":
            self._serve_preview_snapshot()
        elif path == "/api/metrics/history":
            self.send_json({"interval": METRICS_INTERVAL, "samples": metrics.history()})
        elif path == "/api/events":
            try:
                limit = max(1, min(500, int((query.get("limit") or ["60"])[0])))
            except ValueError:
                limit = 60
            import events
            self.send_json({"events": events.read(limit)})
        elif path == "/api/youtube/broadcast":
            self.send_json(youtube_broadcast_info(force=True))
        elif path == "/api/scenes":
            self.send_json(scene_payload())
        elif path == "/api/schedule":
            self.send_json(scene_schedule.status())
        elif path == "/api/scenes/card":
            self._serve_scene_card(query)
        elif path == "/api/program/still":
            self._serve_bus_still(query)
        elif path == "/api/layout":
            self.send_json({
                "canvas": {"width": overlay_layout.CANVAS_W, "height": overlay_layout.CANVAS_H},
                "overlays": overlay_layout.load(),
                "labels": overlay_layout.SLOTS,
                "weather_enabled": WEATHER_ENABLED,
            })
        elif path == "/api/sponsors":
            try:
                days = max(1, min(365, int((query.get("days") or ["30"])[0])))
            except ValueError:
                days = 30
            self.send_json(sponsors.report(days))
        elif path == "/api/sponsors/report.csv":
            try:
                days = max(1, min(365, int((query.get("days") or ["30"])[0])))
            except ValueError:
                days = 30
            body = sponsors.report_csv(days).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition",
                             f'attachment; filename="sponsor-airtime-{time.strftime("%Y%m%d")}.csv"')
            self.send_header("Content-Length", str(len(body)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/ads":
            self.send_json({"ads": list_ads(), "slots": AD_SLOTS, "modes": AD_MODES})
        elif path == "/api/ads/image":
            self._serve_ad_image(query)
        elif path.startswith("/api/overlay/"):
            self._serve_overlay(path.rsplit("/", 1)[1])
        elif path == "/api/logs":
            self._serve_logs(query)
        else:
            self.send_json({"error": "not found"}, 404)

    def _serve_ui(self):
        for candidate in UI_FILE_CANDIDATES:
            if os.path.exists(candidate):
                with open(candidate, "rb") as f:
                    self.send_bytes(f.read(), "text/html; charset=utf-8")
                return
        self.send_json({"error": "admin_ui.html not found"}, 500)

    def _serve_overlay(self, name):
        path = OVERLAY_FILES.get(name)
        if not path or not os.path.exists(path):
            self.send_json({"error": "overlay not available"}, 404)
            return
        with open(path, "rb") as f:
            self.send_bytes(f.read(), "image/png")

    def _serve_ad_image(self, query):
        slot = (query.get("slot") or [""])[0]
        mode = (query.get("mode") or [""])[0]
        name = (query.get("name") or [""])[0]
        path = _safe_ad_path(slot, mode, name)
        if not path or not os.path.exists(path):
            self.send_json({"error": "not found"}, 404)
            return
        mime = MIME_BY_EXT.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        with open(path, "rb") as f:
            self.send_bytes(f.read(), mime, cache="max-age=30")

    def _serve_logs(self, query):
        name = (query.get("name") or ["watchdog"])[0]
        try:
            lines = max(10, min(1000, int((query.get("lines") or ["200"])[0])))
        except ValueError:
            lines = 200
        path = LOG_FILES.get(name)
        if not path:
            self.send_json({"error": f"unknown log '{name}'", "available": list(LOG_FILES)}, 404)
            return
        if not os.path.exists(path):
            self.send_json({"name": name, "lines": [], "note": "log file does not exist yet"})
            return
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 256 * 1024))
                tail = f.read().decode("utf-8", "replace").splitlines()[-lines:]
            tail = [_scrub_secrets(line) for line in tail]
            self.send_json({"name": name, "lines": tail})
        except OSError as e:
            self.send_json({"error": str(e)}, 500)

    def _serve_preview_snapshot(self):
        preview.touch()
        if not os.path.exists(PREVIEW_JPG):
            self.send_json({"error": "no frame yet", "running": preview.status()["running"]}, 404)
            return
        try:
            with open(PREVIEW_JPG, "rb") as f:
                self.send_bytes(f.read(), "image/jpeg")
        except OSError:
            self.send_json({"error": "frame read failed"}, 500)

    def _serve_preview_stream(self):
        """multipart/x-mixed-replace MJPEG stream from the snapshot file."""
        status = preview.status()
        if not status["running"]:
            self.send_json({"error": "preview not running"}, 409)
            return
        boundary = "vantagecamframe"
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()

        with preview.lock:
            preview.viewers += 1
        last_mtime = 0.0
        try:
            deadline_misses = 0
            while True:
                preview.touch()
                if not preview.status()["running"]:
                    break
                try:
                    mtime = os.path.getmtime(PREVIEW_JPG)
                except OSError:
                    mtime = 0.0
                if mtime > last_mtime:
                    last_mtime = mtime
                    deadline_misses = 0
                    try:
                        with open(PREVIEW_JPG, "rb") as f:
                            frame = f.read()
                    except OSError:
                        continue
                    if frame[:2] != b"\xff\xd8":
                        continue  # partially written frame; skip
                    self.wfile.write(
                        f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                else:
                    deadline_misses += 1
                    if deadline_misses > 300:  # ~30s without a new frame
                        break
                time.sleep(0.1)
        finally:
            # multipart/x-mixed-replace has no length framing; the connection
            # must close so the client knows the stream ended.
            self.close_connection = True
            with preview.lock:
                preview.viewers = max(0, preview.viewers - 1)

    # ---- POST ----------------------------------------------------------------

    def do_POST(self):
        try:
            self._route_post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"POST {self.path} error: {e}")
            try:
                self.send_json({"error": "internal error"}, 500)
            except OSError:
                pass

    def _read_body(self, limit=MAX_UPLOAD_BYTES):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.close_connection = True
            return None
        if length < 0 or length > limit:
            # Body is not drained - close so keep-alive can't desync
            self.close_connection = True
            return None
        return self.rfile.read(length) if length else b""

    def _route_post(self):
        if not self.check_auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/preview/start":
            source = (query.get("source") or ["auto"])[0]
            ok, msg = preview.start(source)
            self.send_json({"ok": ok, "message": msg, "preview": preview.status()},
                           200 if ok else 409)
        elif path == "/api/preview/stop":
            was_running = preview.stop()
            self.send_json({"ok": True,
                            "message": "preview stopped" if was_running else "preview was not running",
                            "preview": preview.status()})
        elif path.startswith("/api/audio/"):
            mode = path.rsplit("/", 1)[1]
            if mode == "toggle":
                mode = "unmuted" if read_text(AUDIO_MODE_FILE, "muted") == "muted" else "muted"
            ok, msg = set_audio_mode(mode)
            self.send_json({"ok": ok, "message": msg, "audio": mode}, 200 if ok else 400)
        elif path == "/api/stream/start":
            ok, msg = start_broadcast()
            self.send_json({"ok": ok, "message": msg})
        elif path == "/api/stream/stop":
            ok, msg = stop_broadcast()
            self.send_json({"ok": ok, "message": msg})
        elif path == "/api/youtube/privacy":
            self._handle_privacy(query)
        elif path == "/api/stream/restart":
            ok, msg = signal_broadcast_restart("manual restart from WebUI")
            self.send_json({"ok": ok, "message": msg}, 200 if ok else 409)
        elif path == "/api/stream/retry-now":
            # Cancel a pending watchdog backoff so the supervisor respawns
            # immediately instead of sitting out the remaining hold.
            try:
                os.remove(RESTART_HOLD_FILE)
                self.send_json({"ok": True, "message": "Backoff cancelled - the encoder will respawn within a couple of seconds"})
            except FileNotFoundError:
                self.send_json({"ok": True, "message": "No backoff was pending"})
            except OSError as e:
                self.send_json({"ok": False, "message": str(e)}, 500)
        elif path == "/api/weather/refresh":
            ok, msg = refresh_weather_now()
            self.send_json({"ok": ok, "message": msg}, 200 if ok else 409)
        elif path == "/api/ingest/check":
            url = os.getenv("YOUTUBE_URL", "rtmp://a.rtmp.youtube.com/live2")
            try:
                result = ingest_probe.probe(url)
                result["stream_key"] = _inspect_stream_key()
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": f"probe failed: {e}"}, 500)
        elif path == "/api/layout":
            self._handle_layout_save(query)
        elif path == "/api/layout/reset":
            saved = overlay_layout.save(overlay_layout.defaults())
            preview.stop()
            self.send_json({"ok": True, "message": "layout reset to defaults", "overlays": saved})
        elif path == "/api/program":
            self._handle_take()
        elif path == "/api/program/preview":
            self._handle_set_preview()
        elif path == "/api/schedule":
            self._handle_schedule_save()
        elif path == "/api/scenes/save":
            self._handle_scene_save()
        elif path == "/api/scenes/delete":
            self._handle_scene_delete()
        elif path == "/api/scenes/fallback":
            self._handle_scene_fallback()
        elif path == "/api/scenes/away":
            self._handle_scene_away()
        elif path == "/api/scenes/background":
            self._handle_scene_background()
        elif path == "/api/sponsors/schedule":
            self._handle_sponsor_schedule()
        elif path == "/api/ads/upload":
            self._handle_ad_upload()
        elif path == "/api/ads/delete":
            self._handle_ad_delete()
        else:
            self.send_json({"error": "not found"}, 404)

    def _handle_privacy(self, query):
        body = self._read_body(limit=4096)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        privacy = (payload.get("privacy") or (query.get("privacy") or [""])[0]).lower()
        if privacy not in youtube_api.PRIVACY_CHOICES:
            self.send_json({"error": f"privacy must be one of {', '.join(youtube_api.PRIVACY_CHOICES)}"}, 400)
            return
        try:
            yt = youtube_api.client()
            broadcast = yt.get_active_broadcast()
            if not broadcast:
                self.send_json({"ok": False,
                                "message": "No active or upcoming broadcast found on this channel."}, 409)
                return
            applied = yt.set_privacy(broadcast["id"], privacy)
            log(f"Broadcast visibility set to {applied}")
            events.record("visibility", f"Visibility set to {applied} from the WebUI")
            _youtube_cache["at"] = 0          # force the next poll to re-read
            self.send_json({"ok": True, "privacy": applied,
                            "message": f"Visibility set to {applied}."})
        except youtube_api.YouTubeError as e:
            self.send_json({"ok": False, "kind": e.kind, "message": e.message},
                           501 if e.kind == "not_configured" else 502)

    def _handle_sponsor_schedule(self):
        body = self._read_body(limit=8192)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        try:
            entry = sponsors.set_entry(
                payload.get("slot", ""), payload.get("mode", ""), payload.get("name", ""),
                enabled=payload.get("enabled"), start=payload.get("start"),
                end=payload.get("end"), note=payload.get("note"))
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
            return
        name = os.path.basename(payload.get("name", ""))
        log(f"Sponsor schedule updated: {payload.get('slot')}/{payload.get('mode')}/{name} -> {entry}")
        events.record("sponsor", f"Schedule updated for {name}: "
                                 f"{'enabled' if entry['enabled'] else 'disabled'}"
                                 f"{', from ' + entry['start'] if entry['start'] else ''}"
                                 f"{', until ' + entry['end'] if entry['end'] else ''}")
        self.send_json({"ok": True, "entry": entry, "report": sponsors.report()})

    def _handle_layout_save(self, query):
        body = self._read_body(limit=16384)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        overlays = payload.get("overlays", payload)
        if not isinstance(overlays, dict):
            self.send_json({"error": "expected an 'overlays' object"}, 400)
            return

        saved = overlay_layout.save(overlays)
        log(f"Overlay layout saved: " + ", ".join(
            f"{k}={v['w']}x{v['h']}@{v['x']},{v['y']}{'' if v['enabled'] else ' (off)'}"
            for k, v in saved.items()))

        # FFmpeg fixes its filter graph at launch, so both pipelines must be
        # restarted to pick up new positions; each rebuilds its graph from the
        # file just written. The preview restarts on its own (next start
        # rebuilds the chain); the broadcast only if asked, since that briefly
        # interrupts the live stream.
        preview.stop()
        applied = False
        detail = "Saved. Restart the stream to apply it on air."
        if (query.get("apply") or [""])[0].lower() in ("1", "true", "yes"):
            ok, msg = signal_broadcast_restart("overlay layout change")
            applied = ok
            detail = ("Saved and applied - the encoder is relaunching with the new layout "
                      "(a few seconds of interruption on air)." if ok
                      else f"Saved, but the broadcast could not be restarted: {msg}")

        self.send_json({"ok": True, "applied": applied, "message": detail,
                        "overlays": saved})

    # ---------------- scenes & the program/preview buses ----------------

    def _serve_scene_card(self, query):
        """The rendered 2560x1440 card for one scene (UI thumbnails)."""
        sid = (query.get("id") or [""])[0]
        if not scenes.ID_RE.match(sid or "") or sid not in scenes.list_scenes():
            self.send_json({"error": "unknown scene"}, 404)
            return
        path = os.path.join(scenes.SCENES_DIR, f"{sid}.png")
        if not os.path.exists(path):
            try:
                scenes.render_to_disk(sid)
            except Exception:
                self.send_json({"error": "scene could not be rendered"}, 500)
                return
        with open(path, "rb") as f:
            self.send_bytes(f.read(), "image/png", cache="no-store")

    def _serve_bus_still(self, query):
        """A composited still of either bus, for the Program/Preview monitors."""
        bus = (query.get("bus") or ["pvw"])[0]
        state = scenes.state()
        target = state["program"] if bus == "pgm" else state["preview"]
        override = (query.get("target") or [""])[0]
        if override:
            if override != "live" and override not in state["scenes"]:
                self.send_json({"error": "unknown scene"}, 404)
                return
            target = override
        try:
            data, detail = compose_still(target)
        except Exception as e:
            self.send_json({"error": f"compose failed: {e}"}, 500)
            return
        if data is None:
            self.send_json({"error": detail}, 503)
            return
        self.send_bytes(data, "image/jpeg", cache="no-store")

    def _handle_take(self):
        """Take a bus to air. The encoder is NOT restarted - the layer swaps."""
        body = self._read_body(limit=4096)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        # resolve_target understands live/toggle/away/on/off as well as scene
        # ids, so MQTT, Home Assistant and the WebUI all speak the same words.
        target = scenes.resolve_target(payload.get("target", ""))
        ok, msg, state = scenes.set_program(target)
        if not ok:
            self.send_json({"error": msg}, 400)
            return
        log(f"Program take: {state['program']} ({state['program_name']})")
        events.record("program", f"On air: {state['program_name']}",
                      "info" if state["program"] == "live" else "warn")
        self.send_json({"ok": True, "message": msg, **scene_payload()})

    def _handle_set_preview(self):
        body = self._read_body(limit=4096)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        target = payload.get("target")
        target = str(target).strip().lower() if target else None
        ok, msg, _ = scenes.set_preview(target)
        if not ok:
            self.send_json({"error": msg}, 400)
            return
        self.send_json({"ok": True, "message": msg, **scene_payload()})

    def _handle_scene_save(self):
        body = self._read_body(limit=65536)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        sid = str(payload.get("id", "")).strip().lower()
        try:
            saved = scenes.save_scene(sid, payload.get("scene") or payload)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
            return
        except Exception as e:
            self.send_json({"error": f"could not save scene: {e}"}, 500)
            return
        log(f"Scene saved: {sid} ({saved['name']})")
        self.send_json({"ok": True, "message": f"Saved '{saved['name']}'.",
                        **scene_payload()})

    def _handle_scene_delete(self):
        body = self._read_body(limit=4096)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        sid = str(payload.get("id", "")).strip().lower()
        try:
            scenes.delete_scene(sid)
        except KeyError:
            self.send_json({"error": "unknown scene"}, 404)
            return
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
            return
        log(f"Scene deleted: {sid}")
        self.send_json({"ok": True, "message": "Scene deleted.", **scene_payload()})

    def _handle_scene_fallback(self):
        body = self._read_body(limit=4096)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        try:
            sid = scenes.set_fallback_scene(str(payload.get("id", "")).strip().lower())
        except KeyError:
            self.send_json({"error": "unknown scene"}, 404)
            return
        log(f"Automatic fallback scene set to {sid}")
        self.send_json({"ok": True,
                        "message": "Automatic camera-failure card updated.",
                        **scene_payload()})

    def _handle_schedule_save(self):
        """Whole-schedule save: the UI edits it as one document."""
        body = self._read_body(limit=65536)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        if not isinstance(payload.get("rules", []), list):
            self.send_json({"error": "'rules' must be a list"}, 400)
            return
        try:
            saved = scene_schedule.save({
                "enabled": payload.get("enabled", False),
                "apply_on_start": payload.get("apply_on_start", True),
                "rules": payload.get("rules") or [],
                # Enabling the schedule must not instantly fire every rule that
                # happens to have passed today, so the tick clock starts now.
                "last_tick": time.time(),
            })
        except Exception as e:
            self.send_json({"error": f"could not save schedule: {e}"}, 500)
            return
        log(f"Schedule saved: {'enabled' if saved['enabled'] else 'disabled'}, "
            f"{len(saved['rules'])} rule(s)")
        self.send_json({"ok": True,
                        "message": ("Schedule saved and running." if saved["enabled"]
                                    else "Schedule saved. It is switched off, so nothing "
                                         "will change on its own."),
                        **scene_schedule.status()})

    def _handle_scene_away(self):
        body = self._read_body(limit=4096)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        try:
            sid = scenes.set_away_scene(str(payload.get("id", "")).strip().lower())
        except KeyError:
            self.send_json({"error": "unknown scene"}, 404)
            return
        log(f"Away scene set to {sid}")
        self.send_json({"ok": True,
                        "message": "Away card updated - this is what the switch takes to air.",
                        **scene_payload()})

    def _handle_scene_background(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self.send_json({"error": "expected multipart/form-data"}, 400)
            return
        body = self._read_body()
        if body is None:
            self.send_json({"error": f"upload too large (max {MAX_UPLOAD_BYTES // (1024*1024)}MB)"}, 413)
            return
        fields, files = parse_multipart(body, ctype)
        upload = files.get("file")
        if not upload:
            self.send_json({"error": "no file provided"}, 400)
            return
        filename, data = upload
        path = scenes.background_path(filename)
        if path is None:
            self.send_json({"error": "invalid filename (png, jpg, jpeg, webp only)"}, 400)
            return
        if not data or not validate_image_bytes(data):
            self.send_json({"error": "file does not look like a valid image"}, 400)
            return
        tmp = path + ".uploading"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        name = os.path.basename(path)
        log(f"Scene background uploaded: {name} ({len(data)} bytes)")
        # Re-render anything already using this background so the change shows
        for sid, scene in scenes.list_scenes().items():
            if scene.get("background") == name:
                try:
                    scenes.save_scene(sid, scene)
                except Exception:
                    pass
        self.send_json({"ok": True, "message": f"uploaded {name}",
                        "background": name, **scene_payload()})

    def _handle_ad_upload(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self.send_json({"error": "expected multipart/form-data"}, 400)
            return
        body = self._read_body()
        if body is None:
            self.send_json({"error": f"upload too large (max {MAX_UPLOAD_BYTES // (1024*1024)}MB)"}, 413)
            return
        fields, files = parse_multipart(body, ctype)
        slot = fields.get("slot", "")
        mode = fields.get("mode", "")
        upload = files.get("file")
        if not upload:
            self.send_json({"error": "no file provided"}, 400)
            return
        filename, data = upload
        path = _safe_ad_path(slot, mode, filename)
        if path is None:
            self.send_json({"error": "invalid slot/mode/filename "
                                     "(png, jpg, jpeg, webp only; simple names only)"}, 400)
            return
        if not data or not validate_image_bytes(data):
            self.send_json({"error": "file does not look like a valid image"}, 400)
            return
        tmp = path + ".uploading"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        log(f"Ad uploaded: {slot}/{mode}/{os.path.basename(path)} ({len(data)} bytes)")
        self.send_json({"ok": True, "message": f"uploaded {os.path.basename(path)}",
                        "ads": list_ads()})

    def _handle_ad_delete(self):
        body = self._read_body(limit=4096)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self.send_json({"error": "invalid JSON"}, 400)
            return
        path = _safe_ad_path(payload.get("slot", ""), payload.get("mode", ""),
                             payload.get("name", ""))
        if path is None or not os.path.exists(path):
            self.send_json({"error": "file not found"}, 404)
            return
        os.remove(path)
        try:
            sponsors.forget(payload.get("slot", ""), payload.get("mode", ""),
                            os.path.basename(path))
        except Exception:
            pass
        log(f"Ad deleted: {path}")
        self.send_json({"ok": True, "message": f"deleted {os.path.basename(path)}",
                        "ads": list_ads()})


# ==============================================================================
#  MAIN
# ==============================================================================

def _handle_sigterm(signum, frame):
    preview.stop()
    os._exit(0)


def main():
    if os.getenv("ADMIN_WEBUI_ENABLED", "true").lower() != "true":
        log("Admin WebUI disabled (ADMIN_WEBUI_ENABLED=false)")
        return

    signal.signal(signal.SIGTERM, _handle_sigterm)
    threading.Thread(target=metrics.run, daemon=True, name="metrics").start()
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    # Clear stale frames from a previous run
    try:
        os.remove(PREVIEW_JPG)
    except OSError:
        pass

    server = ThreadingHTTPServer((ADMIN_BIND, ADMIN_PORT), AdminHandler)
    server.daemon_threads = True
    log(f"Admin WebUI listening on {ADMIN_BIND}:{ADMIN_PORT}")
    if not password_is_usable():
        log("WARNING: ADMIN_PASS is empty or a known default - the WebUI will "
            "refuse all requests until a real password is set.")
    if not shutil.which("ffmpeg"):
        log("WARNING: ffmpeg not found in PATH - preview will not work")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        preview.stop()


if __name__ == "__main__":
    main()
