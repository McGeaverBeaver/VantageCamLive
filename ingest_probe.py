#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ingest reachability probe.

FFmpeg reports every publishing failure as a generic "I/O error", which makes a
blocked port, a broken TLS path and a rejected stream key look identical in the
log. This probe separates them by walking the connection one layer at a time:

    DNS  ->  TCP  ->  TLS handshake (rtmps only)

and reporting exactly which layer failed. It deliberately does NOT send a stream
key or perform an RTMP handshake, so it is safe to run on every boot and cannot
disturb a live broadcast.

Usage:
    python3 ingest_probe.py [rtmps://a.rtmps.youtube.com/live2]   -> JSON
    python3 ingest_probe.py --text [url]                          -> log lines
"""

import os
import sys
import ssl
import json
import socket

DEFAULT_PORTS = {"rtmps": 443, "rtmp": 1935}


def parse_url(url):
    scheme, _, rest = url.partition("://")
    if not rest:
        rest, scheme = scheme, "rtmp"
    hostport = rest.split("/", 1)[0]
    if hostport.startswith("["):                     # IPv6 literal
        host, _, tail = hostport[1:].partition("]")
        port = int(tail[1:]) if tail.startswith(":") and tail[1:].isdigit() else None
    elif ":" in hostport:
        host, _, p = hostport.rpartition(":")
        port = int(p) if p.isdigit() else None
    else:
        host, port = hostport, None
    return scheme.lower(), host, port or DEFAULT_PORTS.get(scheme.lower(), 1935)


def probe(url, timeout=4.0, max_addresses=3):
    scheme, host, port = parse_url(url)
    result = {"url_scheme": scheme, "host": host, "port": port,
              "dns": None, "tcp": None, "tls": None, "addresses": [], "error": None,
              "verdict": "", "hint": ""}
    if not host:
        result["error"] = "could not parse a host out of the ingest URL"
        result["verdict"] = "misconfigured"
        return result

    # --- DNS ---------------------------------------------------------------
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        result["addresses"] = sorted({i[4][0] for i in infos})
        result["dns"] = True
    except socket.gaierror as e:
        result.update(dns=False, error=f"DNS lookup failed: {e}",
                      verdict="dns-failure",
                      hint="The container cannot resolve the ingest hostname. Check its DNS settings.")
        return result

    # --- TCP ---------------------------------------------------------------
    # A blocked port plus a host that resolves to a dozen addresses would
    # otherwise stall boot for a minute, so only a few candidates are tried.
    # IPv4 first: FFmpeg has no Happy-Eyeballs fallback, so if v6 is broken it
    # simply fails where Python/curl would have silently recovered.
    infos = sorted(infos, key=lambda i: 0 if i[0] == socket.AF_INET else 1)[:max_addresses]
    last_err = None
    sock = None
    for info in infos:
        family, socktype, proto, _, sockaddr = info
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            result["tcp"] = True
            result["connected_via"] = sockaddr[0]
            break
        except OSError as e:
            last_err = f"{sockaddr[0]}: {e}"
            try:
                sock.close()
            except OSError:
                pass
            sock = None
    if sock is None:
        result.update(tcp=False, error=f"TCP connect failed ({last_err})",
                      verdict="port-blocked",
                      hint=f"Nothing is reachable on {host}:{port}. A firewall, the Docker "
                           f"network, or the ISP is blocking outbound traffic to that port.")
        return result

    # --- TLS (rtmps only) --------------------------------------------------
    if scheme != "rtmps":
        sock.close()
        result.update(verdict="ok", hint="")
        return result

    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            result["tls"] = True
            result["tls_version"] = tls.version()
            result["tls_cipher"] = tls.cipher()[0] if tls.cipher() else None
        result.update(verdict="ok", hint="")
        return result
    except ssl.SSLError as e:
        result.update(tls=False, error=f"TLS handshake failed: {e}", verdict="tls-failure")
    except OSError as e:
        result.update(tls=False, error=f"TLS handshake failed: {e}", verdict="tls-failure")
    finally:
        try:
            sock.close()
        except OSError:
            pass

    # Retry without certificate verification to tell "untrusted certificate"
    # apart from "the TLS connection itself is being cut".
    try:
        raw = socket.create_connection((host, port), timeout=timeout)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with ctx.wrap_socket(raw, server_hostname=host) as tls:
            result["tls_without_verification"] = True
            result["tls_version"] = tls.version()
        result["verdict"] = "tls-trust-failure"
        result["hint"] = ("TLS only succeeds when certificate verification is disabled, so the "
                          "container's CA trust store is missing or stale. Add the "
                          "'ca-certificates' package / refresh it.")
    except Exception:
        result["tls_without_verification"] = False
        result["hint"] = ("The TLS connection is being cut even without certificate "
                          "verification. Something between this container and the ingest is "
                          "terminating TLS on that port (firewall / deep packet inspection / "
                          "transparent proxy). Try the plain RTMP ingest on port 1935 instead: "
                          "YOUTUBE_URL=rtmp://a.rtmp.youtube.com/live2")
    return result


def as_lines(r):
    """Human-readable log lines."""
    out = []
    target = f"{r['url_scheme']}://{r['host']}:{r['port']}"
    if r["verdict"] == "ok":
        detail = f" (TLS {r.get('tls_version')})" if r.get("tls") else ""
        out.append(f"Ingest check: {target} reachable{detail}")
        return out
    out.append(f"[ERROR] Ingest check FAILED for {target}")
    out.append(f"[ERROR]   DNS: {_mark(r['dns'])}   TCP: {_mark(r['tcp'])}   TLS: {_mark(r['tls'])}")
    if r.get("addresses"):
        out.append(f"[ERROR]   resolved to: {', '.join(r['addresses'])}")
    if r.get("error"):
        out.append(f"[ERROR]   {r['error']}")
    if r.get("hint"):
        out.append(f"[ERROR]   {r['hint']}")
    return out


def _mark(v):
    return "ok" if v is True else ("FAILED" if v is False else "-")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--text"]
    url = args[0] if args else os.getenv("YOUTUBE_URL", "rtmp://a.rtmp.youtube.com/live2")
    r = probe(url)
    if "--text" in sys.argv[1:]:
        for line in as_lines(r):
            print(line)
    else:
        print(json.dumps(r, indent=2))
    sys.exit(0 if r["verdict"] == "ok" else 1)
