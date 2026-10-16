"""Keyword alerts on the site (docs/handoffs/alerts-beta.md): sign up, confirm, sign in, and My alerts.

Mounted in the site app (api_v1.create_site). No passwords: an email address is the account, proven by a signed
link (fiftyoff/tokens.py). The confirm link starts a 90-day session cookie on that browser; every alert email
carries a link that opens My alerts signed in. Every response here is `no-store`.

    POST /api/v1/watch {email, keyword, source}   pending alert + confirm email (same answer for any address)
    GET  /c/{token}                               confirm: arm the alert (or offer the swap), sign in, -> /watching/
    GET  /m/{token}                               sign-in or manage link: sign in, -> /my-alerts/
    GET  /u/{token}  POST /u/{token}              stop these emails (GET lands on My alerts, which does the POST)
    POST /api/v1/signin {email}                   a sign-in link to a known, verified address (same answer for any)
    GET  /api/v1/me                               who's signed in, their alerts and missed deals (401 if nobody)
    POST /api/v1/me/alerts {keyword, source}      add (409 + the current alert when the tier is full)
    POST /api/v1/me/alerts/{id} {action, keyword} edit | stop | undo | rearm | swap
    POST /api/v1/me/pause {paused}   POST /api/v1/me/stop-all   POST /api/v1/signout
    GET  /api/v1/alerts/config                    {open, delay_minutes, lifetime_days, max_free}

Rule 7: nothing here touches prices or availability; it only stores who wants which keyword.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import mail, notify, tokens

log = logging.getLogger("fiftyoff.alerts")

COOKIE = "fo_s"
SOURCES = {"search", "deal", "gone", "sold", "my-alerts"}
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]+\.[a-z]{2,}", re.I)
NO_STORE = {"Cache-Control": "no-store"}
PATHS = ("/api/v1/watch", "/api/v1/signin", "/api/v1/signout", "/api/v1/me", "/api/v1/alerts/", "/c/", "/m/", "/u/")


def no_store_path(path: str) -> bool:
    return path.startswith(PATHS)


class AlertStore(Protocol):
    def by_email(self, email: str) -> dict | None: ...
    def subscriber(self, sid: int) -> dict | None: ...
    def create(self, email: str) -> dict: ...
    def verify(self, sid: int, email: str) -> None: ...  # verified_at + the email endpoint
    def interests(self, sid: int) -> list[dict]: ...  # id, value, state, armed_at, ended_at, source, created_at
    def ask(self, sid: int, keyword: str, source: str | None) -> dict: ...  # pending unless already watching
    def put(self, sid: int, keyword: str, source: str | None, now: datetime) -> dict: ...  # watching, armed now
    def update(self, sid: int, iid: int, **fields) -> None: ...
    def set_paused(self, sid: int, paused: bool) -> None: ...
    def caught(self, sid: int, since: datetime) -> list[dict]: ...  # alert_delivery rows: missed (stale) and sent


class RateLimit:
    """At most `n` hits per key in `seconds`, in this process (one API container)."""

    def __init__(self, n: int, seconds: float, clock: Callable[[], float] = time.monotonic):
        self.n, self.seconds, self.clock = n, seconds, clock
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, q = self.clock(), self.hits[key]
        while q and q[0] <= now - self.seconds:
            q.popleft()
        if len(q) >= self.n:
            return False
        q.append(now)
        if len(self.hits) > 10000:  # forget idle keys now and then
            for k in [k for k, v in self.hits.items() if not v]:
                del self.hits[k]
        return True


@dataclass
class Alerts:
    store: AlertStore
    send: mail.Sender
    key: str
    site: str
    cfg: notify.NotifyConfig
    is_open: Callable[[], bool] = lambda: False
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    per_ip: RateLimit = field(default_factory=lambda: RateLimit(10, 3600))
    per_email: RateLimit = field(default_factory=lambda: RateLimit(3, 3600))

    @property
    def links(self) -> mail.Links:
        return mail.Links(self.site, self.key)

    def perks(self, sub: dict) -> dict:
        return notify.perks(self.cfg, sub["tier"])

    def view(self, sub: dict) -> dict:
        """What /api/v1/me returns: the subscriber, their alerts (newest first; ended ones of the last week, pending ones
        of the last day),
        and what alerts caught in the last 30 days (missed = the unit went before the send window closed)."""
        now, p = self.clock(), self.perks(sub)
        week = now - timedelta(days=7)
        alerts = []
        for i in sorted(self.store.interests(sub["id"]), key=lambda i: i["id"], reverse=True):
            if i["state"] == "pending" and i["created_at"] < now - timedelta(days=1):
                continue  # a recent pending alert is listed (the swap sheet names it); an old one never got confirmed
            if i["state"] not in ("watching", "pending") and (i["ended_at"] or i["created_at"]) < week:
                continue
            ends = i["armed_at"] + timedelta(days=p["lifetime_days"]) if p["lifetime_days"] and i["armed_at"] \
                and i["state"] == "watching" else None
            alerts.append({"id": i["id"], "keyword": i["value"], "state": i["state"], "armed_at": _iso(i["armed_at"]),
                           "ends_at": _iso(ends), "ended_at": _iso(i["ended_at"])})
        caught = [{"alert": c["interest_id"], "status": "missed" if c["status"] == "stale" else "sent",
                   "title": c["title"], "id": c["asin"], "at": _iso(c["at"])}
                  for c in self.store.caught(sub["id"], now - timedelta(days=30))]
        return {"email": sub["email"], "tier": sub["tier"], "paused": sub["paused"], "max": p["max_interests"],
                "delay_minutes": p["delay_minutes"], "one_shot": p["one_shot"], "lifetime_days": p["lifetime_days"],
                "alerts": alerts, "caught": caught}

    def room(self, sub: dict, but: int | None = None) -> bool:
        watching = [i for i in self.store.interests(sub["id"]) if i["state"] == "watching" and i["id"] != but]
        return len(watching) < self.perks(sub)["max_interests"]

    def watching(self, sub: dict) -> list[dict]:
        return [{"id": i["id"], "keyword": i["value"]} for i in self.store.interests(sub["id"]) if i["state"] == "watching"]


def _iso(t: datetime | None) -> str | None:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def _err(status: int, error: str, **extra) -> JSONResponse:
    return JSONResponse({"error": error, **extra}, status_code=status, headers=NO_STORE)


def _ok(body: dict | None = None, status: int = 200) -> JSONResponse:
    return JSONResponse(body or {"ok": True}, status_code=status, headers=NO_STORE)


def router(a: Alerts) -> tuple[APIRouter, APIRouter]:
    """(the /api/v1 routes, the short link routes /c/ /m/ /u/)."""
    v1, short = APIRouter(prefix="/api/v1"), APIRouter()

    def ip(request: Request) -> str:
        return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")

    def session(request: Request) -> dict | None:
        body = tokens.verify(a.key, request.cookies.get(COOKIE), "session")
        return a.store.subscriber(body["s"]) if body else None

    def sign_in(resp: Response, sid: int) -> Response:
        resp.set_cookie(COOKIE, tokens.sign(a.key, "session", sid), max_age=tokens.TTL["session"], httponly=True,
                        secure=a.site.startswith("https"), samesite="lax", path="/")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def go(path: str) -> RedirectResponse:
        return RedirectResponse(path, status_code=303, headers=NO_STORE)

    def mailer(address: str, m: mail.Mail) -> None:
        try:
            a.send(address, m)
        except Exception:  # noqa: BLE001 — the visitor already has their answer; the log has the failure
            log.exception("alert email to subscriber failed")

    async def body(request: Request) -> dict:
        try:
            b = await request.json()
            return b if isinstance(b, dict) else {}
        except ValueError:
            return {}

    @v1.get("/alerts/config")
    def config():
        p = notify.perks(a.cfg, "free")
        return _ok({"open": a.is_open(), "delay_minutes": p["delay_minutes"], "lifetime_days": p["lifetime_days"],
                    "max_free": p["max_interests"]})

    @v1.post("/watch")
    async def watch(request: Request, background: BackgroundTasks):
        b = await body(request)
        email, kw = str(b.get("email") or "").strip().lower(), notify.keyword(str(b.get("keyword") or ""))
        source = b.get("source") if b.get("source") in SOURCES else None
        if not EMAIL.fullmatch(email) or len(email) > 254:
            return _err(422, "email")
        if not kw:
            return _err(422, "keyword")
        if not a.per_ip.allow(ip(request)):
            return _err(429, "too many requests; try again in an hour")
        if a.per_email.allow(email):  # over the per-address limit: the same answer, no email
            sub = a.store.by_email(email) or a.store.create(email)
            i = a.store.ask(sub["id"], kw, source)
            background.add_task(mailer, email, mail.confirm_mail(kw, a.links, sub["id"], i["id"]))
        return _ok({"ok": True, "email": email, "keyword": kw}, 202)

    @v1.post("/signin")
    async def signin(request: Request, background: BackgroundTasks):
        email = str((await body(request)).get("email") or "").strip().lower()
        if not EMAIL.fullmatch(email) or len(email) > 254:
            return _err(422, "email")
        if not a.per_ip.allow(ip(request)):
            return _err(429, "too many requests; try again in an hour")
        sub = a.store.by_email(email) if a.per_email.allow(email) else None
        if sub and sub["verified_at"]:  # an unknown or unconfirmed address gets the same answer and no email
            background.add_task(mailer, email, mail.signin_mail(a.links, sub["id"]))
        return _ok({"ok": True, "email": email}, 202)

    @v1.post("/signout")
    def signout():
        r = _ok()
        r.delete_cookie(COOKIE, path="/")
        return r

    @v1.get("/me")
    def me(request: Request):
        sub = session(request)
        return _ok(a.view(sub)) if sub else _err(401, "signed out")

    @v1.post("/me/alerts")
    async def add(request: Request):
        sub = session(request)
        if not sub:
            return _err(401, "signed out")
        b = await body(request)
        kw = notify.keyword(str(b.get("keyword") or ""))
        if not kw:
            return _err(422, "keyword")
        same = next((i for i in a.store.interests(sub["id"]) if i["value"] == kw), None)
        if same and same["state"] == "watching":
            return _ok(a.view(sub))
        if not a.room(sub):
            return _err(409, "full", keyword=kw, current=a.watching(sub))
        a.store.put(sub["id"], kw, b.get("source") if b.get("source") in SOURCES else None, a.clock())
        return _ok(a.view(sub))

    @v1.post("/me/alerts/{iid}")
    async def change(iid: int, request: Request):
        sub = session(request)
        if not sub:
            return _err(401, "signed out")
        b = await body(request)
        action = b.get("action")
        mine = {i["id"]: i for i in a.store.interests(sub["id"])}
        i = mine.get(iid)
        if not i:
            return _err(404, "no such alert")
        now = a.clock()
        if action == "stop":
            if i["state"] in ("watching", "pending"):
                a.store.update(sub["id"], iid, state="stopped", ended_at=now)
        elif action == "undo":
            if i["state"] == "stopped":
                if not a.room(sub):
                    return _err(409, "full", keyword=i["value"], current=a.watching(sub))
                a.store.update(sub["id"], iid, state="watching", ended_at=None)
        elif action == "rearm":
            if i["state"] != "watching":
                if not a.room(sub):
                    return _err(409, "full", keyword=i["value"], current=a.watching(sub))
                a.store.update(sub["id"], iid, state="watching", armed_at=now, ended_at=None)
        elif action == "swap":  # this one in, the others out (as many as the tier needs)
            others = [x for x in mine.values() if x["state"] == "watching" and x["id"] != iid]
            keep = a.perks(sub)["max_interests"] - 1
            for x in sorted(others, key=lambda x: x["armed_at"] or now)[:max(0, len(others) - keep)]:
                a.store.update(sub["id"], x["id"], state="stopped", ended_at=now)
            a.store.update(sub["id"], iid, state="watching", armed_at=now, ended_at=None)
        elif action == "edit":
            kw = notify.keyword(str(b.get("keyword") or ""))
            if not kw:
                return _err(422, "keyword")
            other = next((x for x in mine.values() if x["value"] == kw and x["id"] != iid), None)
            if other:  # that keyword has a row already: it takes over, this one stops
                a.store.update(sub["id"], iid, state="stopped", ended_at=now)
                a.store.update(sub["id"], other["id"], state="watching", armed_at=now, ended_at=None)
            elif kw != i["value"] or i["state"] != "watching":
                if i["state"] != "watching" and not a.room(sub):
                    return _err(409, "full", keyword=kw, current=a.watching(sub))
                a.store.update(sub["id"], iid, value=kw, state="watching", armed_at=now, ended_at=None)
        else:
            return _err(422, "action: edit, stop, undo, rearm or swap")
        return _ok(a.view(sub))

    @v1.post("/me/pause")
    async def pause(request: Request):
        sub = session(request)
        if not sub:
            return _err(401, "signed out")
        a.store.set_paused(sub["id"], bool((await body(request)).get("paused")))
        return _ok(a.view(a.store.subscriber(sub["id"])))

    @v1.post("/me/stop-all")
    def stop_all(request: Request):
        sub = session(request)
        if not sub:
            return _err(401, "signed out")
        _stop_all(sub["id"])
        return _ok(a.view(sub))

    def _stop_all(sid: int) -> None:
        now = a.clock()
        for i in a.store.interests(sid):
            if i["state"] in ("watching", "pending"):
                a.store.update(sid, i["id"], state="stopped", ended_at=now)

    @short.get("/c/{token}")
    def confirm(token: str):
        t = tokens.verify(a.key, token, "confirm")
        sub = a.store.subscriber(t["s"]) if t else None
        if not sub:
            return go("/my-alerts/?link=expired")
        a.store.verify(sub["id"], sub["email"])
        i = next((x for x in a.store.interests(sub["id"]) if x["id"] == t.get("i")), None)
        if not i:
            return sign_in(go("/my-alerts/"), sub["id"])
        if i["state"] != "watching":
            if not a.room(sub):
                return sign_in(go(f"/my-alerts/?swap={i['id']}"), sub["id"])
            a.store.update(sub["id"], i["id"], state="watching", armed_at=a.clock(), ended_at=None)
        return sign_in(go(f"/watching/?q={quote(i['value'])}"), sub["id"])

    @short.get("/m/{token}")
    def manage(token: str, request: Request):
        t = tokens.verify(a.key, token, "manage") or tokens.verify(a.key, token, "signin")
        sub = a.store.subscriber(t["s"]) if t else None
        if not sub:
            return go("/my-alerts/?link=expired")
        rearm = request.query_params.get("rearm", "")
        return sign_in(go(f"/my-alerts/?rearm={rearm}" if rearm.isdigit() else "/my-alerts/"), sub["id"])

    @short.get("/u/{token}")
    def stop_page(token: str):
        t = tokens.verify(a.key, token, "stop")
        sub = a.store.subscriber(t["s"]) if t else None
        if not sub:
            return go("/my-alerts/?link=expired")
        return sign_in(go("/my-alerts/?stop=all"), sub["id"])  # the page asks the API to stop (link scanners don't)

    @short.post("/u/{token}")
    def stop_now(token: str):
        """RFC 8058 one-click unsubscribe from the mail app (List-Unsubscribe-Post)."""
        t = tokens.verify(a.key, token, "stop")
        sub = a.store.subscriber(t["s"]) if t else None
        if sub:
            _stop_all(sub["id"])
        return Response("Stopped. You won't get more alert emails.", media_type="text/plain", headers=NO_STORE)

    return v1, short


# ---------------------------------------------------------------- Postgres

class PgAlerts:
    """The API role (feed_reader, scripts/feed-reader.sh) reads and writes subscriber, endpoint and interest, and
    reads the alert_delivery view. One short connection per call, like the rest of the API."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn  # None: FEED_DATABASE_URL, read per call (the app is built at import, before any query)

    def _q(self, sql: str, args=(), one: bool = False):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(self.dsn or os.environ["FEED_DATABASE_URL"], row_factory=dict_row) as conn:
            cur = conn.execute(sql, args)
            if cur.description is None:
                return None
            return cur.fetchone() if one else cur.fetchall()

    def by_email(self, email):
        return self._q("SELECT * FROM subscriber WHERE email = %s", (email,), one=True)

    def subscriber(self, sid):
        return self._q("SELECT * FROM subscriber WHERE id = %s", (sid,), one=True)

    def create(self, email):
        return self._q("INSERT INTO subscriber (email) VALUES (%s) ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email "
                       "RETURNING *", (email,), one=True)

    def verify(self, sid, email):
        self._q("UPDATE subscriber SET verified_at = coalesce(verified_at, now()) WHERE id = %s", (sid,))
        self._q("INSERT INTO endpoint (subscriber_id, kind, address) VALUES (%s, 'email', %s) ON CONFLICT (kind, address) "
                "DO UPDATE SET disabled_at = NULL, failures = 0", (sid, email))

    def interests(self, sid):
        return self._q("SELECT id, value, state, armed_at, ended_at, source, created_at FROM interest "
                       "WHERE subscriber_id = %s AND kind = 'keyword' ORDER BY id", (sid,))

    def ask(self, sid, keyword, source):
        return self._q("INSERT INTO interest (subscriber_id, kind, value, state, source) VALUES (%s, 'keyword', %s, 'pending', %s) "
                       "ON CONFLICT (subscriber_id, kind, value) DO UPDATE SET state = CASE WHEN interest.state = 'watching' "
                       "THEN 'watching' ELSE 'pending' END, source = coalesce(EXCLUDED.source, interest.source) RETURNING *",
                       (sid, keyword, source), one=True)

    def put(self, sid, keyword, source, now):
        return self._q("INSERT INTO interest (subscriber_id, kind, value, state, armed_at, source) "
                       "VALUES (%s, 'keyword', %s, 'watching', %s, %s) ON CONFLICT (subscriber_id, kind, value) DO UPDATE "
                       "SET state = 'watching', armed_at = EXCLUDED.armed_at, ended_at = NULL, "
                       "source = coalesce(EXCLUDED.source, interest.source) RETURNING *", (sid, keyword, now, source), one=True)

    def update(self, sid, iid, **fields):
        cols = [c for c in fields if c in ("value", "state", "armed_at", "ended_at")]
        self._q(f"UPDATE interest SET {', '.join(f'{c} = %s' for c in cols)} WHERE id = %s AND subscriber_id = %s",
                (*[fields[c] for c in cols], iid, sid))

    def set_paused(self, sid, paused):
        self._q("UPDATE subscriber SET paused = %s WHERE id = %s", (paused, sid))

    def caught(self, sid, since):
        return self._q("SELECT interest_id, status, at, asin, title FROM alert_delivery WHERE subscriber_id = %s AND at > %s "
                       "ORDER BY at DESC LIMIT 50", (sid, since))
