#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scene library - the "away" cards that can take over the broadcast on demand.

The whole point is that going away must NOT restart the encoder. FFmpeg fixes
its filter graph at launch and every restart drops the RTMP connection, which
YouTube punishes on a 24/7 channel. So the broadcast pipeline carries one extra
full-frame overlay - the SCENE LAYER - that is always present:

    camera -> [scene layer] -> sponsors -> weather -> encoder

The layer reads a looping concat playlist pointing at a single file,
/config/scene_layer.png. Swapping that file atomically changes what viewers see
within about a second, with the encoder untouched and the RTMP session intact.
Live is a fully transparent frame; away is an opaque card.

Both states are rendered at the full 2560x1440 canvas ON PURPOSE. A smaller
transparent frame would be cheaper, but changing the layer's resolution
mid-stream forces FFmpeg to reconfigure the filter graph, which is a needless
risk in the VAAPI path. Measured cost of the constant full-frame blend is a few
percent of one core - far cheaper than a reconnect.

Scenes live in /config/scenes.json; each renders to /config/scenes/<id>.png.
"""

import os
import io
import re
import json
import time
import datetime

CONFIG_DIR = os.getenv("VANTAGECAM_CONFIG_DIR", "/config")
SCENES_JSON = os.path.join(CONFIG_DIR, "scenes.json")
SCENES_DIR = os.path.join(CONFIG_DIR, "scenes")
BACKGROUNDS_DIR = os.path.join(SCENES_DIR, "backgrounds")

# What the broadcast pipeline actually reads
LAYER_PNG = os.path.join(CONFIG_DIR, "scene_layer.png")
LAYER_LIST = os.path.join(CONFIG_DIR, "scene_layer.txt")
CLEAR_PNG = os.path.join(CONFIG_DIR, "scene_clear.png")

# One-word state file ("live" or a scene id) so start.sh's hot loops can read
# the on-air bus without spawning Python or parsing JSON.
PROGRAM_FILE = os.path.join(CONFIG_DIR, "program_state")

# The card the automatic camera-failure path uses as its FFmpeg input. Kept in
# sync with the nominated fallback scene so the operator styles it in the WebUI
# like any other scene instead of it being a hardcoded image.
FALLBACK_RENDER = os.path.join(CONFIG_DIR, "fallback.png")

CANVAS_W = 2560
CANVAS_H = 1440

# Seconds each concat entry lasts. This is the upper bound on how long a take
# waits to appear on air; 1s is responsive without re-reading the file madly.
LAYER_SEGMENT_SECONDS = 1

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_FALLBACKS = [
    FONT_PATH,
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

LOCATION_NAME = os.getenv("WEATHER_LOCATION", "")

# Two nominated scenes, deliberately distinct: one is shown when the camera
# FAILS, the other is what you go away with on purpose. Conflating them means a
# scheduled break tells viewers there is a technical fault.
FALLBACK_SCENE_ID = "technical"   # automatic, camera unreachable
AWAY_SCENE_ID = "away"            # deliberate: the MQTT/HA switch and toggle


def _now():
    return time.time()


# ---------------------------------------------------------------- defaults

def default_scenes():
    """Starter library. 'technical' doubles as the automatic-fallback card."""
    return {
        "technical": {
            "name": "Technical Difficulties",
            "headline": "We'll Be Right Back",
            "subtitle": "Experiencing technical difficulties - stream will resume shortly",
            "bg_color": "#12121e",
            "text_color": "#ffffff",
            "accent_color": "#6496ff",
            "background": "",
            "show_location": True,
            "show_clock": True,
        },
        "away": {
            "name": "Away",
            "headline": "Back Soon",
            "subtitle": "The live view returns shortly",
            "bg_color": "#0d1b2a",
            "text_color": "#ffffff",
            "accent_color": "#4cc9f0",
            "background": "",
            "show_location": True,
            "show_clock": True,
        },
        "closed": {
            "name": "Closed For The Season",
            "headline": "Closed For The Season",
            "subtitle": "The camera returns in the spring - thanks for watching",
            "bg_color": "#1b2432",
            "text_color": "#ffffff",
            "accent_color": "#ffb703",
            "background": "",
            "show_location": True,
            "show_clock": False,
        },
    }


def default_scene():
    return {
        "name": "New Scene",
        "headline": "Back Soon",
        "subtitle": "",
        "bg_color": "#12121e",
        "text_color": "#ffffff",
        "accent_color": "#6496ff",
        "background": "",
        "show_location": True,
        "show_clock": True,
    }


# ---------------------------------------------------------------- storage

def _atomic_write_bytes(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _atomic_write_text(path, text):
    _atomic_write_bytes(path, text.encode("utf-8"))


def _ensure_dirs():
    for d in (SCENES_DIR, BACKGROUNDS_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


def _clean_str(value, fallback="", limit=200):
    if value is None:
        return fallback
    return str(value).replace("\r", " ").replace("\n", " ").strip()[:limit]


def _clean_color(value, fallback):
    value = _clean_str(value, "", 7)
    return value if HEX_RE.match(value) else fallback


def _clean_background(value):
    """Background filenames are stored bare and must stay inside the store."""
    value = os.path.basename(_clean_str(value, "", 120))
    if not value or value.startswith("."):
        return ""
    if not value.lower().endswith(IMAGE_EXTS):
        return ""
    return value


def sanitize(scene, fallback=None):
    fallback = fallback or default_scene()
    scene = scene if isinstance(scene, dict) else {}
    return {
        "name": _clean_str(scene.get("name"), fallback["name"], 60) or fallback["name"],
        "headline": _clean_str(scene.get("headline"), fallback["headline"], 80),
        "subtitle": _clean_str(scene.get("subtitle"), fallback["subtitle"], 160),
        "bg_color": _clean_color(scene.get("bg_color"), fallback["bg_color"]),
        "text_color": _clean_color(scene.get("text_color"), fallback["text_color"]),
        "accent_color": _clean_color(scene.get("accent_color"), fallback["accent_color"]),
        "background": _clean_background(scene.get("background")),
        "show_location": bool(scene.get("show_location", fallback["show_location"])),
        "show_clock": bool(scene.get("show_clock", fallback["show_clock"])),
    }


def _read_store():
    try:
        with open(SCENES_JSON) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    scenes = data.get("scenes")
    if not isinstance(scenes, dict) or not scenes:
        scenes = default_scenes()
    clean = {}
    for sid, scene in scenes.items():
        sid = str(sid).lower()
        if ID_RE.match(sid):
            clean[sid] = sanitize(scene)
    if not clean:
        clean = {k: sanitize(v) for k, v in default_scenes().items()}
    program = data.get("program")
    if program != "live" and program not in clean:
        program = "live"
    fallback_scene = data.get("fallback_scene")
    if fallback_scene not in clean:
        fallback_scene = FALLBACK_SCENE_ID if FALLBACK_SCENE_ID in clean else sorted(clean)[0]
    away_scene = data.get("away_scene")
    if away_scene not in clean:
        away_scene = AWAY_SCENE_ID if AWAY_SCENE_ID in clean else fallback_scene
    preview = data.get("preview")
    if preview != "live" and preview not in clean:
        preview = None
    return {"scenes": clean, "program": program, "fallback_scene": fallback_scene,
            "away_scene": away_scene, "preview": preview}


def _write_store(store):
    _ensure_dirs()
    _atomic_write_text(SCENES_JSON, json.dumps({
        "scenes": store["scenes"],
        "program": store["program"],
        "fallback_scene": store["fallback_scene"],
        "away_scene": store["away_scene"],
        "preview": store.get("preview"),
    }, indent=2))


def load():
    return _read_store()


def list_scenes():
    return _read_store()["scenes"]


def get_scene(scene_id):
    return _read_store()["scenes"].get(scene_id)


# ---------------------------------------------------------------- rendering

def _font(size):
    from PIL import ImageFont
    for path in FONT_FALLBACKS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _hex_rgb(value, fallback=(18, 18, 30)):
    try:
        value = value.lstrip("#")
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, AttributeError, IndexError):
        return fallback


def _fit_text(draw, text, max_width, start_size, min_size=24):
    """Largest font size at which text fits max_width."""
    size = start_size
    while size > min_size:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 4
    return _font(min_size)


def render_scene(scene, width=CANVAS_W, height=CANVAS_H):
    """Render one scene to an opaque RGBA image."""
    from PIL import Image, ImageDraw, ImageFilter

    scene = sanitize(scene)
    bg = _hex_rgb(scene["bg_color"])
    fg = _hex_rgb(scene["text_color"], (255, 255, 255))
    accent = _hex_rgb(scene["accent_color"], (100, 150, 255))

    img = Image.new("RGBA", (width, height), bg + (255,))

    # Optional background photo, cover-fitted and dimmed so text stays legible
    bg_name = scene.get("background")
    if bg_name:
        path = os.path.join(BACKGROUNDS_DIR, bg_name)
        try:
            with Image.open(path) as raw:
                photo = raw.convert("RGB")
            scale = max(width / photo.width, height / photo.height)
            photo = photo.resize((max(1, int(photo.width * scale)),
                                  max(1, int(photo.height * scale))),
                                 Image.Resampling.LANCZOS)
            left = (photo.width - width) // 2
            top = (photo.height - height) // 2
            photo = photo.crop((left, top, left + width, top + height))
            img.paste(photo.convert("RGBA"), (0, 0))
            # Scrim: without it, light photos swallow white text entirely
            img.alpha_composite(Image.new("RGBA", (width, height), (0, 0, 0, 120)))
        except (OSError, ValueError):
            pass  # missing/corrupt background - the flat colour still renders

    draw = ImageDraw.Draw(img)
    cx = width // 2

    # Headline, auto-shrunk to fit rather than overflowing the frame
    headline = scene["headline"]
    y = height // 2 - int(height * 0.06)
    if headline:
        font = _fit_text(draw, headline, int(width * 0.84), int(height * 0.115))
        w = draw.textlength(headline, font=font)
        bbox = draw.textbbox((0, 0), headline, font=font)
        h = bbox[3] - bbox[1]
        x = cx - w / 2
        draw.text((x + 5, y + 5), headline, font=font, fill=(0, 0, 0, 190))
        draw.text((x, y), headline, font=font, fill=fg + (255,))
        y += h + int(height * 0.05)

    if scene["subtitle"]:
        font = _fit_text(draw, scene["subtitle"], int(width * 0.78), int(height * 0.038))
        w = draw.textlength(scene["subtitle"], font=font)
        x = cx - w / 2
        draw.text((x + 3, y + 3), scene["subtitle"], font=font, fill=(0, 0, 0, 170))
        draw.text((x, y), scene["subtitle"], font=font, fill=(210, 210, 215, 255))

    # Accent rule above the headline, a cheap way to look deliberate
    rule_w = int(width * 0.12)
    rule_y = height // 2 - int(height * 0.10)
    draw.rectangle([cx - rule_w // 2, rule_y, cx + rule_w // 2, rule_y + 6],
                   fill=accent + (255,))

    if scene["show_location"] and LOCATION_NAME:
        font = _font(int(height * 0.032))
        w = draw.textlength(LOCATION_NAME, font=font)
        draw.text((cx - w / 2, rule_y - int(height * 0.06)), LOCATION_NAME,
                  font=font, fill=accent + (255,))

    if scene["show_clock"]:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        font = _font(int(height * 0.028))
        w = draw.textlength(stamp, font=font)
        draw.text((width - w - int(width * 0.02), height - int(height * 0.07)),
                  stamp, font=font, fill=(140, 140, 150, 255))

    return img


def render_to_disk(scene_id, scene=None):
    """Render one scene to /config/scenes/<id>.png. Returns the path."""
    _ensure_dirs()
    scene = scene or get_scene(scene_id)
    if scene is None:
        raise KeyError(scene_id)
    img = render_scene(scene)
    path = os.path.join(SCENES_DIR, f"{scene_id}.png")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    _atomic_write_bytes(path, buf.getvalue())
    return path


def render_all():
    store = _read_store()
    for sid, scene in store["scenes"].items():
        try:
            render_to_disk(sid, scene)
        except Exception:
            pass
    return sorted(store["scenes"])


# ---------------------------------------------------------------- the layer

def ensure_layer_assets():
    """Create the transparent frame and the concat playlist the encoder reads."""
    _ensure_dirs()
    if not os.path.exists(CLEAR_PNG):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0)).save(buf, "PNG", optimize=True)
        _atomic_write_bytes(CLEAR_PNG, buf.getvalue())
    # The playlist is rewritten every boot: it embeds an absolute path, and
    # CONFIG_DIR can differ between installs.
    _atomic_write_text(LAYER_LIST,
                       f"file '{LAYER_PNG}'\nduration {LAYER_SEGMENT_SECONDS}\n"
                       f"file '{LAYER_PNG}'\n")
    if not os.path.exists(LAYER_PNG):
        _copy_atomic(CLEAR_PNG, LAYER_PNG)


def _copy_atomic(src, dest):
    with open(src, "rb") as f:
        data = f.read()
    _atomic_write_bytes(dest, data)


def apply_layer(program):
    """Point the live layer at 'live' (transparent) or a scene's card."""
    ensure_layer_assets()
    if program == "live":
        _copy_atomic(CLEAR_PNG, LAYER_PNG)
    else:
        path = os.path.join(SCENES_DIR, f"{program}.png")
        if not os.path.exists(path):
            render_to_disk(program)
        _copy_atomic(path, LAYER_PNG)
    try:
        _atomic_write_text(PROGRAM_FILE, program)
    except OSError:
        pass
    return program


def sync_fallback_render(store=None):
    """Keep /config/fallback.png as the nominated fallback scene's card.

    That file is the FFmpeg *input* for the automatic camera-failure pipeline
    (the camera is gone, so there is nothing to overlay onto). Pointing it at a
    real scene means the technical-difficulties card is editable in the WebUI
    like every other scene instead of being hardcoded in weather.py.
    """
    store = store or _read_store()
    sid = store["fallback_scene"]
    path = os.path.join(SCENES_DIR, f"{sid}.png")
    if not os.path.exists(path):
        try:
            render_to_disk(sid, store["scenes"].get(sid))
        except Exception:
            return False
    try:
        _copy_atomic(path, FALLBACK_RENDER)
        return True
    except OSError:
        return False


def set_program(target):
    """Take 'live' or a scene id to air. Returns (ok, message, state)."""
    store = _read_store()
    if target != "live" and target not in store["scenes"]:
        return False, f"unknown scene '{target}'", state()
    # Vision-mixer convention: a take swaps the buses, so Preview immediately
    # shows what you would cut back to. Without this the operator is left
    # staring at two identical monitors after every take.
    previous = store["program"]
    store["program"] = target
    if previous != target:
        store["preview"] = previous
    _write_store(store)
    try:
        apply_layer(target)
    except Exception as e:
        return False, f"scene saved but the layer could not be swapped: {e}", state()
    if target == "live":
        msg = "Camera is on air."
    else:
        msg = f"'{store['scenes'][target]['name']}' is on air."
    return True, msg, state()


def set_preview(target):
    """Choose what the Preview bus shows. None = the sensible opposite."""
    store = _read_store()
    if target is not None and target != "live" and target not in store["scenes"]:
        return False, f"unknown scene '{target}'", state()
    store["preview"] = target
    _write_store(store)
    return True, "Preview set.", state()


def resolve_preview(store=None):
    """What the Preview bus should show: explicit choice, else the opposite bus."""
    store = store or _read_store()
    if store.get("preview"):
        return store["preview"]
    if store["program"] == "live":
        return store["away_scene"]
    return "live"


def state():
    store = _read_store()
    program = store["program"]
    preview = resolve_preview(store)
    return {
        "program": program,
        "preview": preview,
        "on_air": "camera" if program == "live" else "scene",
        "program_name": ("Camera" if program == "live"
                         else store["scenes"].get(program, {}).get("name", program)),
        "preview_name": ("Camera" if preview == "live"
                         else store["scenes"].get(preview, {}).get("name", preview)),
        "fallback_scene": store["fallback_scene"],
        "away_scene": store["away_scene"],
        "scenes": store["scenes"],
    }


# ---------------------------------------------------------------- CRUD

def save_scene(scene_id, scene):
    store = _read_store()
    scene_id = str(scene_id or "").strip().lower()
    if not ID_RE.match(scene_id):
        raise ValueError("scene id must be lowercase letters, digits, - or _ (max 40)")
    clean = sanitize(scene, store["scenes"].get(scene_id))
    store["scenes"][scene_id] = clean
    _write_store(store)
    render_to_disk(scene_id, clean)
    # Editing the card that is currently on air must update the air instantly
    if store["program"] == scene_id:
        apply_layer(scene_id)
    if store["fallback_scene"] == scene_id:
        sync_fallback_render(store)
    return clean


def delete_scene(scene_id):
    store = _read_store()
    if scene_id not in store["scenes"]:
        raise KeyError(scene_id)
    if len(store["scenes"]) <= 1:
        raise ValueError("at least one scene must remain")
    if store["program"] == scene_id:
        raise ValueError("that scene is on air - take the camera back first")
    del store["scenes"][scene_id]
    if store["fallback_scene"] == scene_id:
        store["fallback_scene"] = sorted(store["scenes"])[0]
    if store["away_scene"] == scene_id:
        store["away_scene"] = sorted(store["scenes"])[0]
    if store.get("preview") == scene_id:
        store["preview"] = None
    _write_store(store)
    try:
        os.remove(os.path.join(SCENES_DIR, f"{scene_id}.png"))
    except OSError:
        pass
    return True


def resolve_target(target):
    """Map a requested target to a real bus value.

    An exact scene id always wins, so a scene literally called 'away' is never
    shadowed by the alias. 'away' otherwise means the nominated away scene and
    'toggle' flips between it and the camera - both for MQTT/Home Assistant.
    """
    store = _read_store()
    target = str(target or "").strip().lower()
    if target == "live" or target in store["scenes"]:
        return target
    if target in ("away", "on", "true", "1"):
        return store["away_scene"]
    if target in ("off", "false", "0", "camera"):
        return "live"
    if target == "toggle":
        return "live" if store["program"] != "live" else store["away_scene"]
    return target                      # unknown - set_program reports it


def set_away_scene(scene_id):
    store = _read_store()
    if scene_id not in store["scenes"]:
        raise KeyError(scene_id)
    store["away_scene"] = scene_id
    _write_store(store)
    return scene_id


def set_fallback_scene(scene_id):
    store = _read_store()
    if scene_id not in store["scenes"]:
        raise KeyError(scene_id)
    store["fallback_scene"] = scene_id
    _write_store(store)
    sync_fallback_render(store)
    return scene_id


def background_path(name):
    """Absolute path of a stored background, or None if the name is unsafe."""
    name = _clean_background(name)
    if not name:
        return None
    return os.path.join(BACKGROUNDS_DIR, name)


def list_backgrounds():
    _ensure_dirs()
    try:
        return sorted(n for n in os.listdir(BACKGROUNDS_DIR)
                      if n.lower().endswith(IMAGE_EXTS))
    except OSError:
        return []


def init():
    """Boot-time setup: assets exist, scenes rendered, layer matches stored state."""
    _ensure_dirs()
    store = _read_store()
    _write_store(store)               # materialise defaults on first run
    ensure_layer_assets()
    for sid, scene in store["scenes"].items():
        try:
            render_to_disk(sid, scene)
        except Exception:
            pass
    try:
        apply_layer(store["program"])
    except Exception:
        apply_layer("live")
    sync_fallback_render(store)
    return store


# ---------------------------------------------------------------- CLI

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    cmd = args[0] if args else "state"
    if cmd == "init":
        store = init()
        print(f"scenes: {', '.join(sorted(store['scenes']))}")
        print(f"program: {store['program']}")
    elif cmd == "state":
        print(json.dumps(state(), indent=2))
    elif cmd == "take" and len(args) > 1:
        ok, msg, _ = set_program(resolve_target(args[1]))
        print(msg)
        sys.exit(0 if ok else 1)
    elif cmd == "render":
        print("rendered: " + ", ".join(render_all()))
    elif cmd == "layer":
        # Which state the encoder is currently being fed - used by the healthcheck
        print(state()["program"])
    else:
        sys.exit(f"usage: {sys.argv[0]} [init|state|take <live|id>|render|layer]")
