#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube Live Data API client — shared by watchdog.py (auto-PUBLIC after
recovery) and admin_api.py (broadcast controls in the WebUI).

Previously this logic lived only inside watchdog.py; it is factored out here so
both consumers share one implementation of token refresh, error classification
and broadcast lookup.

All credentials come from the environment:
    YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN

Callers may pass on_error(kind, detail) to receive classified failures
('token_expired', 'invalid_credentials', 'insufficient_scope', 'api_error') so
the watchdog can raise its Discord alerts without this module knowing about
Discord.
"""

import os
import json
import time
import threading
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from urllib.parse import urlencode

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/youtube/v3"

PRIVACY_CHOICES = ("public", "unlisted", "private")


class YouTubeError(Exception):
    """Raised with a human-readable message and a machine-readable kind."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.message = message


class YouTubeClient:
    def __init__(self, client_id=None, client_secret=None, refresh_token=None, on_error=None):
        self.client_id = client_id if client_id is not None else os.getenv("YOUTUBE_CLIENT_ID", "")
        self.client_secret = client_secret if client_secret is not None else os.getenv("YOUTUBE_CLIENT_SECRET", "")
        self.refresh_token = refresh_token if refresh_token is not None else os.getenv("YOUTUBE_REFRESH_TOKEN", "")
        self.on_error = on_error
        self._token = None
        self._token_expires = 0.0
        self._lock = threading.Lock()

    # ---- plumbing ---------------------------------------------------------

    @property
    def configured(self):
        return all([self.client_id, self.client_secret, self.refresh_token])

    def _fail(self, kind, message):
        if self.on_error:
            try:
                self.on_error(kind, message)
            except Exception:
                pass
        raise YouTubeError(kind, message)

    @staticmethod
    def _classify(code, body):
        """Map an OAuth/API HTTP error onto a stable kind + readable message."""
        try:
            data = json.loads(body)
        except ValueError:
            data = {}
        desc = (data.get("error_description")
                or data.get("error", {}).get("message") if isinstance(data.get("error"), dict)
                else data.get("error"))
        desc = desc or body[:300]
        if code == 400 and ("invalid_grant" in body or "expired" in body.lower()):
            return "token_expired", ("The YouTube refresh token has expired or been revoked. "
                                     "Regenerate it and update YOUTUBE_REFRESH_TOKEN.")
        if "invalid_client" in body or code == 401:
            return "invalid_credentials", ("YouTube API credentials rejected. Check "
                                           "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET.")
        if code == 403 and ("insufficientPermissions" in body or "SCOPE" in body.upper()):
            return "insufficient_scope", ("The refresh token lacks the youtube scope. Regenerate it "
                                          "with https://www.googleapis.com/auth/youtube.")
        return "api_error", f"YouTube API error {code}: {desc}"

    def _request(self, url, data=None, method="GET", timeout=10):
        token = self.access_token()
        req = Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            kind, msg = self._classify(e.code, e.read().decode(errors="replace"))
            self._fail(kind, msg)
        except Exception as e:
            self._fail("api_error", f"YouTube API request failed: {e}")

    def access_token(self):
        """Cached access token; refreshed ~1 minute before it expires."""
        if not self.configured:
            self._fail("not_configured",
                       "YouTube API is not configured (set YOUTUBE_CLIENT_ID, "
                       "YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN).")
        with self._lock:
            if self._token and time.time() < self._token_expires:
                return self._token
            payload = urlencode({
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            }).encode()
            req = Request(TOKEN_URL, data=payload, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            try:
                with urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read().decode())
            except HTTPError as e:
                kind, msg = self._classify(e.code, e.read().decode(errors="replace"))
                self._fail(kind, msg)
            except Exception as e:
                self._fail("api_error", f"Could not reach the YouTube token endpoint: {e}")
            self._token = result.get("access_token")
            self._token_expires = time.time() + max(60, int(result.get("expires_in", 3600))) - 60
            if not self._token:
                self._fail("api_error", "Token endpoint returned no access_token")
            return self._token

    # ---- broadcasts -------------------------------------------------------

    def get_active_broadcast(self):
        """The broadcast currently on air, or the next upcoming one.

        Returns None when the channel has neither. Privacy can be changed on
        an upcoming broadcast too, which is why both are considered.
        """
        for status in ("active", "upcoming"):
            params = urlencode({"part": "id,status,snippet",
                                "broadcastStatus": status,
                                "broadcastType": "all"})
            result = self._request(f"{API_BASE}/liveBroadcasts?{params}")
            items = result.get("items") or []
            if items:
                b = items[0]
                return {
                    "id": b["id"],
                    "title": b.get("snippet", {}).get("title", ""),
                    "privacy": b.get("status", {}).get("privacyStatus", ""),
                    "lifecycle": b.get("status", {}).get("lifeCycleStatus", ""),
                    "state": status,
                    "watch_url": f"https://www.youtube.com/watch?v={b['id']}",
                }
        return None

    def set_privacy(self, broadcast_id, privacy):
        """Set a broadcast's visibility. Only the status part is sent, so
        snippet fields on a live broadcast are never disturbed."""
        if privacy not in PRIVACY_CHOICES:
            self._fail("bad_request", f"privacy must be one of {', '.join(PRIVACY_CHOICES)}")
        body = json.dumps({"id": broadcast_id, "status": {"privacyStatus": privacy}}).encode()
        result = self._request(f"{API_BASE}/liveBroadcasts?{urlencode({'part': 'status'})}",
                               data=body, method="PUT")
        return result.get("status", {}).get("privacyStatus")

    def get_viewers(self, video_id):
        """Concurrent viewers, or None when YouTube is not reporting them
        (it omits the field when the broadcast is not live)."""
        params = urlencode({"part": "liveStreamingDetails", "id": video_id})
        result = self._request(f"{API_BASE}/videos?{params}")
        items = result.get("items") or []
        if not items:
            return None
        details = items[0].get("liveStreamingDetails", {})
        viewers = details.get("concurrentViewers")
        try:
            return int(viewers) if viewers is not None else None
        except (TypeError, ValueError):
            return None


_default_client = None
_default_lock = threading.Lock()


def client(on_error=None):
    """Process-wide client so the access token is refreshed once, not per call."""
    global _default_client
    with _default_lock:
        if _default_client is None:
            _default_client = YouTubeClient(on_error=on_error)
        elif on_error is not None:
            _default_client.on_error = on_error
        return _default_client
