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
# D32 census: other Amazon.com root categories, swept in rotation for supply only (no watching, no checks).
# Media (books, music, video, Kindle, apps) is left out, as in the feed rules. Keepa's response names each
# id, so a wrong id shows up in the census table instead of failing silently.
CENSUS_CATS = [165793011, 3760911, 3760901, 1064954, 165796011, 2619533011, 15684181, 2972638011, 7141123011,
               11091801, 16310091, 2617941011, 468642, 2335752011, 16310101, 10272111, 4991425011]

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
    new_near_miss_minutes: int = 60     # D30: a new 30-49% deal; settled listings use slow_minutes
    census_enabled: bool = False        # D32: switched on in preflight.toml [tracker]
    census_minutes: float = 2           # D32: one census page (5 tokens) per slot -> <= 2.5 tokens/min
    census_max_pages: int = 40          # per category pass; a pass stops early when a short page comes back
    census_cats: list[int] = field(default_factory=lambda: list(CENSUS_CATS))
    headline: float = 0.50              # D30: only new units at this strict discount get the fast cadence
    retry_minutes: int = 5              # D30: a failed check (0 tokens) is retried soon, doubling per failure

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


# ---------------------------------------------------------------- product signals (D28)

RATING, COUNT_REVIEWS = 16, 17  # csv indexes; only present when the request asks for history


def _last_csv(csv: list, i: int) -> int | None:
    a = csv[i] if len(csv) > i else None
    return a[-1] if a and a[-1] is not None and a[-1] >= 0 else None


def product_signals(p: dict) -> dict:
    """Demand signals from a product response, for the internal deal score (D28). Never shown to users
    (D19). A field Keepa didn't send is None, so an upsert can keep the earlier value: reviews and
    rating only come with history, i.e. on a watch's first check."""
    csv = p.get("csv") or []
    stats = p.get("stats") or {}
    cur = stats.get("current") or []
    pos = lambda v: v if isinstance(v, int) and v > 0 else None
    rating = _last_csv(csv, RATING)
    avail = p.get("availabilityAmazon")
    return {
        "brand": p.get("brand") or None,
        "cat_path": [c.get("name") for c in p.get("categoryTree") or []] or None,
        "reviews": _last_csv(csv, COUNT_REVIEWS),
        "rating": rating / 10 if rating else None,  # Keepa stores 45 for 4.5 stars
        "drops30": stats.get("salesRankDrops30") if (stats.get("salesRankDrops30") or -1) >= 0 else None,
        "drops90": stats.get("salesRankDrops90") if (stats.get("salesRankDrops90") or -1) >= 0 else None,
        "monthly_sold": pos(p.get("monthlySold")),
        "amazon_sells": None if avail is None else avail != -1,
        "rank": pos(cur[3]) if len(cur) > 3 else None,
    }


# ---------------------------------------------------------------- persistence

class Store(Protocol):
    def load(self) -> tuple[dict[str, Watch], dict[tuple[str, int], Unit], dict]: ...
    def put_state(self, key: str, value) -> None: ...
    def save_watch(self, w: Watch) -> None: ...
    def save_unit(self, u: Unit) -> None: ...
    def add_sweep_rows(self, t: float, rows: list[dict]) -> None: ...
    def add_check(self, t: float, check: dict, offers: list[dict]) -> None: ...
    def add_census_rows(self, t: float, cat_id: int, rows: list[dict]) -> None: ...
    def save_product(self, t: float, asin: str, signals: dict) -> None: ...


class MemoryStore:
    """In-process Store for tests and fixture rehearsals."""

    def __init__(self):
        self.watch: dict[str, Watch] = {}
        self.units: dict[tuple[str, int], Unit] = {}
        self.state: dict = {}
        self.sweep_rows: list[dict] = []
        self.checks: list[tuple[dict, list[dict]]] = []
        self.products: dict[str, dict] = {}
        self.census: list[dict] = []

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

    def add_census_rows(self, t, cat_id, rows):
        self.census += [{"t": t, "cat_id": cat_id, **r} for r in rows]

    def save_product(self, t, asin, signals):
        old = self.products.get(asin, {})
        self.products[asin] = {k: v if v is not None else old.get(k) for k, v in signals.items()}


# ---------------------------------------------------------------- the tracker

def sweep_query(cfg: TrackerConfig, page: int, cats: list[int] | None = None) -> dict:
    return {
        "page": page, "domainId": DOMAIN_US, "priceTypes": [9], "dateRange": 0,
        "isRangeEnabled": True, "deltaPercentRange": [cfg.sweep_min_delta, 100],
        "currentRange": [cfg.sweep_min_resale_cents, 100_000_00],
        "isFilterEnabled": True, "filterErotic": True, "singleVariation": False, "sortType": 1,
        "includeCategories": cats or TARGET_CATS,
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
        self.fail_streak: dict[str, int] = {}
        self.last_census: float = state.get("last_census", 0.0)
        self.census_next: int = state.get("census_next", 0)
        self.census_page: int = state.get("census_page", 0)
        self.census_pass_t: float = state.get("census_pass_t", 0.0)

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

    def census(self) -> int:
        """D32: fetch ONE page of the current census category (newest first) and record what's listed;
        nothing is watched or checked. A category's pass ends when a short page comes back or at
        census_max_pages; then the next category starts. One page per slot keeps the census at a steady
        <= 5 tokens per census_page_minutes and never blocks the checks for long."""
        t = self.clock()
        cats = self.cfg.census_cats
        cat = cats[self.census_next % len(cats)]
        if self.census_page == 0:
            self.census_pass_t = t  # every page of a pass is stamped with the pass start
        data = self.keepa.call("deal", label=f"census-{cat}-p{self.census_page}", estimate=DEAL_PAGE_COST,
                               body=sweep_query(self.cfg, self.census_page, [cat]))
        deals = data.get("deals") or {}
        names = dict(zip(deals.get("categoryIds") or [], deals.get("categoryNames") or []))
        dr = deals.get("dr") or []
        rows = [r for r in (self._census_row(d, names) for d in dr) if r]
        self.store.add_census_rows(self.census_pass_t, cat, rows)
        self.census_page += 1
        if len(dr) < DEAL_PAGE_SIZE or self.census_page >= self.cfg.census_max_pages:
            self.log(f"[{iso(t)}] census {cat} ({names.get(cat, '?')}): pass done, {self.census_page} pages")
            self.census_next, self.census_page = (self.census_next + 1) % len(cats), 0
        self.last_census = t
        for k, v in (("last_census", t), ("census_next", self.census_next), ("census_page", self.census_page),
                     ("census_pass_t", self.census_pass_t)):
            self.store.put_state(k, v)
        return 1

    def _census_row(self, d: dict, names: dict) -> dict | None:
        r = analysis.deal_row(d, names, 0, source="census")
        if not r:
            return None
        cur = d.get("current") or []
        rank = cur[3] if len(cur) > 3 and cur[3] > 0 else None
        return {"asin": r.asin, "parent": r.parent, "cat": r.root_cat, "title": r.title,
                "resale": r.warehouse_cents, "ref": r.strict_ref_cents, "strict": r.strict,
                "keepa_pct": r.keepa_reported, "cond": r.condition, "rank": rank,
                "creation": d.get("creationDate"), "qualifies": qualifies(r.strict, r.strict_ref_cents, rank, self.cfg),
                "formula": analysis.DISCOUNT_FORMULA_VERSION}

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
            # D30: the fast lane is for headline deals (or a watch not yet checked); new near misses go hourly
            hot = not units or any((u.strict_last or 0) >= self.cfg.headline for u in units)
            return (self.cfg.fast_minutes if hot else self.cfg.new_near_miss_minutes) * 60
        if any(u.state == "unconfirmed" for u in units):
            return self.cfg.unconfirmed_minutes * 60
        return self.cfg.slow_minutes * 60

    def next_check(self, t: float) -> str | None:
        """The next due watch, or None. D30 strict priority, because demand far exceeds the ~164
        checks/h budget and a plain most-overdue pick starves both of these: (0) retries of failed
        checks, (1) the fast lane (new headline deals), (2) everything else. Most overdue
        (overdue / its own interval) first within a class."""
        best, best_key = None, None
        for w in self.watch.values():
            if w.retired is not None:
                continue
            iv = self.interval(w, t)
            ratio = (t - w.last_check) / iv
            if ratio < 1.0:
                continue
            cls = 0 if w.asin in self.fail_streak else 1 if iv == self.cfg.fast_minutes * 60 else 2
            key = (cls, -ratio)
            if best_key is None or key < best_key:
                best, best_key = w.asin, key
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
            self._defer_retry(w, t)
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
        try:  # ranking signals are a nice-to-have; an odd product must never stop the tracker
            self.store.save_product(t, asin, product_signals(p))
        except Exception as e:  # noqa: BLE001
            self.log(f"  {asin}: product signals skipped ({e!r})")
        prev_check = w.last_check or None
        csv = p.get("csv") or []
        looks = [keepa_to_unix(x) for x, _ in decode_csv(csv[EXTRA_INFO_UPDATES] if len(csv) > EXTRA_INFO_UPDATES else None)] \
            if w.ok_checks == 0 and ok else []
        w.last_check = t
        if ok:  # a failed offer fetch says nothing about presence; its offers are Keepa's stale copy
            if any(qualifies(o["strict"], ref, w.rank, self.cfg) for o in offers):
                w.last_qualifying = t
            w.ok_checks += 1
            self.fail_streak.pop(asin, None)
            self._update_units(asin, offers, ref, t, prev_check, looks)
        else:
            self._defer_retry(w, t)
        self._maybe_retire(w, t)
        self.store.save_watch(w)

    def _defer_retry(self, w: Watch, t: float) -> None:
        """D30: a failed check cost nothing and told us nothing, so make the watch due again in
        retry_minutes (doubling per consecutive failure) instead of a full interval."""
        n = self.fail_streak.get(w.asin, 0)
        self.fail_streak[w.asin] = n + 1
        iv = self.interval(w, t)
        w.last_check = t - iv + min(self.cfg.retry_minutes * 60 * 2 ** n, iv)

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
        if self.cfg.census_enabled and self.cfg.census_cats and t - self.last_census >= self.cfg.census_minutes * 60:
            self.census()
            return "census"
        asin = self.next_check(t)
        if asin:
            self.check(asin)
            return "check"
        return "idle"
