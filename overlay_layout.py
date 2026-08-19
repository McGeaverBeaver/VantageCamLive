#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Overlay layout store — shared by start.sh (broadcast pipeline), admin_api.py
(preview pipeline + WebUI) so all three agree on where overlays sit.

Coordinates are always in the 2560x1440 composition canvas that start.sh builds
before the final scale to YOUTUBE_WIDTH/HEIGHT, so a saved layout looks the same
whether you broadcast 1080p, 1440p or 4K.

Persisted as /config/overlay_layout.json. A shell fragment
(/config/overlay_layout.sh) with the same values is written alongside it so
start.sh and its background managers can consume the layout without a JSON
parser. The fragment only ever contains INTEGER assignments, so sourcing it
cannot execute anything unexpected.
"""

import os
import json

CONFIG_DIR = os.getenv("VANTAGECAM_CONFIG_DIR", "/config")
LAYOUT_JSON = os.path.join(CONFIG_DIR, "overlay_layout.json")
LAYOUT_SH = os.path.join(CONFIG_DIR, "overlay_layout.sh")

# The composition canvas start.sh scales the camera to before overlaying.
CANVAS_W = 2560
CANVAS_H = 1440

MIN_SIZE = 32

# key -> (label, description) for the WebUI
SLOTS = {
    "tl": "Sponsor — Top Left",
    "tr": "Sponsor — Top Right",
    "weather": "Weather + Alerts",
}


def _int(value, fallback):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return fallback


def defaults():
    """Positions matching the historical hardcoded 20px-margin corners."""
    tl = _int(os.getenv("SCALE_TL", "500"), 500)
    tr = _int(os.getenv("SCALE_TR", "400"), 400)
    wx, wy = 900, 500
    return {
        "tl": {"x": 20, "y": 20, "w": tl, "h": tl, "enabled": True},
        "tr": {"x": CANVAS_W - tr - 20, "y": 20, "w": tr, "h": tr, "enabled": True},
        "weather": {"x": CANVAS_W - wx - 20, "y": CANVAS_H - wy - 20,
                    "w": wx, "h": wy, "enabled": True},
    }


def _sanitize(slot, box, fallback):
    """Clamp one overlay box so it always lands fully inside the canvas."""
    w = max(MIN_SIZE, min(CANVAS_W, _int(box.get("w"), fallback["w"])))
    h = max(MIN_SIZE, min(CANVAS_H, _int(box.get("h"), fallback["h"])))
    x = max(0, min(CANVAS_W - w, _int(box.get("x"), fallback["x"])))
    y = max(0, min(CANVAS_H - h, _int(box.get("y"), fallback["y"])))
    enabled = box.get("enabled", fallback["enabled"])
    return {"x": x, "y": y, "w": w, "h": h, "enabled": bool(enabled)}


def load():
    """Current layout, falling back to defaults for anything missing/invalid."""
    base = defaults()
    try:
        with open(LAYOUT_JSON) as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return base
    overlays = stored.get("overlays", stored) if isinstance(stored, dict) else {}
    out = {}
    for slot, fallback in base.items():
        box = overlays.get(slot) if isinstance(overlays, dict) else None
        out[slot] = _sanitize(slot, box or {}, fallback) if isinstance(box, dict) else fallback
    return out


def shell_fragment(layout):
    lines = []
    for slot, box in layout.items():
        prefix = f"LAYOUT_{slot.upper()}"
        lines.append(f"{prefix}_X={box['x']}")
        lines.append(f"{prefix}_Y={box['y']}")
        lines.append(f"{prefix}_W={box['w']}")
        lines.append(f"{prefix}_H={box['h']}")
        lines.append(f"{prefix}_ENABLED={1 if box['enabled'] else 0}")
    return "\n".join(lines) + "\n"


def _atomic_write(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def save(layout):
    """Persist a sanitized layout as JSON plus the shell fragment."""
    base = defaults()
    clean = {slot: _sanitize(slot, (layout or {}).get(slot) or {}, fallback)
             for slot, fallback in base.items()}
    _atomic_write(LAYOUT_JSON, json.dumps(
        {"canvas": {"width": CANVAS_W, "height": CANVAS_H}, "overlays": clean}, indent=2))
    _atomic_write(LAYOUT_SH, shell_fragment(clean))
    return clean


def sync():
    """Regenerate the shell fragment from whatever is currently stored."""
    layout = load()
    _atomic_write(LAYOUT_SH, shell_fragment(layout))
    return layout


def filter_spec(layout, slot):
    """(scale_filter, overlay_coords) for one slot's ffmpeg filter chain."""
    box = layout[slot]
    # decrease keeps the source aspect ratio, so resizing a box never distorts
    # a sponsor logo; the image anchors to the box's top-left corner.
    return (f"scale={box['w']}:{box['h']}:force_original_aspect_ratio=decrease",
            f"{box['x']}:{box['y']}")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "sh"
    if mode == "sh":
        # Emit (and persist) the shell fragment for start.sh to source
        sys.stdout.write(shell_fragment(sync()))
    elif mode == "json":
        print(json.dumps({"canvas": {"width": CANVAS_W, "height": CANVAS_H},
                          "overlays": load()}, indent=2))
    elif mode == "reset":
        print(json.dumps(save(defaults()), indent=2))
    else:
        sys.exit(f"usage: {sys.argv[0]} [sh|json|reset]")
