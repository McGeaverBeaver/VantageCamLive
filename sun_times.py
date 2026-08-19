#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sunrise/sunset driven DAY / NIGHT switching.

The fixed-clock schedule (DAY_START_HOUR / DAY_END_HOUR) drifts badly across
the year: at 44°N, sunset moves by more than four hours between June and
December, so a 20:00 switch is an hour early in summer and three hours late in
winter. This resolves the current mode from real solar times for the camera's
own coordinates instead.

Times come from Open-Meteo (already used for the weather overlay, no API key),
are cached per-day in /config/sun_times.json, and the resolved mode is written
to /config/day_night so start.sh's hot loops read a file instead of spawning
Python.

Falls back to the clock schedule whenever the lookup fails, so a network
outage can never leave the overlays stuck in the wrong mode.
"""

import os
import json
import datetime

CONFIG_DIR = os.getenv("VANTAGECAM_CONFIG_DIR", "/config")
CACHE_FILE = os.path.join(CONFIG_DIR, "sun_times.json")
MODE_FILE = os.path.join(CONFIG_DIR, "day_night")

LAT = os.getenv("WEATHER_LAT", "40.7128")
LON = os.getenv("WEATHER_LON", "-74.0060")
TIMEZONE = os.getenv("WEATHER_TIMEZONE", "America/Toronto")

# Positive shifts DAY later at dawn and earlier at dusk (a tighter day);
# negative widens it. Useful because a camera goes usably dark a little before
# astronomical sunset.
SUN_OFFSET_MINUTES = int(os.getenv("SUN_OFFSET_MINUTES", "0") or 0)

DAY_START_HOUR = int(os.getenv("DAY_START_HOUR", "6") or 6)
DAY_END_HOUR = int(os.getenv("DAY_END_HOUR", "20") or 20)


def _clock_mode(now=None):
    now = now or datetime.datetime.now()
    return "DAY" if DAY_START_HOUR <= now.hour < DAY_END_HOUR else "NIGHT"


def _load_cache():
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(data):
    try:
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass


def fetch_sun_times(day=None):
    """{'date','sunrise','sunset'} for the given local date, cached per day."""
    day = day or datetime.date.today().isoformat()
    cache = _load_cache()
    if cache.get("date") == day and cache.get("sunrise") and cache.get("sunset"):
        return cache

    import requests   # imported lazily so the clock path needs no dependency
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
           f"&daily=sunrise,sunset&timezone={TIMEZONE}&start_date={day}&end_date={day}")
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    daily = resp.json().get("daily", {})
    sunrise = (daily.get("sunrise") or [None])[0]
    sunset = (daily.get("sunset") or [None])[0]
    if not sunrise or not sunset:
        raise ValueError("Open-Meteo returned no sunrise/sunset")
    data = {"date": day, "sunrise": sunrise, "sunset": sunset}
    _save_cache(data)
    return data


def resolve_mode(now=None):
    """(mode, source) - source is 'sun' or 'clock' when a fallback was used."""
    now = now or datetime.datetime.now()
    try:
        times = fetch_sun_times(now.date().isoformat())
        sunrise = datetime.datetime.fromisoformat(times["sunrise"])
        sunset = datetime.datetime.fromisoformat(times["sunset"])
        shift = datetime.timedelta(minutes=SUN_OFFSET_MINUTES)
        # Polar edge case: with the sun up (or down) all day the window can
        # invert; treat a non-positive window as "whole day is NIGHT".
        start, end = sunrise + shift, sunset - shift
        if end <= start:
            return ("DAY" if (sunset - sunrise) > datetime.timedelta(hours=12) else "NIGHT"), "sun"
        return ("DAY" if start <= now < end else "NIGHT"), "sun"
    except Exception:
        return _clock_mode(now), "clock"


def write_mode():
    mode, source = resolve_mode()
    try:
        tmp = MODE_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(mode)
        os.replace(tmp, MODE_FILE)
    except OSError:
        pass
    return mode, source


if __name__ == "__main__":
    import sys
    if "--json" in sys.argv:
        mode, source = resolve_mode()
        cache = _load_cache()
        print(json.dumps({"mode": mode, "source": source,
                          "sunrise": cache.get("sunrise"), "sunset": cache.get("sunset"),
                          "offset_minutes": SUN_OFFSET_MINUTES}, indent=2))
    else:
        mode, source = write_mode()
        print(f"{mode} ({source})")
