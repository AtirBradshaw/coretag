"""Talking to the Coretag server. Standard library only."""

import json
import urllib.error
import urllib.request

from . import VERSION


class ServerError(Exception):
    pass


def _request(base, path, payload=None, timeout=30):
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json",
                 "User-Agent": f"coretag-agent/{VERSION}"},
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail", "")
        except Exception:
            detail = ""
        raise ServerError(f"the server refused ({e.code}) {detail}".strip())
    except urllib.error.URLError as e:
        raise ServerError(f"couldn't reach the server ({e.reason})")
    except Exception as e:
        raise ServerError(f"{type(e).__name__}: {e}")


def start_session(base):
    """One-time code for this run, so a saved upload can't be replayed later.
    Free hosting sleeps when idle, so the first request gets a long timeout."""
    return _request(base, "/api/v1/session", {}, timeout=90)["nonce"]


def check_claim(base, code):
    return _request(base, f"/api/v1/claim/{code}")


def submit(base, nonce, telemetry, claim_code=None, claim_mode=None):
    body = {"nonce": nonce, "telemetry": telemetry}
    if claim_code:
        body["claim_code"] = claim_code
        body["claim_mode"] = claim_mode or "arrival"
    return _request(base, "/api/v1/report", body, timeout=60)
