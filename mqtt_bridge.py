#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MQTT bridge - drive the program bus from Home Assistant, Node-RED or anything
else that speaks MQTT.

Publishes Home Assistant autodiscovery so the container appears by itself as a
device with an "Away" switch, a "Scene" selector and an "On Air" sensor. No YAML
to write on the Home Assistant side.

State is deliberately read from disk (scenes.py's program_state file) rather
than kept in memory: the WebUI, the API and this bridge are separate processes,
and polling one small file is far simpler - and harder to get wrong - than any
IPC between them. A take from the WebUI therefore shows up in Home Assistant
within a second, and vice versa.

Everything here is optional. With no MQTT_HOST set the bridge never starts, and
if paho-mqtt is missing it says so once and exits without touching the stream.
"""

import os
import re
import ssl
import warnings
import sys
import json
import time
import socket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenes  # noqa: E402

CONFIG_DIR = os.getenv("VANTAGECAM_CONFIG_DIR", "/config")

HOST = os.getenv("MQTT_HOST", "").strip()
PORT = int(os.getenv("MQTT_PORT", "1883") or 1883)
USERNAME = os.getenv("MQTT_USER", "").strip()
PASSWORD = os.getenv("MQTT_PASS", "")
PREFIX = (os.getenv("MQTT_PREFIX", "vantagecam").strip().strip("/") or "vantagecam")
DISCOVERY_PREFIX = (os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant").strip().strip("/")
                    or "homeassistant")
DISCOVERY_ENABLED = os.getenv("MQTT_DISCOVERY", "true").lower() != "false"
USE_TLS = os.getenv("MQTT_TLS", "false").lower() == "true"
DEVICE_NAME = os.getenv("MQTT_DEVICE_NAME", "").strip() or (
    os.getenv("WEATHER_LOCATION", "").strip() or "VantageCam") + " Live"
POLL_SECONDS = 1.0

# A stable per-install id so Home Assistant keeps the same device across restarts
NODE_ID = re.sub(r"[^a-z0-9_]", "_", (PREFIX + "_" + socket.gethostname()).lower())[:48]

T_AVAILABILITY = f"{PREFIX}/availability"
T_PROGRAM_STATE = f"{PREFIX}/program/state"
T_PROGRAM_SET = f"{PREFIX}/program/set"
T_SCENE_STATE = f"{PREFIX}/scene/state"
T_SCENE_SET = f"{PREFIX}/scene/set"
T_ONAIR_STATE = f"{PREFIX}/on_air/state"


def log(msg):
    print(f"[MQTT] {msg}", flush=True)


def configured():
    return bool(HOST)


# ---------------------------------------------------------------- discovery

def _device_block():
    return {
        "identifiers": [NODE_ID],
        "name": DEVICE_NAME,
        "manufacturer": "VantageCam",
        "model": "VantageCam Live",
    }


def discovery_messages(state):
    """(topic, payload) pairs describing the entities to Home Assistant."""
    scene_names = [s["name"] for s in state["scenes"].values()]
    away_name = state["scenes"].get(state["away_scene"], {}).get("name", "Away")
    avail = [{"topic": T_AVAILABILITY, "payload_available": "online",
              "payload_not_available": "offline"}]
    device = _device_block()

    switch = {
        "name": "Away",
        "unique_id": f"{NODE_ID}_away",
        "command_topic": T_PROGRAM_SET,
        "state_topic": T_PROGRAM_STATE,
        # program/state carries "live" or a scene id; anything but live is away
        "value_template": "{{ 'OFF' if value == 'live' else 'ON' }}",
        "payload_on": "away",
        "payload_off": "live",
        "state_on": "ON",
        "state_off": "OFF",
        "icon": "mdi:television-pause",
        "availability": avail,
        "device": device,
    }
    select = {
        "name": "Scene",
        "unique_id": f"{NODE_ID}_scene",
        "command_topic": T_SCENE_SET,
        "state_topic": T_SCENE_STATE,
        "options": ["Camera"] + sorted(scene_names),
        "icon": "mdi:playlist-play",
        "availability": avail,
        "device": device,
    }
    sensor = {
        "name": "On Air",
        "unique_id": f"{NODE_ID}_on_air",
        "state_topic": T_ONAIR_STATE,
        "icon": "mdi:broadcast",
        "availability": avail,
        "device": device,
    }
    return [
        (f"{DISCOVERY_PREFIX}/switch/{NODE_ID}/away/config", switch),
        (f"{DISCOVERY_PREFIX}/select/{NODE_ID}/scene/config", select),
        (f"{DISCOVERY_PREFIX}/sensor/{NODE_ID}/on_air/config", sensor),
    ]
    # Away switch semantics: ON takes the nominated away card to air, OFF returns
    # the camera. The scene select can pick any card (or Camera) directly.


# ---------------------------------------------------------------- commands

def scene_id_for_name(name, state):
    """Home Assistant selects by display name; map it back to a scene id."""
    name = (name or "").strip()
    if name.lower() in ("camera", "live"):
        return "live"
    for sid, scene in state["scenes"].items():
        if scene["name"].lower() == name.lower():
            return sid
    return name.lower()          # allow raw ids too


def apply_target(target, source):
    """Resolve and take a target to air. Returns the new state."""
    resolved = scenes.resolve_target(target)
    ok, msg, state = scenes.set_program(resolved)
    if ok:
        log(f"{source}: {msg}")
        try:
            import events
            events.record("program", f"On air: {state['program_name']} (MQTT)",
                          "info" if state["program"] == "live" else "warn")
        except Exception:
            pass
    else:
        log(f"{source}: ignored '{target}' - {msg}")
    return state


# ---------------------------------------------------------------- the bridge

class Bridge:
    def __init__(self):
        self.client = None
        self.connected = False
        self.last_published = None
        self.last_scene_sig = None

    # -- paho 1.x and 2.x differ in the constructor; support both ------------
    def _make_client(self):
        import paho.mqtt.client as mqtt
        client_id = f"{NODE_ID}_{int(time.time()) % 100000}"
        try:
            from paho.mqtt.enums import CallbackAPIVersion
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                client = mqtt.Client(CallbackAPIVersion.VERSION1, client_id=client_id)
        except (ImportError, AttributeError, TypeError):
            client = mqtt.Client(client_id=client_id)
        if USERNAME:
            client.username_pw_set(USERNAME, PASSWORD)
        if USE_TLS:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        client.will_set(T_AVAILABILITY, "offline", qos=1, retain=True)
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        def _on_disconnect(*_a):
            self.connected = False
            log("disconnected from broker - paho will reconnect")
        client.on_disconnect = _on_disconnect
        return client

    def on_connect(self, client, userdata, flags, rc, *args):
        if rc != 0:
            log(f"connection refused by broker (code {rc})")
            return
        log(f"connected to {HOST}:{PORT} as '{PREFIX}'")
        client.publish(T_AVAILABILITY, "online", qos=1, retain=True)
        client.subscribe([(T_PROGRAM_SET, 1), (T_SCENE_SET, 1)])
        self.last_scene_sig = None       # force discovery + state republish
        self.last_published = None
        self.connected = True

    def on_message(self, client, userdata, msg):
        payload = (msg.payload or b"").decode("utf-8", "replace").strip()
        if not payload:
            return
        state = scenes.state()
        if msg.topic == T_SCENE_SET:
            target = scene_id_for_name(payload, state)
        else:
            target = payload
        # Broker payloads are untrusted input: resolve_target/set_program only
        # ever accept 'live' or a known scene id, anything else is reported.
        self.publish_state(apply_target(target, f"{msg.topic} <- '{payload[:40]}'"),
                           force=True)

    # -- publishing ---------------------------------------------------------

    def publish_discovery(self, state):
        if not DISCOVERY_ENABLED:
            return
        for topic, payload in discovery_messages(state):
            self.client.publish(topic, json.dumps(payload), qos=1, retain=True)
        log(f"published Home Assistant discovery for '{DEVICE_NAME}' "
            f"({len(state['scenes'])} scenes)")

    def publish_state(self, state=None, force=False):
        state = state or scenes.state()
        sig = (state["program"], state["program_name"])
        if not force and sig == self.last_published:
            return
        self.client.publish(T_PROGRAM_STATE, state["program"], qos=1, retain=True)
        self.client.publish(T_SCENE_STATE,
                            "Camera" if state["program"] == "live" else state["program_name"],
                            qos=1, retain=True)
        self.client.publish(T_ONAIR_STATE,
                            "Camera" if state["program"] == "live" else state["program_name"],
                            qos=1, retain=True)
        self.last_published = sig

    def maybe_republish_discovery(self, state):
        """Re-announce when the scene library changes, so the select stays right."""
        sig = tuple(sorted((sid, s["name"]) for sid, s in state["scenes"].items()))
        if sig != self.last_scene_sig:
            self.last_scene_sig = sig
            self.publish_discovery(state)

    # -- main loop ----------------------------------------------------------

    def run(self):
        self.client = self._make_client()
        delay = 2
        while True:
            try:
                self.client.connect(HOST, PORT, keepalive=45)
                break
            except (OSError, socket.error) as e:
                log(f"cannot reach {HOST}:{PORT} ({e}) - retrying in {delay}s")
                time.sleep(delay)
                delay = min(delay * 2, 60)
        self.client.loop_start()
        for _ in range(100):                 # up to 10s for the CONNACK
            if self.connected:
                break
            time.sleep(0.1)
        try:
            while True:
                try:
                    if not self.connected:
                        time.sleep(POLL_SECONDS)
                        continue
                    state = scenes.state()
                    self.maybe_republish_discovery(state)
                    self.publish_state(state)
                except Exception as e:                  # never die on one bad poll
                    log(f"poll error: {e}")
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                self.client.publish(T_AVAILABILITY, "offline", qos=1, retain=True)
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass


def main():
    if not configured():
        log("MQTT_HOST not set - bridge disabled")
        return 0
    try:
        import paho.mqtt.client  # noqa: F401
    except ImportError:
        log("paho-mqtt is not installed - MQTT disabled (the stream is unaffected)")
        return 0
    scenes.init()
    log(f"topics: {T_PROGRAM_SET} (set) / {T_PROGRAM_STATE} (state) / "
        f"{T_SCENE_SET} (scene) / {T_AVAILABILITY} (availability)")
    Bridge().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
