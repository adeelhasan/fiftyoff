"""Signed links for keyword alerts (docs/handoffs/alerts-beta.md): confirm, sign in, manage, stop, and the session.

A token is `payload.signature`, both base64url: the payload is JSON {p: purpose, s: subscriber id, i: interest id
(optional), e: expiry (unix seconds)}; the signature is HMAC-SHA256 over the payload with SECRET_KEY (.env).
Nothing secret is inside, only ids; whoever holds a token can do what its purpose allows until it expires.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

PURPOSES = {"confirm", "signin", "manage", "stop", "session"}
TTL = {"confirm": 24 * 3600, "signin": 24 * 3600, "manage": 30 * 86400, "stop": 365 * 86400, "session": 90 * 86400}


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sig(key: str, payload: str) -> str:
    return _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())


def sign(key: str, purpose: str, subscriber: int, interest: int | None = None, now: float | None = None,
         ttl: int | None = None) -> str:
    if purpose not in PURPOSES:
        raise ValueError(purpose)
    body = {"p": purpose, "s": subscriber, "e": int((now if now is not None else time.time()) + (ttl or TTL[purpose]))}
    if interest is not None:
        body["i"] = interest
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sig(key, payload)}"


def verify(key: str, token: str | None, purpose: str, now: float | None = None) -> dict | None:
    """The payload {p, s, i?, e} if the token is ours, for this purpose and unexpired; else None."""
    if not key or not token or token.count(".") != 1:
        return None
    payload, sig = token.split(".")
    if not hmac.compare_digest(_sig(key, payload), sig):
        return None
    try:
        body = json.loads(_unb64(payload))
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("p") != purpose or not isinstance(body.get("s"), int):
        return None
    if body.get("e", 0) < (now if now is not None else time.time()):
        return None
    return body
