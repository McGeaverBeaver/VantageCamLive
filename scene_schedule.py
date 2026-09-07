#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Optional scene scheduler - take a card to air (or return the camera) at a fixed
clock time or at real sunrise/sunset.

OFF BY DEFAULT. Nothing here runs until the operator enables it in the WebUI,
and the daemon re-reads that flag every tick, so turning it off takes effect
immediately without a restart.

Two behaviours that matter more than the feature itself:

  * Rules are EDGE-TRIGGERED. A rule fires once, at its moment. If you take the
    camera back by hand ten minutes later, the scheduler does not fight you - it
    stays out of the way until the next scheduled moment. A scheduler that
    continuously enforces state would make manual control useless.

  * A sun lookup failure does not silently skip a rule. Sunrise moves by about
    four minutes a day, so yesterday's cached time is far better than not
    firing at all and leaving the camera up all night. Stale times are used with
    a warning rather than treated as fatal.

Rules live in /config/scene_schedule.json.
"""

import os
import sys
import json
import time
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenes  # noqa: E402

CONFIG_DIR = os.getenv("VANTAGECAM_CONFIG_DIR", "/config")
SCHEDULE_JSON = os.path.join(CONFIG_DIR, "scene_schedule.json")

TICK_SECONDS = 30
# How far back a rule may be "due". Longer than the tick so a slow tick or a
# brief clock wobble cannot make a rule vanish, short enough that a rule which
# fired hours ago is not re-applied.
DUE_WINDOW_SECONDS = 300
MAX_RULES = 40

EVENTS = ("sunrise", "sunset")
TYPES = ("sun", "clock")
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]          # 0 = Monday, matching date.weekday()
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def log(msg):
    print(f"[Schedule] {msg}", flush=True)


# ---------------------------------------------------------------- storage

def _atomic_write(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def default_store():
    return {
        "enabled": False,          # nothing happens until the operator opts in
        "apply_on_start": True,    # reconcile after a restart (see reconcile())
        "rules": [],
        "last_tick": 0,
    }


def _clean_rule(rule, index):
    if not isinstance(rule, dict):
        return None
    rtype = rule.get("type")
    if rtype not in TYPES:
        return None
    action = str(rule.get("action", "")).strip().lower()
    if not action:
        return None
    try:
        offset = int(rule.get("offset_minutes", 0) or 0)
    except (TypeError, ValueError):
        offset = 0
    offset = max(-720, min(720, offset))
    days = rule.get("days")
    if not isinstance(days, list) or not days:
        days = list(ALL_DAYS)
    days = sorted({int(d) for d in days if isinstance(d, (int, float)) and 0 <= int(d) <= 6})
    if not days:
        days = list(ALL_DAYS)

    clean = {
        "id": str(rule.get("id") or f"rule{index}")[:40],
        "enabled": bool(rule.get("enabled", True)),
        "type": rtype,
        "action": action,
        "offset_minutes": offset,
        "days": days,
    }
    if rtype == "sun":
        clean["event"] = rule.get("event") if rule.get("event") in EVENTS else "sunset"
        clean["time"] = ""
    else:
        raw = str(rule.get("time", "") or "").strip()
        try:
            hh, mm = raw.split(":")[:2]
            clean["time"] = "%02d:%02d" % (max(0, min(23, int(hh))), max(0, min(59, int(mm))))
        except (ValueError, IndexError):
            return None
        clean["event"] = ""
        clean["offset_minutes"] = 0
    return clean


def load():
    base = default_store()
    try:
        with open(SCHEDULE_JSON) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return base
    if not isinstance(data, dict):
        return base
    rules = []
    for i, rule in enumerate(data.get("rules") or []):
        clean = _clean_rule(rule, i)
        if clean:
            rules.append(clean)
        if len(rules) >= MAX_RULES:
            break
    return {
        "enabled": bool(data.get("enabled", False)),
        "apply_on_start": bool(data.get("apply_on_start", True)),
        "rules": rules,
        "last_tick": float(data.get("last_tick") or 0),
    }


def save(store):
    clean = {
        "enabled": bool(store.get("enabled", False)),
        "apply_on_start": bool(store.get("apply_on_start", True)),
        "rules": [r for r in (_clean_rule(x, i) for i, x in enumerate(store.get("rules") or []))
                  if r],
        "last_tick": float(store.get("last_tick") or 0),
    }
    _atomic_write(SCHEDULE_JSON, json.dumps(clean, indent=2))
    return clean


# ---------------------------------------------------------------- sun times

_sun_warned = False


def sun_times_for(day):
    """(sunrise, sunset) datetimes for a date, or (None, None).

    Falls back to whatever is cached when the lookup fails - a four-minute-stale
    sunrise beats a rule that never fires.
    """
    global _sun_warned
    import sun_times
    iso = day.isoformat()
    try:
        data = sun_times.fetch_sun_times(iso)
        _sun_warned = False
    except Exception as e:
        data = sun_times._load_cache()
        if not data or not data.get("sunrise"):
            if not _sun_warned:
                log(f"sun times unavailable and nothing cached ({e}) - sun rules cannot fire")
                _sun_warned = True
            return None, None
        if not _sun_warned:
            log(f"sun lookup failed ({e}); using cached times from {data.get('date')} "
                f"- accurate to a few minutes")
            _sun_warned = True
    try:
        sunrise = datetime.datetime.fromisoformat(data["sunrise"])
        sunset = datetime.datetime.fromisoformat(data["sunset"])
    except (KeyError, ValueError):
        return None, None
    # Cached times carry their own date; move them onto the day we asked about
    return (datetime.datetime.combine(day, sunrise.time()),
            datetime.datetime.combine(day, sunset.time()))


def rule_time_on(rule, day):
    """When this rule fires on a given date, or None if it does not."""
    if day.weekday() not in rule["days"]:
        return None
    if rule["type"] == "clock":
        try:
            hh, mm = (int(x) for x in rule["time"].split(":"))
        except (ValueError, AttributeError):
            return None
        return datetime.datetime.combine(day, datetime.time(hh, mm))
    sunrise, sunset = sun_times_for(day)
    base = sunrise if rule["event"] == "sunrise" else sunset
    if base is None:
        return None
    return base + datetime.timedelta(minutes=rule["offset_minutes"])


def next_fire(rule, now=None, search_days=8):
    now = now or datetime.datetime.now()
    for i in range(search_days):
        day = (now + datetime.timedelta(days=i)).date()
        when = rule_time_on(rule, day)
        if when and when > now:
            return when
    return None


def last_fire(rule, now=None, search_days=8):
    now = now or datetime.datetime.now()
    for i in range(search_days):
        day = (now - datetime.timedelta(days=i)).date()
        when = rule_time_on(rule, day)
        if when and when <= now:
            return when
    return None


# ---------------------------------------------------------------- evaluation

def due_rules(store, now, since):
    """Enabled rules whose moment fell in (since, now]."""
    out = []
    for rule in store["rules"]:
        if not rule["enabled"]:
            continue
        when = last_fire(rule, now, search_days=2)
        if when and when > since:
            out.append((when, rule))
    out.sort(key=lambda x: x[0])
    return out


def apply_action(action, why):
    """Take the action's target to air. Unknown targets are reported, not raised."""
    target = scenes.resolve_target(action)
    ok, msg, state = scenes.set_program(target)
    if ok:
        log(f"{why}: {msg}")
        try:
            import events
            events.record("schedule", f"Scheduled: {state['program_name']} ({why})",
                          "info" if state["program"] == "live" else "warn")
        except Exception:
            pass
    else:
        log(f"{why}: ignored - {msg}")
    return ok


def tick(now=None):
    """One evaluation pass. Returns the action applied, or None."""
    now = now or datetime.datetime.now()
    store = load()
    if not store["enabled"]:
        return None
    since_ts = store["last_tick"] or (now.timestamp() - DUE_WINDOW_SECONDS)
    since = datetime.datetime.fromtimestamp(
        max(since_ts, now.timestamp() - DUE_WINDOW_SECONDS))
    fired = due_rules(store, now, since)
    store["last_tick"] = now.timestamp()
    save(store)
    if not fired:
        return None
    # If several rules came due in the same window the newest one wins - it is
    # the state the operator most recently asked for.
    when, rule = fired[-1]
    apply_action(rule["action"], f"rule '{describe(rule)}' at {when.strftime('%H:%M')}")
    return rule["action"]


def reconcile(now=None):
    """After a restart, put the air back where the schedule says it should be.

    Without this, a container that restarts at 2am comes back on camera even
    though the 11pm 'go away' rule already fired.
    """
    now = now or datetime.datetime.now()
    store = load()
    if not store["enabled"] or not store["apply_on_start"]:
        return None
    best = None
    for rule in store["rules"]:
        if not rule["enabled"]:
            continue
        when = last_fire(rule, now)
        if when and (best is None or when > best[0]):
            best = (when, rule)
    if not best:
        return None
    when, rule = best
    current = scenes.state()["program"]
    target = scenes.resolve_target(rule["action"])
    if current == target:
        return None                       # already correct, leave it alone
    apply_action(rule["action"],
                 f"restart reconcile - '{describe(rule)}' fired {when.strftime('%a %H:%M')}")
    return rule["action"]


# ---------------------------------------------------------------- describing

def describe(rule):
    if rule["type"] == "clock":
        when = rule["time"]
    else:
        off = rule["offset_minutes"]
        when = rule["event"]
        if off:
            when += f" {off:+d}min"
    days = ("every day" if sorted(rule["days"]) == ALL_DAYS
            else ",".join(DAY_NAMES[d] for d in rule["days"]))
    return f"{when} -> {rule['action']} ({days})"


def status(now=None):
    """Store plus computed next-fire times, for the WebUI."""
    now = now or datetime.datetime.now()
    store = load()
    state = scenes.state()
    rules = []
    for rule in store["rules"]:
        nxt = next_fire(rule, now) if rule["enabled"] else None
        target = scenes.resolve_target(rule["action"])
        rules.append({
            **rule,
            "action_name": ("Camera" if target == "live"
                            else state["scenes"].get(target, {}).get("name", rule["action"])),
            "action_valid": target == "live" or target in state["scenes"],
            "summary": describe(rule),
            "next_fire": nxt.isoformat(timespec="minutes") if nxt else None,
        })
    upcoming = [r for r in rules if r["next_fire"]]
    upcoming.sort(key=lambda r: r["next_fire"])
    return {
        "enabled": store["enabled"],
        "apply_on_start": store["apply_on_start"],
        "rules": rules,
        "next": upcoming[0] if upcoming else None,
        "sun_available": all(sun_times_for(now.date())),
    }


# ---------------------------------------------------------------- daemon

def daemon():
    log(f"scene scheduler running (tick {TICK_SECONDS}s)")
    try:
        reconcile()
    except Exception as e:
        log(f"reconcile failed: {e}")
    while True:
        try:
            tick()
        except Exception as e:            # a bad rule must never kill the loop
            log(f"tick error: {e}")
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "daemon":
        daemon()
    elif cmd == "tick":
        print(tick() or "nothing due")
    elif cmd == "reconcile":
        print(reconcile() or "already correct")
    elif cmd == "status":
        print(json.dumps(status(), indent=2))
    else:
        sys.exit(f"usage: {sys.argv[0]} [daemon|tick|reconcile|status]")
