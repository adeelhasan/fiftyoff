"""Deterministic pre-flight analysis: census discounts, variation grouping, episode reconstruction.

Versioned so every result can be replayed from raw responses (CLAUDE.md rule 8).
Definitions of "usable" are pre-registered in docs/DECISIONS.md (D11) — change them there first.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from .keepa import (
    AMAZON,
    CONDITIONS,
    EXTRA_INFO_UPDATES,
    NEW,
    WAREHOUSE,
    decode_csv,
    decode_offer_csv,
)

DISCOUNT_FORMULA_VERSION = "d0.1"
EPISODE_ALGO_VERSION = "e0.1"

DEFAULT_THRESHOLDS = (0.30, 0.40, 0.50, 0.60)
CENSUS_BUCKETS = (0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70)
PRICE_BANDS = (4000, 10000, 25000, 50000)  # cents: $40 / $100 / $250 / $500

# PF16 lifespan bands, in minutes
LIFESPAN_BANDS = (
    ("<10 min", 0, 10),
    ("10–30 min", 10, 30),
    ("30–60 min", 30, 60),
    ("1–6 hr", 60, 360),
    ("6+ hr", 360, float("inf")),
)

# D11 pre-registered usability rules
RECURRENCE_MAX_MEDIAN_GAP_MIN = 24 * 60
RECURRENCE_MAX_P90_GAP_MIN = 72 * 60
RECURRENCE_MIN_REF_COVERAGE = 0.80
HIGH_CONF_MAX_UNCERTAINTY_MIN = 60
MEDIUM_CONF_MAX_UNCERTAINTY_MIN = 24 * 60


def _at(arr: list | None, i: int, default=None):
    if arr is None or i >= len(arr):
        return default
    return arr[i]


def discount(price: int | None, ref: int | None) -> float | None:
    if price is None or ref is None or price <= 0 or ref <= 0:
        return None
    return 1 - price / ref


# ---------------------------------------------------------------- census (deal objects)

@dataclass
class DealRow:
    asin: str
    parent: str
    title: str
    root_cat: str
    warehouse_cents: int
    condition: str
    condition_comment: str | None
    discounts: dict[str, float | None]
    strict_key: str | None
    strict: float | None
    strict_ref_cents: int | None
    keepa_reported: int | None  # Keepa's own deltaPercent for WAREHOUSE in the queried range
    keepa_ref_match: str | None  # which of our candidates Keepa's number matches (±2 pts)
    source: str = ""  # census query that produced the row


def deal_row(d: dict, cat_names: dict[int, str], date_range: int, source: str = "") -> DealRow | None:
    cur = d.get("current") or []
    avg = d.get("avg") or []
    wh = _at(cur, WAREHOUSE)
    if wh is None or wh <= 0:
        return None
    refs = {
        "amazon_now": _at(cur, AMAZON),
        "new_now": _at(cur, NEW),
        # Keepa's own WAREHOUSE deltaPercent is measured against this one (verified on live page 0).
        "new_avg48h": _at(_at(avg, 0), NEW),
        "amazon_avg30": _at(_at(avg, 2), AMAZON),
        "new_avg30": _at(_at(avg, 2), NEW),
        "amazon_avg90": _at(_at(avg, 3), AMAZON),
        "new_avg90": _at(_at(avg, 3), NEW),
    }
    discounts = {k: discount(wh, v) for k, v in refs.items()}
    avail = {k: v for k, v in discounts.items() if v is not None}
    strict_key = min(avail, key=avail.get) if avail else None
    reported = _at(_at(d.get("deltaPercent"), date_range), WAREHOUSE)
    match = None
    if reported is not None and avail:
        best = min(avail, key=lambda k: abs(avail[k] * 100 - reported))
        if abs(avail[best] * 100 - reported) <= 2:
            match = best
    return DealRow(
        asin=d["asin"],
        parent=d.get("parentAsin") or d["asin"],
        title=(d.get("title") or "")[:140],
        root_cat=cat_names.get(d.get("rootCat"), str(d.get("rootCat"))),
        warehouse_cents=wh,
        condition=CONDITIONS.get(d.get("warehouseCondition") or 0, str(d.get("warehouseCondition"))),
        condition_comment=d.get("warehouseConditionComment"),
        discounts=discounts,
        strict_key=strict_key,
        strict=avail.get(strict_key) if strict_key else None,
        strict_ref_cents=refs[strict_key] if strict_key else None,
        keepa_reported=reported,
        keepa_ref_match=match,
        source=source,
    )


def bucket_label(x: float | None, edges=CENSUS_BUCKETS) -> str:
    if x is None:
        return "no reference"
    below = [e for e in edges if x >= e]
    if not below:
        return f"<{int(edges[0] * 100)}%"
    return f"{int(max(below) * 100)}%+"


def price_band(cents: int | None) -> str:
    if not cents:
        return "unknown"
    above = [b for b in PRICE_BANDS if cents >= b]
    return f"${max(above) // 100}+" if above else f"<${PRICE_BANDS[0] // 100}"


def census_summary(rows: list[DealRow]) -> dict:
    parents = defaultdict(list)
    for r in rows:
        parents[r.parent].append(r)
    families = sorted(
        ((p, rs) for p, rs in parents.items() if len(rs) > 1), key=lambda x: -len(x[1])
    )
    reported50 = [r for r in rows if (r.keepa_reported or 0) >= 50]
    return {
        "asins": len(rows),
        "parents": len(parents),
        "strict_buckets": Counter(bucket_label(r.strict) for r in rows),
        "reported_buckets": Counter(
            bucket_label(None if r.keepa_reported is None else r.keepa_reported / 100) for r in rows
        ),
        "strict_ref_used": Counter(r.strict_key or "none" for r in rows),
        "keepa_ref_match": Counter(r.keepa_ref_match or "no match (±2 pts)" for r in rows),
        "conditions": Counter(r.condition for r in rows),
        "categories": Counter(r.root_cat for r in rows),
        "price_bands_50": Counter(price_band(r.strict_ref_cents) for r in rows if (r.strict or 0) >= 0.5),
        "reported50": len(reported50),
        "reported50_strict_below50": sum(1 for r in reported50 if (r.strict or 0) < 0.5),
        "families": [(p, [asdict(r) for r in rs]) for p, rs in families[:15]],
        "family_asins": sum(len(rs) for _, rs in families),
    }


# ---------------------------------------------------------------- history (product objects)

def value_at(series: list[tuple[int, int]], t: int) -> int | None:
    """Step-function lookup: the last recorded value at or before t."""
    v = None
    for ts, val in series:
        if ts > t:
            break
        v = val
    return v


def conservative_ref(amazon: list, new: list, t: int) -> int | None:
    """D6 applied historically: the lowest available current new price (strictest discount)."""
    vals = [v for v in (value_at(amazon, t), value_at(new, t)) if v is not None and v > 0]
    return min(vals) if vals else None


def band_for(minutes: float) -> str:
    for label, lo, hi in LIFESPAN_BANDS:
        if lo <= minutes < hi:
            return label
    return LIFESPAN_BANDS[-1][0]


@dataclass
class Episode:
    threshold: float
    start: int
    end: int | None  # None = still qualifying at the end of the data (right-censored)
    end_reason: str | None
    left_censored: bool  # already qualifying when the window opened
    best_discount: float
    start_uncertainty: int | None = None
    end_uncertainty: int | None = None
    lifespan_min: int | None = None
    lifespan_max: int | None = None
    lifespan_band: str | None = None
    confidence: str = "LOW"


def _prev_obs(obs: list[int], t: int, strictly_before: bool = True) -> int | None:
    prev = None
    for o in obs:
        if o < t or (not strictly_before and o <= t):
            prev = o
        else:
            break
    return prev


def reconstruct_episodes(
    price_series: list[tuple[int, int]],
    amazon: list,
    new: list,
    obs: list[int],
    window_start: int,
    threshold: float,
) -> list[Episode]:
    """Episodes = maximal runs where the price is >= threshold below the conservative reference.

    Change points come from the price and both reference series. Boundary uncertainty comes from
    Keepa's offer-observation times (csv EXTRA_INFO_UPDATES): a change first seen at time t
    happened somewhere after the previous observation.
    """
    times = sorted({window_start} | {t for s in (price_series, amazon, new) for t, _ in s if t >= window_start})
    episodes: list[Episode] = []
    cur: Episode | None = None
    prev_price = None
    for t in times:
        price = value_at(price_series, t)
        ref = conservative_ref(amazon, new, t)
        d = discount(price, ref)
        qualifies = d is not None and d >= threshold
        if qualifies and cur is None:
            cur = Episode(threshold, t, None, None, t == window_start, d)
        elif qualifies and cur is not None:
            cur.best_discount = max(cur.best_discount, d)
        elif not qualifies and cur is not None:
            cur.end = t
            if price is None or price <= 0:
                cur.end_reason = "offer_disappeared"
            elif prev_price is not None and price > prev_price:
                cur.end_reason = "price_rose"
            else:
                cur.end_reason = "reference_fell"
            episodes.append(cur)
            cur = None
        prev_price = price
    if cur is not None:
        episodes.append(cur)
    for e in episodes:
        _bound(e, obs)
    return episodes


def _bound(e: Episode, obs: list[int]) -> None:
    start_lo = None if e.left_censored else _prev_obs(obs, e.start)
    e.start_uncertainty = None if start_lo is None else e.start - start_lo
    if e.end is None:
        e.confidence = "OPEN"  # right-censored: still qualifying, no lifespan claim
        return
    end_lo = _prev_obs(obs, e.end)
    if end_lo is None or end_lo < e.start:
        end_lo = e.start
    e.end_uncertainty = e.end - end_lo
    if start_lo is None:
        e.confidence = "LOW"
        return
    e.lifespan_min = end_lo - e.start
    e.lifespan_max = e.end - start_lo
    lo_band, hi_band = band_for(e.lifespan_min), band_for(e.lifespan_max)
    e.lifespan_band = lo_band if lo_band == hi_band else None
    worst = max(e.start_uncertainty, e.end_uncertainty)
    if worst <= HIGH_CONF_MAX_UNCERTAINTY_MIN:
        e.confidence = "HIGH"
    elif worst <= MEDIUM_CONF_MAX_UNCERTAINTY_MIN:
        e.confidence = "MEDIUM"
    else:
        e.confidence = "LOW"


def gap_stats(obs: list[int]) -> dict:
    gaps = [b - a for a, b in zip(obs, obs[1:])]
    if not gaps:
        return {"n_obs": len(obs), "median_gap_min": None, "p90_gap_min": None, "max_gap_min": None}
    gaps_sorted = sorted(gaps)
    p90 = gaps_sorted[min(len(gaps_sorted) - 1, int(0.9 * len(gaps_sorted)))]
    return {
        "n_obs": len(obs),
        "median_gap_min": statistics.median(gaps),
        "p90_gap_min": p90,
        "max_gap_min": max(gaps),
    }


def ref_coverage(amazon: list, new: list, window_start: int, now: int) -> float:
    times = sorted({window_start, now} | {t for s in (amazon, new) for t, _ in s if window_start <= t <= now})
    covered = 0
    for a, b in zip(times, times[1:]):
        if conservative_ref(amazon, new, a) is not None:
            covered += b - a
    span = now - window_start
    return covered / span if span > 0 else 0.0


@dataclass
class ProductResult:
    asin: str
    title: str
    parent: str | None
    category: str
    current_discount: float | None
    aggregate_found: bool
    offers_found: int
    offers_with_condition: int
    offer_conditions: dict
    gaps: dict
    ref_coverage: float
    csv9_aligned_with_obs: float | None
    total_offer_count: int | None
    retrieved_offer_count: int | None
    live_warehouse_offer: bool
    saving_basis_new: int | None
    variations: int
    historical_variations: int
    aggregate_episodes: dict = field(default_factory=dict)  # threshold -> list[Episode]
    offer_episodes: dict = field(default_factory=dict)  # threshold -> count across warehouse offers
    offer_conditions_in_episodes: dict = field(default_factory=dict)
    recurrence_usable: bool = False
    recurrence_reasons: list = field(default_factory=list)
    lifespan_usable: bool = False
    confidence: str = "LOW"
    tokens: int | None = None


def analyze_product(p: dict, now: int, window_days: int, thresholds=DEFAULT_THRESHOLDS,
                    category: str = "?") -> ProductResult:
    csv = p.get("csv") or []
    window_start = now - window_days * 1440
    wh = decode_csv(_at(csv, WAREHOUSE))
    amazon = decode_csv(_at(csv, AMAZON))
    new = decode_csv(_at(csv, NEW))
    obs = sorted(t for t, _ in decode_csv(_at(csv, EXTRA_INFO_UPDATES)) if window_start <= t <= now)

    wh_in_window = [(t, v) for t, v in wh if t >= window_start]
    carried = value_at(wh, window_start)
    aggregate_found = any(v > 0 for _, v in wh_in_window) or (carried or 0) > 0
    obs_set = set(obs)
    aligned = (
        sum(1 for t, _ in wh_in_window if t in obs_set) / len(wh_in_window) if wh_in_window else None
    )

    offers = p.get("offers") or []
    live_idx = set(p.get("liveOffersOrder") or [])
    wh_offers = [(i, o) for i, o in enumerate(offers) if o.get("isWarehouseDeal")]
    conds = Counter(CONDITIONS.get(o.get("condition", 0), "?") for _, o in wh_offers)
    with_cond = sum(1 for _, o in wh_offers if 2 <= (o.get("condition") or 0) <= 5)
    saving_new = next(
        (o.get("savingBasis") for _, o in wh_offers if o.get("savingBasisType") == 4), None
    )
    stats = p.get("stats") or {}

    res = ProductResult(
        asin=p["asin"],
        title=(p.get("title") or "")[:100],
        parent=p.get("parentAsin"),
        category=category,
        current_discount=discount(value_at(wh, now), conservative_ref(amazon, new, now)),
        aggregate_found=aggregate_found,
        offers_found=len(wh_offers),
        offers_with_condition=with_cond,
        offer_conditions=dict(conds),
        gaps=gap_stats(obs),
        ref_coverage=ref_coverage(amazon, new, window_start, now),
        csv9_aligned_with_obs=aligned,
        total_offer_count=stats.get("totalOfferCount"),
        retrieved_offer_count=stats.get("retrievedOfferCount"),
        live_warehouse_offer=any(i in live_idx for i, _ in wh_offers),
        saving_basis_new=saving_new,
        variations=len(p.get("variations") or []),
        historical_variations=len(p.get("historicalVariations") or []),
    )

    for th in thresholds:
        res.aggregate_episodes[th] = reconstruct_episodes(wh, amazon, new, obs, window_start, th)
        n_offer_eps = 0
        ep_conds = Counter()
        for _, o in wh_offers:
            series = [(t, price) for t, price, _ship in decode_offer_csv(o.get("offerCSV"))]
            # An offer's history just stops when it vanishes; close it at the first
            # observation after lastSeen so it doesn't qualify forever.
            gone = next((t for t in obs if t > (o.get("lastSeen") or 0)), None)
            if series and gone is not None and gone > series[-1][0]:
                series.append((gone, -1))
            eps = reconstruct_episodes(series, amazon, new, obs, window_start, th)
            n_offer_eps += len(eps)
            if eps:
                ep_conds[CONDITIONS.get(o.get("condition", 0), "?")] += len(eps)
        res.offer_episodes[th] = n_offer_eps
        res.offer_conditions_in_episodes[th] = dict(ep_conds)

    _apply_usability(res)
    return res


def _apply_usability(res: ProductResult) -> None:
    g = res.gaps
    reasons = []
    if not res.aggregate_found:
        reasons.append("no WAREHOUSE history in window")
    if res.ref_coverage < RECURRENCE_MIN_REF_COVERAGE:
        reasons.append(f"reference price available only {res.ref_coverage:.0%} of window")
    if g["median_gap_min"] is None:
        reasons.append("<2 offer observations in window")
    else:
        if g["median_gap_min"] > RECURRENCE_MAX_MEDIAN_GAP_MIN:
            reasons.append(f"median observation gap {g['median_gap_min'] / 60:.0f}h > 24h")
        if g["p90_gap_min"] > RECURRENCE_MAX_P90_GAP_MIN:
            reasons.append(f"p90 observation gap {g['p90_gap_min'] / 60:.0f}h > 72h")
    res.recurrence_usable = not reasons
    res.recurrence_reasons = reasons

    closed = [e for eps in res.aggregate_episodes.values() for e in eps if e.end is not None]
    usable = [e for e in closed if e.lifespan_band and e.confidence in ("HIGH", "MEDIUM")]
    res.lifespan_usable = bool(usable)
    if any(e.confidence == "HIGH" for e in usable) and res.recurrence_usable:
        res.confidence = "HIGH"
    elif usable or res.recurrence_usable:
        res.confidence = "MEDIUM"
    else:
        res.confidence = "LOW"


def suggest_decision(n_warehouse_deals: int, results: list[ProductResult]) -> tuple[str, str]:
    """D5, applied mechanically. The user makes the final call."""
    if n_warehouse_deals == 0:
        return "STOP / REASSESS", "the census found no Warehouse deals"
    if not results:
        return "INCOMPLETE", "no history sample analysed yet"
    n = len(results)
    rec = sum(r.recurrence_usable for r in results)
    life = sum(r.lifespan_usable for r in results)
    why = f"recurrence-usable {rec}/{n} ({rec / n:.0%}), lifespan-usable {life}/{n} ({life / n:.0%})"
    if rec / n >= 0.60 and life / n >= 0.40:
        return "GO", why
    if rec / n >= 0.60:
        return "PARTIAL GO", why
    return "STOP / REASSESS", why
