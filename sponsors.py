#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sponsor scheduling and airtime reporting.

Adds two things the plain drag-a-file-into-a-folder workflow cannot express:

  * a run window per logo (start/end date, plus an on/off switch), so a
    sponsorship that ends on the 31st stops airing on the 31st without anyone
    remembering to delete the file, and next month's sponsor can be loaded in
    advance; and
  * an airtime ledger - impressions and seconds on air, per day - so you can
    tell a sponsor exactly what they got.

Schedule lives in /config/ads/sponsors.json, the ledger in
/config/sponsor_stats.json. Both are written under an flock because the
top-left and top-right rotation managers are separate processes.
"""

import os
import re
import csv
import json
import time
import fcntl
import datetime

CONFIG_DIR = os.getenv("VANTAGECAM_CONFIG_DIR", "/config")
ADS_BASE = os.path.join(CONFIG_DIR, "ads")
SCHEDULE_FILE = os.path.join(ADS_BASE, "sponsors.json")
STATS_FILE = os.path.join(CONFIG_DIR, "sponsor_stats.json")

SLOTS = ("topleft", "topright")
MODES = ("DAY", "NIGHT")
EXTS = (".png", ".jpg", ".jpeg", ".webp")

MAX_DAYS_KEPT = 120          # per-logo daily history retained
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _key(slot, mode, name):
    return f"{slot}/{mode}/{name}"


def _load(path, default):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def _save_locked(path, mutate):
    """Read-modify-write under an exclusive lock (two managers write stats)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock_path = path + ".lock"
    with open(lock_path, "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
        except OSError:
            pass
        data = _load(path, {})
        mutate(data)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError:
            pass
    return data


# ---------------------------------------------------------------- schedule

def _clean_date(value):
    value = (value or "").strip()
    return value if DATE_RE.match(value) else ""


def default_entry():
    return {"enabled": True, "start": "", "end": "", "note": ""}


def get_schedule():
    return _load(SCHEDULE_FILE, {})


def set_entry(slot, mode, name, enabled=None, start=None, end=None, note=None):
    if slot not in SLOTS or mode not in MODES:
        raise ValueError("unknown slot or mode")
    key = _key(slot, mode, os.path.basename(name))

    def mutate(data):
        entry = {**default_entry(), **data.get(key, {})}
        if enabled is not None:
            entry["enabled"] = bool(enabled)
        if start is not None:
            entry["start"] = _clean_date(start)
        if end is not None:
            entry["end"] = _clean_date(end)
        if note is not None:
            entry["note"] = str(note)[:200]
        data[key] = entry

    _save_locked(SCHEDULE_FILE, mutate)
    return get_schedule().get(key, default_entry())


def forget(slot, mode, name):
    """Drop schedule + stats for a deleted logo."""
    key = _key(slot, mode, os.path.basename(name))
    _save_locked(SCHEDULE_FILE, lambda d: d.pop(key, None))
    _save_locked(STATS_FILE, lambda d: d.pop(key, None))


def is_live(entry, today=None):
    """Is this logo inside its run window right now?"""
    if not entry.get("enabled", True):
        return False, "disabled"
    today = today or datetime.date.today().isoformat()
    start, end = entry.get("start", ""), entry.get("end", "")
    if start and today < start:
        return False, f"starts {start}"
    if end and today > end:
        return False, f"ended {end}"
    return True, "live"


# ---------------------------------------------------------------- files

def scan(slot, mode):
    directory = os.path.join(ADS_BASE, slot, mode)
    try:
        return sorted(n for n in os.listdir(directory)
                      if os.path.splitext(n)[1].lower() in EXTS
                      and os.path.isfile(os.path.join(directory, n)))
    except OSError:
        return []


def eligible(slot, mode, today=None):
    """Full paths of the logos that should be airing right now."""
    schedule = get_schedule()
    out = []
    for name in scan(slot, mode):
        entry = {**default_entry(), **schedule.get(_key(slot, mode, name), {})}
        live, _ = is_live(entry, today)
        if live:
            out.append(os.path.join(ADS_BASE, slot, mode, name))
    return out


# ---------------------------------------------------------------- ledger

def record_airtime(slot, mode, name, seconds):
    key = _key(slot, mode, os.path.basename(name))
    seconds = max(0, min(86400, int(float(seconds or 0))))
    today = datetime.date.today().isoformat()
    now = int(time.time())

    def mutate(data):
        entry = data.get(key) or {"impressions": 0, "seconds": 0, "first_shown": now, "days": {}}
        entry["impressions"] = entry.get("impressions", 0) + 1
        entry["seconds"] = entry.get("seconds", 0) + seconds
        entry["last_shown"] = now
        entry.setdefault("first_shown", now)
        days = entry.setdefault("days", {})
        days[today] = days.get(today, 0) + seconds
        for old in sorted(days)[:-MAX_DAYS_KEPT]:
            days.pop(old, None)
        data[key] = entry

    _save_locked(STATS_FILE, mutate)


def get_stats():
    return _load(STATS_FILE, {})


def _fmt_hms(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


def report(days=30):
    """Per-logo schedule + airtime, newest activity first."""
    schedule, stats = get_schedule(), get_stats()
    today = datetime.date.today()
    window = {(today - datetime.timedelta(days=i)).isoformat() for i in range(days)}
    rows = []
    for slot in SLOTS:
        for mode in MODES:
            for name in scan(slot, mode):
                key = _key(slot, mode, name)
                entry = {**default_entry(), **schedule.get(key, {})}
                st = stats.get(key, {})
                live, why = is_live(entry, today.isoformat())
                recent = sum(v for d, v in (st.get("days") or {}).items() if d in window)
                rows.append({
                    "slot": slot, "mode": mode, "name": name, "key": key,
                    "enabled": entry["enabled"], "start": entry["start"],
                    "end": entry["end"], "note": entry["note"],
                    "live": live, "status": why,
                    "impressions": st.get("impressions", 0),
                    "seconds": st.get("seconds", 0),
                    "airtime": _fmt_hms(st.get("seconds", 0)),
                    "seconds_window": recent,
                    "airtime_window": _fmt_hms(recent),
                    "last_shown": st.get("last_shown"),
                })
    rows.sort(key=lambda r: (-(r["last_shown"] or 0), r["slot"], r["name"]))
    return {"days": days, "generated": int(time.time()), "rows": rows}


def report_csv(days=30):
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Slot", "Mode", "File", "Status", "Starts", "Ends",
                f"Impressions (all time)", "Airtime (all time)",
                f"Airtime (last {days}d)", "Last shown", "Note"])
    for r in report(days)["rows"]:
        last = (datetime.datetime.fromtimestamp(r["last_shown"]).strftime("%Y-%m-%d %H:%M")
                if r["last_shown"] else "")
        w.writerow([r["slot"], r["mode"], r["name"], r["status"], r["start"], r["end"],
                    r["impressions"], r["airtime"], r["airtime_window"], last, r["note"]])
    return buf.getvalue()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "list" and len(sys.argv) >= 4:
        for path in eligible(sys.argv[2], sys.argv[3]):
            print(path)
    elif cmd == "record" and len(sys.argv) >= 6:
        record_airtime(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == "csv":
        sys.stdout.write(report_csv())
    else:
        for r in report()["rows"]:
            mark = "LIVE " if r["live"] else "  -  "
            print(f"{mark} {r['slot']:8s} {r['mode']:5s} {r['name'][:28]:28s} "
                  f"{r['status']:12s} {r['impressions']:6d} imp  {r['airtime']:>9s}")
