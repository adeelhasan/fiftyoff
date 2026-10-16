"""Keyword alerts, rules k0.1 (docs/handoffs/alerts-beta.md; replaces the shelf rules n0.1 of 2026-10-08).

The tracker records unit events (new, revived) in `deal_event` for the units it checks live; this module decides,
deterministically (rule 7), whether an event is worth telling anyone, and whose keyword it matches. The match is
search's own (`search.matches` over the title and brand), so a keyword means what it means in the header search.

A match opens a send window for that alert (event time + the tier's delay); later matches for the same alert join
it. When the window closes, units that went or got unlisted are marked stale (My alerts lists them as missed) and
the rest go out as one email. A one-shot tier's alert then ends (`fired`); if everything was missed, it stays
armed. Each pass also ends alerts past their tier's lifetime (`expired`) and sends the expiry email.

Every number is a starting value to tune ([notify] and [tiers.*] in preflight.toml). Tiers are config only:
a name with perks. Billing doesn't exist yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Protocol

from . import mail
from .search import matches, words

RULES_VERSION = "k0.1"
ACCEPTABLE = "Used - Acceptable"
KEYWORD_MIN, KEYWORD_MAX = 2, 40
KEYWORD_CHARS = re.compile(r"[^a-z0-9 &'.+\-]")


@dataclass
class NotifyConfig:
    min_strict: float = 0.50       # the site's headline: 50%+ ...
    min_ref_cents: int = 4000      # ... from a $40 reference
    fresh_hours: float = 6         # a "new" unit must be this fresh by Keepa's dating (a first check finds old ones too)
    min_appeal: int = 3            # skip what the rater scored below this (unrated products don't wait)
    repeat_hours: float = 72       # one message per product (parent ASIN) per subscriber in this window
    site: str = "https://beta.fiftyoff.app"
    poll_seconds: float = 60
    tiers: dict[str, dict] = field(default_factory=lambda: {
        "free": {"delay_minutes": 30, "max_interests": 1, "one_shot": True, "lifetime_days": 30}})

    @classmethod
    def from_toml(cls, t: dict) -> "NotifyConfig":
        c = cls()
        for k, v in (t.get("notify") or {}).items():
            if hasattr(c, k):
                setattr(c, k, v)
        if t.get("tiers"):
            c.tiers = dict(t["tiers"])
        return c


def perks(cfg: NotifyConfig, tier: str) -> dict:
    """A tier's perks; an unknown tier gets the free tier's."""
    base = {"delay_minutes": 0, "max_interests": 1, "one_shot": False, "lifetime_days": 0}
    return {**base, **cfg.tiers.get("free", {}), **cfg.tiers.get(tier, {})}


def keyword(raw: str | None) -> str | None:
    """A keyword as stored: lower-cased, trimmed, spaces collapsed, odd characters dropped, 2-40 characters with at
    least one letter or digit. None if it doesn't qualify."""
    k = " ".join(KEYWORD_CHARS.sub(" ", (raw or "").lower()).split())
    return k if KEYWORD_MIN <= len(k) <= KEYWORD_MAX and re.search(r"[a-z0-9]", k) else None


def hits(kw: str, ev: dict) -> bool:
    return matches(kw, words(ev.get("title"), ev.get("brand")))


def product_key(ev: dict) -> str:
    return ev.get("parent_asin") or ev["asin"]


def _born(ev: dict) -> datetime | None:
    """When the deal became new, by Keepa's dating where we have it: the unit's first Keepa record, or the
    deal's current price (watch.created_at). Our own first sighting counts only if an earlier look didn't see it."""
    ts = [ev.get("keepa_first_seen_at"), ev.get("priced_at"),
          ev.get("first_seen_at") if ev.get("appeared_after_at") else None]
    ts = [t for t in ts if t]
    return max(ts) if ts else None


def decide(ev: dict, appeal: dict | None, now: datetime, cfg: NotifyConfig) -> tuple[str, dict]:
    """One event -> ("skip" | "ready", details). ev is the event joined to its unit, watch and product."""
    if ev.get("state") == "gone":
        return "skip", {"why": "gone"}
    if ev.get("unlisted"):
        return "skip", {"why": "unlisted"}
    if (ev.get("strict") or 0) < cfg.min_strict:
        return "skip", {"why": f"strict {ev.get('strict') or 0:.2f}"}
    if (ev.get("ref_cents") or 0) < cfg.min_ref_cents:
        return "skip", {"why": "reference"}
    if ev.get("cond") == ACCEPTABLE:
        return "skip", {"why": "acceptable"}
    if ev["kind"] == "new":
        born = _born(ev)
        if born is None or now - born > timedelta(hours=cfg.fresh_hours):
            return "skip", {"why": "not fresh"}
    if appeal is not None and appeal["score"] < cfg.min_appeal:
        return "skip", {"why": f"appeal {appeal['score']}"}
    return "ready", {"product_key": product_key(ev), "score": appeal["score"] if appeal else None}


def deliver_at(at: datetime, tier: str, cfg: NotifyConfig) -> datetime:
    return at + timedelta(minutes=perks(cfg, tier)["delay_minutes"])


# ---------------------------------------------------------------- one pass

class NotifyStore(Protocol):
    def open_events(self) -> list[dict]: ...
    def appeal(self, keys: list[str]) -> dict[str, dict]: ...
    def set_event(self, event_id: int, status: str, details: dict) -> None: ...
    def audience(self) -> list[dict]: ...  # subscriber_id, tier, endpoint_id, interest_id, keyword, armed_at
    def windows(self) -> dict[int, datetime]: ...  # interest_id -> deliver_at of its queued deliveries
    def recent(self, since: datetime) -> set[tuple[int, str]]: ...  # (subscriber_id, product_key) already told
    def add_deliveries(self, rows: list[dict]) -> None: ...
    def due(self, now: datetime) -> list[dict]: ...
    def mark(self, delivery_ids: list[int], status: str, error: str | None = None) -> None: ...
    def end_interest(self, interest_id: int, state: str, now: datetime) -> None: ...
    def endpoint_result(self, endpoint_id: int, ok: bool) -> None: ...
    def armed_before(self, t: datetime) -> list[dict]: ...  # watching alerts armed before t (expiry candidates)


def advance(store: NotifyStore, now: datetime, cfg: NotifyConfig) -> dict[str, int]:
    """Decide open events and queue deliveries for the alerts they match."""
    events = store.open_events()
    if not events:
        return {}
    ratings = store.appeal(sorted({product_key(e) for e in events} | {e["asin"] for e in events}))
    audience = store.audience()
    windows = store.windows()
    told = store.recent(now - timedelta(hours=cfg.repeat_hours))
    counts: dict[str, int] = {}
    for ev in events:
        a = ratings.get(product_key(ev)) or ratings.get(ev["asin"])
        status, d = decide(ev, a, now, cfg)
        if status == "ready":
            rows, seen = [], set()
            for s in audience:
                key = (s["subscriber_id"], d["product_key"])
                if s["armed_at"] is None or s["armed_at"] > ev["at"] or key in told or key in seen \
                        or not hits(s["keyword"], ev):
                    continue  # armed after the deal landed (no backfill), told already, or no match
                seen.add(key)
                at = windows.setdefault(s["interest_id"], deliver_at(ev["at"], s["tier"], cfg))
                rows.append({"event_id": ev["id"], "subscriber_id": s["subscriber_id"], "endpoint_id": s["endpoint_id"],
                             "interest_id": s["interest_id"], "product_key": d["product_key"], "deliver_at": at})
            told |= seen
            store.add_deliveries(rows)
            status = "queued" if rows else "no_watchers"
        store.set_event(ev["id"], status, {**d, "rules_v": RULES_VERSION})
        counts[status] = counts.get(status, 0) + 1
    return counts


def send_due(store: NotifyStore, send: mail.Sender, now: datetime, cfg: NotifyConfig, links: mail.Links,
             log: Callable[[str], None] = print) -> int:
    """Send what's due, one email per alert. A stopped or paused alert's deliveries are dropped; a unit that went
    or got unlisted since is stale (missed). One-shot alerts end once something is sent."""
    due = store.due(now)
    dropped = [d["id"] for d in due if d["interest_state"] != "watching" or d.get("paused")]
    stale = [d["id"] for d in due if d["id"] not in dropped and (d.get("state") == "gone" or d.get("unlisted"))]
    if dropped:
        store.mark(dropped, "dropped")
    if stale:
        store.mark(stale, "stale")
    by: dict[int, list[dict]] = {}
    for d in due:
        if d["id"] not in dropped and d["id"] not in stale:
            by.setdefault(d["interest_id"], []).append(d)
    sent = 0
    for iid, items in by.items():
        first = items[0]
        one_shot = perks(cfg, first["tier"])["one_shot"]
        m = mail.deals_mail(first["keyword"], items, links, first["subscriber_id"], iid, one_shot, now)
        try:
            send(first["address"], m)
        except Exception as e:  # noqa: BLE001 — one bad address must not stop the others
            store.mark([i["id"] for i in items], "failed", repr(e)[:300])
            store.endpoint_result(first["endpoint_id"], False)
            log(f"  send to endpoint {first['endpoint_id']} failed: {e!r}")
            continue
        store.mark([i["id"] for i in items], "sent")
        store.endpoint_result(first["endpoint_id"], True)
        if one_shot:
            store.end_interest(iid, "fired", now)
        sent += 1
    return sent


def expire(store: NotifyStore, send: mail.Sender, now: datetime, cfg: NotifyConfig, links: mail.Links,
           log: Callable[[str], None] = print) -> int:
    """End alerts past their tier's lifetime and send each the expiry email. An alert with a send window still
    open keeps going until the window closes."""
    lifetimes = [perks(cfg, t)["lifetime_days"] for t in {"free", *cfg.tiers}]
    shortest = min((x for x in lifetimes if x), default=0)
    if not shortest:
        return 0
    windows = store.windows()
    n = 0
    for r in store.armed_before(now - timedelta(days=shortest)):
        days = perks(cfg, r["tier"])["lifetime_days"]
        if not days or r["armed_at"] > now - timedelta(days=days) or r["interest_id"] in windows:
            continue
        store.end_interest(r["interest_id"], "expired", now)  # first, so a failing send can't repeat every pass
        n += 1
        if r.get("paused") or not r.get("address"):
            continue
        try:
            send(r["address"], mail.expired_mail(r["keyword"], links, r["subscriber_id"], r["interest_id"], days))
        except Exception as e:  # noqa: BLE001
            log(f"  expiry email for alert {r['interest_id']} failed: {e!r}")
    return n
