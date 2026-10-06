"""Cloudflare Access identity (D37). Access sits in front of preview.fiftyoff.app and adds a signed JWT
to every request it lets through (`Cf-Access-Jwt-Assertion`). We verify it ourselves: the signature
against the team's published keys, the audience (our application's AUD tag), the issuer and the expiry.
The email header Cloudflare also sends is never trusted on its own.

Roles live in `app_user` (viewer | admin). Emails in ADMIN_EMAILS are owners: always admin and active,
so nobody can lock the owner out from the People tab.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Callable

import jwt

HEADER = "cf-access-jwt-assertion"
REFETCH_SECONDS = 300  # an unknown key id triggers at most one key refresh per 5 min
RETRY_SECONDS = 15     # after a failed fetch, try again soon: no keys means nobody gets in


def certs_url(team: str) -> str:
    return f"https://{team}.cloudflareaccess.com/cdn-cgi/access/certs"


def fetch_certs(team: str) -> dict:
    with urllib.request.urlopen(certs_url(team), timeout=5) as r:  # noqa: S310 — fixed https URL
        return json.load(r)


class AccessVerifier:
    def __init__(self, team: str, aud: str, fetch: Callable[[str], dict] = fetch_certs,
                 clock: Callable[[], float] = time.time):
        self.team, self.aud, self.fetch, self.clock = team, aud, fetch, clock
        self.issuer = f"https://{team}.cloudflareaccess.com"
        self.keys: dict[str, jwt.PyJWK] = {}
        self.fetched_at = self.failed_at = float("-inf")

    def _key(self, kid: str | None) -> jwt.PyJWK | None:
        now = self.clock()
        if kid not in self.keys and now - self.fetched_at >= REFETCH_SECONDS and now - self.failed_at >= RETRY_SECONDS:
            try:
                self.keys = {k["kid"]: jwt.PyJWK(k) for k in self.fetch(self.team).get("keys", []) if k.get("kid")}
                self.fetched_at = now
            except Exception:  # noqa: BLE001 — keys unreachable: fail closed, keep the old keys, retry soon
                self.failed_at = now
        return self.keys.get(kid)

    def verify(self, token: str | None) -> str | None:
        """The verified, lower-cased email, or None for a missing, invalid or non-person token."""
        if not token:
            return None
        try:
            key = self._key(jwt.get_unverified_header(token).get("kid"))
            if key is None:
                return None
            claims = jwt.decode(token, key=key.key, algorithms=["RS256"], audience=self.aud, issuer=self.issuer,
                                options={"require": ["exp", "aud", "iss"]}, leeway=30)
        except jwt.PyJWTError:
            return None
        email = claims.get("email")  # service tokens carry no email: not a person, no access
        return email.strip().lower() if isinstance(email, str) and "@" in email else None


def owners(raw: str | None) -> frozenset[str]:
    return frozenset(e.strip().lower() for e in (raw or "").split(",") if e.strip())


ROLES = ("viewer", "admin")
NOTE_MAX = 500


def user_change(current: dict | None, change: dict, is_owner: bool) -> tuple[dict, list[tuple]]:
    """New app_user fields + log entries (field, old, new) for one People-tab change. A user can be set up
    before they first sign in (no current row). Owners (ADMIN_EMAILS) can't be demoted or deactivated
    from the page. Raises ValueError on a bad change."""
    cur = current or {"role": "admin" if is_owner else "viewer", "active": True, "note": None}
    unknown = set(change) - {"role", "active", "note"}
    if unknown or not change:
        raise ValueError(f"unknown or empty change: {sorted(unknown)}")
    new = {k: cur.get(k) for k in ("role", "active", "note")}
    if "role" in change:
        if change["role"] not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        new["role"] = change["role"]
    if "active" in change:
        if not isinstance(change["active"], bool):
            raise ValueError("active must be true or false")
        new["active"] = change["active"]
    if "note" in change:
        note = (change["note"] or "").strip() or None
        if note and len(note) > NOTE_MAX:
            raise ValueError("note too long")
        new["note"] = note
    if is_owner and (new["role"] != "admin" or not new["active"]):
        raise ValueError("an owner (ADMIN_EMAILS) is always an active admin; change ADMIN_EMAILS instead")
    base = current or {}  # a new person is logged from blank, so setting up a viewer still writes a row
    log = [(f, _s(base.get(f)), _s(new[f])) for f in ("role", "active", "note") if _s(base.get(f)) != _s(new[f])]
    return new, log


def _s(v) -> str | None:
    return None if v is None else str(v).lower() if isinstance(v, bool) else str(v)
