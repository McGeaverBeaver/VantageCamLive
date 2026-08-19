#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Broadcast event timeline.

A compact, append-only record of the things an operator actually cares about —
encoder starts and stops, fallback transitions, watchdog restarts, visibility
changes, sponsor rotations — so a pattern (say, a nightly flap at 03:00) is
visible at a glance instead of buried in megabytes of FFmpeg log.

Stored as JSON Lines in /config/events.jsonl. start.sh appends the same format
directly from bash, so this module is only one of two writers; both are
append-only single-line writes, which are atomic enough for this purpose.
"""

import os
import re
import json
import time

CONFIG_DIR = os.getenv("VANTAGECAM_CONFIG_DIR", "/config")
EVENTS_FILE = os.path.join(CONFIG_DIR, "events.jsonl")

MAX_EVENTS = 2000          # trimmed back to this when the cap is exceeded
TRIM_TRIGGER = 3000

LEVELS = ("info", "warn", "error", "success")

# Known event types -> (icon, default level). Unknown types still record fine.
TYPES = {
    "boot":            ("power", "info"),
    "encoder_start":   ("play", "success"),
    "encoder_stop":    ("stop", "warn"),
    "encoder_fail":    ("alert", "error"),
    "fallback_enter":  ("alert", "warn"),
    "fallback_exit":   ("play", "success"),
    "operator_stop":   ("stop", "warn"),
    "operator_start":  ("play", "success"),
    "watchdog":        ("shield", "warn"),
    "visibility":      ("eye", "info"),
    "layout":          ("layout", "info"),
    "audio":           ("audio", "info"),
    "sponsor":         ("sponsor", "info"),
    "camera_down":     ("camera", "error"),
    "camera_up":       ("camera", "success"),
}


def record(event_type, message, level=None):
    """Append one event. Never raises - telemetry must not break the caller."""
    try:
        level = level or TYPES.get(event_type, ("", "info"))[1]
        if level not in LEVELS:
            level = "info"
        line = json.dumps({
            "ts": int(time.time()),
            "type": str(event_type)[:40],
            "level": level,
            "msg": str(message)[:400],
        }, separators=(",", ":"))
        with open(EVENTS_FILE, "a") as f:
            f.write(line + "\n")
        _maybe_trim()
    except OSError:
        pass


def _maybe_trim():
    """Keep the file bounded without rewriting it on every append."""
    try:
        if os.path.getsize(EVENTS_FILE) < 300 * 1024:
            return
        with open(EVENTS_FILE) as f:
            lines = f.readlines()
        if len(lines) <= TRIM_TRIGGER:
            return
        tmp = EVENTS_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.writelines(lines[-MAX_EVENTS:])
        os.replace(tmp, EVENTS_FILE)
    except OSError:
        pass


def read(limit=100, since=None, types=None):
    """Most recent events first. Tolerates partial/corrupt lines."""
    try:
        with open(EVENTS_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 512 * 1024))
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if since is not None and ev.get("ts", 0) < since:
            continue
        if types and ev.get("type") not in types:
            continue
        out.append(ev)
    out.reverse()
    return out[:max(1, min(1000, limit))]


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "record":
        record(sys.argv[2], " ".join(sys.argv[3:]) or "")
    else:
        for e in read(int(sys.argv[2]) if len(sys.argv) > 2 else 40):
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e['ts']))} "
                  f"[{e['level']:7s}] {e['type']:15s} {e['msg']}")
