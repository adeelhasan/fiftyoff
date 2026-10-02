"""New-deal tracker: Keepa sweeps find Resale deals; live checks time each unit (HANDOFF, D20).

Pure logic, with no I/O except through the injected Keepa client and Store, so tests can drive it
with scripted responses and a fake clock (CLAUDE.md rule 3).

Evidence behind the rules (2026-10-01, from the D17 48h run's raw data):
- The deal feed (sortType 1) is ordered by `creationDate`, which always equals currentSince[WAREHOUSE]:
  a new unit or a Resale price change floats to the top. Sweeps only page back to the previous sweep.
- A Resale offer can vanish from a successful check (offersSuccessful=true, not the offers cap, not the
  live flag) and return later with the same offerId: 107 times in 48h, gaps 6 min to 29 h, 92% within
  3 h. So absence is "unconfirmed", and a unit is "gone" only after GONE_AFTER of continuous absence.
- Sweep absence is never a miss: the feed is a rolling window. Only product checks confirm or deny a unit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

from . import analysis
from .keepa import (AMAZON, CONDITIONS, DEAL_PAGE_COST, DEAL_PAGE_SIZE, DOMAIN_US, EXTRA_INFO_UPDATES, NEW, Keepa,
                    KeepaError, decode_csv, keepa_to_unix, unix_to_keepa)

CHECK_FORMULA_VERSION = "d0.2"  # strict ref at a check: min of Amazon/New now, 1-day, 30-day, 90-day avg
UNIT_ALGO_VERSION = "u0.2"      # unit states + lifespan bounds + confidence, below (u0.2: Keepa-bracketed starts)

TARGET_CATS = [172282, 1055398, 2619525011, 228013, 3375251]  # Electronics, H&K, Appliances, Tools, Sports

HOUR = 3600
GONE_AFTER = 6 * HOUR         # continuous absence before a unit counts as gone (~98% of hides were shorter)
NEW_WINDOW = 6 * HOUR         # a deal or unit this young (by Keepa's own dating) gets the fast cadence
RETIRE_AFTER_GONE = 6 * HOUR  # all units gone and nothing qualifying for this long -> stop watching
RETIRE_NEVER_LIVE = 6 * HOUR  # the sweep said qualifying, but checks never found a Resale unit
RETIRE_STALE = 48 * HOUR      # nothing qualifying for this long -> stop watching even with units live


def iso(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(t, tz=timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- config + qualification

@dataclass
class TrackerConfig:
    sweep_minutes: int = 30
    full_sweep_hours: int = 12
    max_pages: int = 20
    full_sweep_max_pages: int = 100      # full sweeps must reach old listings whose reference rose
    sweep_min_delta: int = 30            # Keepa nominal floor; our strict tiers decide
    sweep_min_resale_cents: int = 2000
    tiers: list[tuple[float, int]] = field(default_factory=lambda: [(0.40, 10000), (0.30, 20000)])
    max_rank: int = 50000
    check_estimate: int = 7              # observed for 6,605 of 7,020 D17 checks; 13 is the 2-page worst case
    fast_minutes: int = 15
    unconfirmed_minutes: int = 30
    slow_minutes: int = 60

    @classmethod
    def from_toml(cls, t: dict) -> "TrackerConfig":
        c = cls()
        for k, v in t.items():
            if k == "tiers":
                v = [(float(a), int(b)) for a, b in v]
            if hasattr(c, k):
                setattr(c, k, v)
        return c


def qualifies(strict: float | None, ref_cents: int | None, rank: int | None, cfg: TrackerConfig) -> bool:
    if strict is None or ref_cents is None:
        return False
    if rank is not None and rank > cfg.max_rank:
        return False
    return any(strict >= d and ref_cents >= r for d, r in cfg.tiers)


def strict_ref_from_stats(stats: dict) -> tuple[int | None, dict]:
    """Strict reference at a live check (CHECK_FORMULA_VERSION). Keepa's stats lack the 48h average
    the deal feed has, so the 1-day average (stats=1 -> `avg`) stands in for it."""
    parts = {}
    for name, key in (("now", "current"), ("avg1d", "avg"), ("avg30", "avg30"), ("avg90", "avg90")):
        arr = stats.get(key) or []
        for src, i in (("amazon", AMAZON), ("new", NEW)):
            v = arr[i] if len(arr) > i else None
            if v is not None and v > 0:
                parts[f"{src}_{name}"] = v
    return (min(parts.values()) if parts else None), parts


# ---------------------------------------------------------------- state

@dataclass
class Watch:
    asin: str
    parent: str
    title: str
    cat: str
    rank: int | None
    image: str | None
    added: float
    created: float | None = None          # deal creationDate (unix): when the current Resale price started
    last_check: float = 0.0
    ok_checks: int = 0                    # successful offer fetches so far
    last_qualifying: float | None = None   # last sweep or check where this ASIN qualified
    retired: float | None = None


@dataclass
class Unit:
    asin: str
    offer_id: int
    first_seen: float              # our first check that saw it
    appeared_after: float | None   # last look without it: our previous check, or Keepa's last offer look
    last_seen: float
    first_price: int
    last_price: int
    cond: str
    comment: str | None
    strict_first: float | None
    strict_last: float | None
    ref_last: int | None
    keepa_first_seen: float | None = None  # when Keepa first recorded the offer (offerCSV[0]); first check only
    state: str = "live"            # live | unconfirmed | gone
    absent_since: float | None = None   # first successful check without it after last_seen
    gone_at: float | None = None
    revivals: int = 0
    checks_seen: int = 1


def lifespan(u: Unit) -> dict | None:
    """Bounds for a gone unit's lifespan, in minutes, with a rule-9 confidence label (UNIT_ALGO_VERSION).

    lower = last seen - first seen (Keepa's first record if earlier). upper = first absence - last look
    without it (our previous check, or on a watch's first check Keepa's last offer look before its first
    record). None when neither exists (left-censored: it may have been listed for days).
    HIGH: both ends bracketed within 60 min and absent 24h+. MEDIUM: within 24h and absent 6h+. Else LOW.
    """
    if u.state != "gone" or u.absent_since is None:
        return None
    start = min(u.first_seen, u.keepa_first_seen or u.first_seen)
    lower = (u.last_seen - start) / 60
    if u.appeared_after is None:
        return {"lower_min": lower, "upper_min": None, "confidence": "LOW", "algo": UNIT_ALGO_VERSION}
    upper = (u.absent_since - u.appeared_after) / 60
    slack = upper - lower
    absent = (u.gone_at or u.absent_since) - u.last_seen
    if slack <= 60 and absent >= 24 * HOUR:
        conf = "HIGH"
    elif slack <= 24 * 60 and absent >= GONE_AFTER:
        conf = "MEDIUM"
    else:
        conf = "LOW"
    return {"lower_min": lower, "upper_min": upper, "confidence": conf, "algo": UNIT_ALGO_VERSION}


# ---------------------------------------------------------------- persistence

class Store(Protocol):
    def load(self) -> tuple[dict[str, Watch], dict[tuple[str, int], Unit], dict]: ...
    def put_state(self, key: str, value) -> None: ...
    def save_watch(self, w: Watch) -> None: ...
    def save_unit(self, u: Unit) -> None: ...
    def add_sweep_rows(self, t: float, rows: list[dict]) -> None: ...
    def add_check(self, t: float, check: dict, offers: list[dict]) -> None: ...


class MemoryStore:
    """In-process Store for tests and fixture rehearsals."""

    def __init__(self):
        self.watch: dict[str, Watch] = {}
        self.units: dict[tuple[str, int], Unit] = {}
        self.state: dict = {}
        self.sweep_rows: list[dict] = []
        self.checks: list[tuple[dict, list[dict]]] = []

    def load(self):
        return dict(self.watch), dict(self.units), dict(self.state)

    def put_state(self, key, value):
        self.state[key] = value

    def save_watch(self, w):
        self.watch[w.asin] = w

    def save_unit(self, u):
        self.units[(u.asin, u.offer_id)] = u

    def add_sweep_rows(self, t, rows):
        self.sweep_rows += [{"t": t, **r} for r in rows]

    def add_check(self, t, check, offers):
        self.checks.append(({"t": t, **check}, offers))


# ---------------------------------------------------------------- the tracker

def sweep_query(cfg: TrackerConfig, page: int) -> dict:
    return {
        "page": page, "domainId": DOMAIN_US, "priceTypes": [9], "dateRange": 0,
        "isRangeEnabled": True, "deltaPercentRange": [cfg.sweep_min_delta, 100],
        "currentRange": [cfg.sweep_min_resale_cents, 100_000_00],
        "isFilterEnabled": True, "filterErotic": True, "singleVariation": False, "sortType": 1,
        "includeCategories": TARGET_CATS,
    }


class Tracker:
    def __init__(self, cfg: TrackerConfig, keepa: Keepa, store: Store,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = print):
        self.cfg, self.keepa, self.store = cfg, keepa, store
        self.clock, self.sleep, self.log = clock, sleep, log
        self.watch, self.units, state = store.load()
        self.last_sweep: float = state.get("last_sweep", 0.0)
        self.last_full_sweep: float = state.get("last_full_sweep", 0.0)

    # ---- sweeps

    def sweep(self) -> int:
        """Page the deal feed newest-first. Incremental sweeps stop once a page reaches deals created
        before the previous sweep (minus a 60 min margin); a full sweep runs to max_pages."""
        t = self.clock()
        full = t - self.last_full_sweep >= self.cfg.full_sweep_hours * HOUR
        cutoff = None if full or not self.last_sweep else unix_to_keepa(self.last_sweep - HOUR)
        n_rows = pages = 0
        for page in range(self.cfg.full_sweep_max_pages if full else self.cfg.max_pages):
            data = self.keepa.call("deal", label=f"sweep-p{page}", estimate=DEAL_PAGE_COST,
                                   body=sweep_query(self.cfg, page))
            pages += 1
            deals = data.get("deals") or {}
            names = dict(zip(deals.get("categoryIds") or [], deals.get("categoryNames") or []))
            dr = deals.get("dr") or []
            rows = [r for r in (self._sweep_row(d, names, t) for d in dr) if r]
            self.store.add_sweep_rows(t, rows)
            n_rows += len(rows)
            if len(dr) < DEAL_PAGE_SIZE:
                break
            if cutoff is not None and min(d.get("creationDate") or 0 for d in dr) < cutoff:
                break
        self.last_sweep = t
        self.store.put_state("last_sweep", t)
        if full:
            self.last_full_sweep = t
            self.store.put_state("last_full_sweep", t)
        self.log(f"[{iso(t)}] {'full' if full else 'incremental'} sweep: {pages} pages, {n_rows} rows, "
                 f"watching {self.active_count()}")
        return pages

    def _sweep_row(self, d: dict, names: dict, t: float) -> dict | None:
        r = analysis.deal_row(d, names, 0, source="tracker")
        if not r:
            return None
        cur = d.get("current") or []
        rank = cur[3] if len(cur) > 3 and cur[3] > 0 else None
        ok = qualifies(r.strict, r.strict_ref_cents, rank, self.cfg)
        if ok:
            self._watch(r, rank, d.get("image"), d.get("creationDate"), t)
        return {"asin": r.asin, "parent": r.parent, "cat": r.root_cat, "title": r.title,
                "resale": r.warehouse_cents, "ref": r.strict_ref_cents, "strict": r.strict,
                "keepa_pct": r.keepa_reported, "cond": r.condition, "comment": r.condition_comment,
                "rank": rank, "creation": d.get("creationDate"), "image": d.get("image"),
                "qualifies": ok, "formula": analysis.DISCOUNT_FORMULA_VERSION}

    def _watch(self, r, rank, image, creation, t) -> None:
        w = self.watch.get(r.asin)
        if w is None or w.retired is not None:
            w = Watch(asin=r.asin, parent=r.parent, title=r.title, cat=r.root_cat, rank=rank, image=image, added=t)
            self.watch[r.asin] = w
        w.rank, w.last_qualifying = rank, t
        if creation:
            w.created = keepa_to_unix(creation)
        self.store.save_watch(w)

    # ---- checks

    def interval(self, w: Watch, t: float) -> float:
        units = [u for u in self.units.values() if u.asin == w.asin and u.state != "gone"]
        # "New" by Keepa's dating, not ours: a fresh database's baseline sweep adds hundreds of old
        # listings at once, and they must not all claim the 15-minute cadence.
        born = [u.keepa_first_seen or u.first_seen for u in units if u.keepa_first_seen or u.appeared_after]
        if (w.created and t - w.created < NEW_WINDOW) or any(t - b < NEW_WINDOW for b in born):
            return self.cfg.fast_minutes * 60
        if any(u.state == "unconfirmed" for u in units):
            return self.cfg.unconfirmed_minutes * 60
        return self.cfg.slow_minutes * 60

    def next_check(self, t: float) -> str | None:
        """The most overdue active watch (overdue / its own interval), or None if nothing is due."""
        best, best_ratio = None, 1.0
        for w in self.watch.values():
            if w.retired is not None:
                continue
            ratio = (t - w.last_check) / self.interval(w, t)
            if ratio >= best_ratio:
                best, best_ratio = w.asin, ratio
        return best

    def check(self, asin: str) -> None:
        t = self.clock()
        w = self.watch[asin]
        first = w.ok_checks == 0  # first look: also fetch 90 days of history (no extra tokens) to date units already there
        try:
            data = self.keepa.call("product", label=f"check-{asin}", estimate=self.cfg.check_estimate, params={
                "domain": DOMAIN_US, "asin": asin, "offers": 20, "update": 0, "only-live-offers": 1,
                "history": 1 if first else 0, "days": 90, "stats": 1,
            })
        except KeepaError as e:
            self.log(f"  {asin}: {e}")
            w.last_check = t
            self.store.save_watch(w)
            return
        self.apply_check(asin, (data.get("products") or [{}])[0], t, data.get("tokensConsumed"))

    def apply_check(self, asin: str, p: dict, t: float, tokens: int | None = None) -> None:
        w = self.watch[asin]
        ok = bool(p.get("offersSuccessful"))
        ref, parts = strict_ref_from_stats(p.get("stats") or {})
        live = set(p.get("liveOffersOrder") or [])
        offers = []
        for i, o in enumerate(p.get("offers") or []):
            if not o.get("isWarehouseDeal") or i not in live or not o.get("offerCSV"):
                continue
            price = o["offerCSV"][-2]
            if price is None or price <= 0:
                continue
            offers.append({"offer_id": o.get("offerId"), "price": price, "keepa_first": o["offerCSV"][0],
                           "cond": CONDITIONS.get(o.get("condition", 0), str(o.get("condition"))),
                           "comment": o.get("conditionComment"), "strict": analysis.discount(price, ref)})
        best = max((o["strict"] for o in offers if o["strict"] is not None), default=None)
        self.store.add_check(t, {"asin": asin, "offers_ok": ok, "ref": ref, "ref_parts": parts, "best": best,
                                 "tokens": tokens, "formula": CHECK_FORMULA_VERSION}, offers)
        prev_check = w.last_check or None
        csv = p.get("csv") or []
        looks = [keepa_to_unix(x) for x, _ in decode_csv(csv[EXTRA_INFO_UPDATES] if len(csv) > EXTRA_INFO_UPDATES else None)] \
            if w.ok_checks == 0 and ok else []
        w.last_check = t
        if any(qualifies(o["strict"], ref, w.rank, self.cfg) for o in offers):
            w.last_qualifying = t
        if ok:  # a failed offer fetch says nothing about presence
            w.ok_checks += 1
            self._update_units(asin, offers, ref, t, prev_check, looks)
        self._maybe_retire(w, t)
        self.store.save_watch(w)

    def _update_units(self, asin, offers, ref, t, prev_check, looks=()) -> None:
        present = {o["offer_id"]: o for o in offers}
        for oid, o in present.items():
            u = self.units.get((asin, oid))
            if u is None:
                after, kfirst = prev_check, None
                if after is None and looks:  # first check: bracket the start with Keepa's own offer looks
                    kfirst = keepa_to_unix(o["keepa_first"])
                    before = [x for x in looks if x < kfirst]
                    after = max(before) if before else None
                u = Unit(asin=asin, offer_id=oid, first_seen=t, appeared_after=after, last_seen=t,
                         first_price=o["price"], last_price=o["price"], cond=o["cond"], comment=o["comment"],
                         strict_first=o["strict"], strict_last=o["strict"], ref_last=ref, keepa_first_seen=kfirst)
                self.units[(asin, oid)] = u
            else:
                if u.state == "gone":
                    u.revivals += 1
                    u.gone_at = None
                    self.log(f"  {asin}/{oid} revived after {(t - u.last_seen) / HOUR:.1f} h")
                u.state, u.absent_since = "live", None
                u.last_seen, u.last_price, u.strict_last, u.ref_last = t, o["price"], o["strict"], ref
                u.checks_seen += 1
            self.store.save_unit(u)
        for (a, oid), u in self.units.items():
            if a != asin or oid in present or u.state == "gone":
                continue
            if u.state == "live":
                u.state, u.absent_since = "unconfirmed", t
            if t - u.last_seen >= GONE_AFTER:
                u.state, u.gone_at = "gone", t
            self.store.save_unit(u)

    def _maybe_retire(self, w: Watch, t: float) -> None:
        units = [u for u in self.units.values() if u.asin == w.asin]
        open_units = [u for u in units if u.state != "gone"]
        quiet = t - (w.last_qualifying or w.added)
        if (not units and w.ok_checks >= 2 and t - w.added >= RETIRE_NEVER_LIVE) \
                or (units and not open_units and quiet >= RETIRE_AFTER_GONE) \
                or quiet >= RETIRE_STALE:
            w.retired = t

    # ---- loop

    def active_count(self) -> int:
        return sum(1 for w in self.watch.values() if w.retired is None)

    def step(self) -> str:
        """One unit of work: a sweep if due, else the most overdue check, else idle. Returns what it did."""
        t = self.clock()
        self.store.put_state("heartbeat", t)
        if t - self.last_sweep >= self.cfg.sweep_minutes * 60:
            self.sweep()
            return "sweep"
        asin = self.next_check(t)
        if asin:
            self.check(asin)
            return "check"
        return "idle"
