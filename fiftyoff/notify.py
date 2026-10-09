"""Notifications v1 (exploratory, 2026-10-08): who hears about a new deal, when, and what the message says.

The tracker records unit events (new, revived) in `deal_event`; this module decides, deterministically
(rule 7), whether an event is worth telling anyone, waits for the product's appeal rating (its shelf comes
from it), then queues one delivery per watcher at event time + their tier's delay. A pass sends what's due,
re-checking first that the deal is still live, and folds everything due for one address into one message.

Every number here is a starting value to tune ([notify] and [tiers.*] in preflight.toml), not a decision.
Tiers are config only: a tier is a name with perks (delay_minutes, max_interests). Billing doesn't exist yet.
Messages carry D19 fields only plus "Data by Keepa", and link to our site, never to Amazon (D23).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from typing import Callable, Protocol

from .shelving import UNSORTED, resolve_shelf

RULES_VERSION = "n0.1"
ACCEPTABLE = "Used - Acceptable"
ATTRIBUTION = "Data by Keepa (https://keepa.com)"


@dataclass
class NotifyConfig:
    min_strict: float = 0.50       # the shelves page headline: 50%+ ...
    min_ref_cents: int = 4000      # ... from a $40 reference
    fresh_hours: float = 6         # a "new" unit must be this fresh by Keepa's dating (a first check finds old ones too)
    min_appeal: int = 3            # skip what the rater scored below this
    rating_wait_minutes: float = 60  # an unrated product waits this long for the rater, then the event expires
    repeat_hours: float = 72       # one message per product (parent ASIN) per watcher in this window
    link_base: str = "https://preview.fiftyoff.app/closed-preview/shelves"
    poll_seconds: float = 60
    tiers: dict[str, dict] = field(default_factory=lambda: {"free": {"delay_minutes": 10, "max_interests": 1}})

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
    base = {"delay_minutes": 0, "max_interests": 1}
    return {**base, **cfg.tiers.get("free", {}), **cfg.tiers.get(tier, {})}


def product_key(ev: dict) -> str:
    return ev.get("parent_asin") or ev["asin"]


def _born(ev: dict) -> datetime | None:
    """When the deal became new, by Keepa's dating where we have it: the unit's first Keepa record, or the
    deal's current price (watch.created_at). Our own first sighting counts only if an earlier look didn't see it."""
    ts = [ev.get("keepa_first_seen_at"), ev.get("priced_at"),
          ev.get("first_seen_at") if ev.get("appeared_after_at") else None]
    ts = [t for t in ts if t]
    return max(ts) if ts else None


def decide(ev: dict, appeal: dict | None, kind_map: dict[str, str], shelves: dict[str, dict],
           now: datetime, cfg: NotifyConfig) -> tuple[str, dict]:
    """One event -> ("skip" | "wait" | "expire" | "ready", details). ev is the event joined to its unit and watch."""
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
    if appeal is None:
        if now - ev["at"] < timedelta(minutes=cfg.rating_wait_minutes):
            return "wait", {}
        return "expire", {"why": "no rating"}
    if appeal["score"] < cfg.min_appeal:
        return "skip", {"why": f"appeal {appeal['score']}"}
    sid = resolve_shelf(appeal, kind_map, shelves)
    if sid == UNSORTED:
        return "skip", {"why": "no shelf"}
    return "ready", {"product_key": product_key(ev), "shelf": sid, "aisle": shelves[sid]["aisle"],
                     "score": appeal["score"], "role": shelves[sid].get("role")}


def watches(interests: list[tuple[str, str]], shelf: str, aisle: str, role: str | None) -> bool:
    """A shelf interest always matches its shelf; an aisle interest covers the aisle's front and aisle shelves."""
    return ("shelf", shelf) in interests or (("aisle", aisle) in interests and role != "hidden")


def deliver_at(at: datetime, tier: str, cfg: NotifyConfig) -> datetime:
    return at + timedelta(minutes=perks(cfg, tier)["delay_minutes"])


def link(item: dict, cfg: NotifyConfig) -> str:
    return f"{cfg.link_base}?shelf={item['shelf']}"


def render(items: list[dict], cfg: NotifyConfig) -> tuple[str, str, str]:
    """(subject, text, html) for one address. items: title, strict, cond, resale_cents, shelf, shelf_name.
    D19 fields only, our link, never Amazon's."""
    items = sorted(items, key=lambda i: -(i["strict"] or 0))
    one = items[0]
    if len(items) == 1:
        subject = f"{round(one['strict'] * 100)}% off: {one['title'][:70]}"
    else:
        subject = f"{len(items)} new deals on your shelves, up to {round(one['strict'] * 100)}% off"

    def line(i: dict) -> str:
        return (f"{round(i['strict'] * 100)}% off · ${i['resale_cents'] / 100:,.2f} · {i['cond'] or 'Resale'}"
                f" · {i['shelf_name']}")

    text = "\n\n".join(f"{i['title']}\n{line(i)}\n{link(i, cfg)}" for i in items)
    text += f"\n\n--\nfiftyoff test alert ({RULES_VERSION}). {ATTRIBUTION}\n"
    html = "".join(f'<p><a href="{escape(link(i, cfg))}">{escape(i["title"])}</a><br>{escape(line(i))}</p>'
                   for i in items)
    html += (f'<p style="color:#777;font-size:12px">fiftyoff test alert ({RULES_VERSION}). '
             f'<a href="https://keepa.com">Data by Keepa</a></p>')
    return subject, text, html


# ---------------------------------------------------------------- one pass

class NotifyStore(Protocol):
    def open_events(self) -> list[dict]: ...
    def appeal(self, keys: list[str]) -> dict[str, dict]: ...
    def shelves(self) -> dict[str, dict]: ...
    def kind_map(self) -> dict[str, str]: ...
    def set_event(self, event_id: int, status: str, details: dict) -> None: ...
    def audience(self) -> list[dict]: ...  # subscriber_id, tier, endpoint_id, interests [(kind, value)]
    def recent(self, since: datetime) -> set[tuple[int, str]]: ...  # (subscriber_id, product_key) already told
    def add_deliveries(self, rows: list[dict]) -> None: ...
    def due(self, now: datetime) -> list[dict]: ...
    def mark(self, delivery_ids: list[int], status: str, error: str | None = None) -> None: ...
    def endpoint_result(self, endpoint_id: int, ok: bool) -> None: ...


Sender = Callable[[dict, str, str, str], None]  # (endpoint, subject, text, html); raises on failure


def advance(store: NotifyStore, now: datetime, cfg: NotifyConfig) -> dict[str, int]:
    """Decide open events and queue deliveries for the ready ones."""
    events = store.open_events()
    if not events:
        return {}
    ratings = store.appeal(sorted({product_key(e) for e in events} | {e["asin"] for e in events}))
    shelves, kmap = store.shelves(), store.kind_map()
    audience = store.audience()
    told = store.recent(now - timedelta(hours=cfg.repeat_hours))
    counts: dict[str, int] = {}
    for ev in events:
        a = ratings.get(product_key(ev)) or ratings.get(ev["asin"])
        status, d = decide(ev, a, kmap, shelves, now, cfg)
        if status == "ready":
            rows = []
            for s in audience:
                if (s["subscriber_id"], d["product_key"]) in told \
                        or not watches(s["interests"], d["shelf"], d["aisle"], d["role"]):
                    continue
                rows.append({"event_id": ev["id"], "subscriber_id": s["subscriber_id"], "endpoint_id": s["endpoint_id"],
                             "product_key": d["product_key"], "deliver_at": deliver_at(ev["at"], s["tier"], cfg)})
            told |= {(r["subscriber_id"], d["product_key"]) for r in rows}
            store.add_deliveries(rows)
            status = "queued" if rows else "no_watchers"
        if status != "wait" or ev.get("status") != "waiting":
            store.set_event(ev["id"], "waiting" if status == "wait" else status, {**d, "rules_v": RULES_VERSION})
        counts[status] = counts.get(status, 0) + 1
    return counts


def send_due(store: NotifyStore, send: Sender, now: datetime, cfg: NotifyConfig, log: Callable[[str], None] = print) -> int:
    """Send what's due, one message per endpoint. A deal that went or got unlisted since is dropped (stale)."""
    due = store.due(now)
    stale = [d["id"] for d in due if d.get("state") == "gone" or d.get("unlisted")]
    if stale:
        store.mark(stale, "stale")
    by: dict[int, list[dict]] = {}
    for d in due:
        if d["id"] not in stale:
            by.setdefault(d["endpoint_id"], []).append(d)
    sent = 0
    for eid, items in by.items():
        subject, text, html = render(items, cfg)
        try:
            send(items[0], subject, text, html)
        except Exception as e:  # noqa: BLE001 — one bad address must not stop the others
            store.mark([i["id"] for i in items], "failed", repr(e)[:300])
            store.endpoint_result(eid, False)
            log(f"  send to endpoint {eid} failed: {e!r}")
            continue
        store.mark([i["id"] for i in items], "sent")
        store.endpoint_result(eid, True)
        sent += 1
    return sent
