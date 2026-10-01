"""Track 1 (D16): Resale presence on popular products, whether or not they're discounted today.

Answers the extension question: when a shopper lands on a popular product page, how often is
there a Resale offer, how deep is it, and how often does it turn over?
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field

from .analysis import conservative_ref, discount, gap_stats, reconstruct_episodes, value_at
from .keepa import AMAZON, CONDITIONS, EXTRA_INFO_UPDATES, NEW, WAREHOUSE, decode_csv, decode_offer_csv

PRESENCE_ALGO_VERSION = "p0.1"


@dataclass
class Presence:
    asin: str
    title: str
    category: str
    rank: int | None
    normal_cents: int | None  # conservative New/Amazon reference now
    live_resale: bool
    live_discount: float | None  # cheapest live Resale offer vs reference now
    live_condition: str | None
    presence_share: float  # share of the window with any Resale price recorded
    median_discount: float | None  # time-weighted, while present
    max_discount: float | None
    time_at: dict = field(default_factory=dict)  # threshold -> share of window at >= threshold
    episodes: dict = field(default_factory=dict)  # threshold -> count of episodes starting in window
    units_seen: int = 0  # distinct Resale offers seen in the window
    units_gone: int = 0  # ... of which disappeared before the last observation (sold or pulled)
    conditions: dict = field(default_factory=dict)
    median_gap_min: float | None = None
    tokens: int | None = None


def _wmedian(pairs: list[tuple[float, int]]) -> float | None:
    pairs = sorted(p for p in pairs if p[1] > 0)
    total = sum(w for _, w in pairs)
    if not total:
        return None
    acc = 0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def resale_profile(p: dict, now: int, window_days: int, thresholds, category: str = "?") -> Presence:
    csv = p.get("csv") or []
    ws = now - window_days * 1440
    wh = decode_csv(csv[WAREHOUSE] if len(csv) > WAREHOUSE else None)
    amazon = decode_csv(csv[AMAZON] if csv else None)
    new = decode_csv(csv[NEW] if len(csv) > NEW else None)
    obs = sorted(t for t, _ in decode_csv(csv[EXTRA_INFO_UPDATES] if len(csv) > EXTRA_INFO_UPDATES else None)
                 if ws <= t <= now)

    times = sorted({ws, now} | {t for s in (wh, amazon, new) for t, _ in s if ws <= t <= now})
    present = 0
    weighted: list[tuple[float, int]] = []
    at = Counter()
    for a, b in zip(times, times[1:]):
        price = value_at(wh, a)
        if price is None or price <= 0:
            continue
        present += b - a
        d = discount(price, conservative_ref(amazon, new, a))
        if d is not None:
            weighted.append((d, b - a))
            for th in thresholds:
                if d >= th:
                    at[th] += b - a
    span = max(1, now - ws)

    offers = p.get("offers") or []
    live = set(p.get("liveOffersOrder") or [])
    ref_now = conservative_ref(amazon, new, now)
    wh_offers = [(i, o) for i, o in enumerate(offers) if o.get("isWarehouseDeal")]
    seen = [(i, o) for i, o in wh_offers
            if (o.get("lastSeen") or 0) >= ws or any(t >= ws for t, _, _ in decode_offer_csv(o.get("offerCSV")))]
    last_obs = obs[-1] if obs else now
    gone = [o for i, o in seen if i not in live and (o.get("lastSeen") or 0) < last_obs]
    live_wh = [o for i, o in wh_offers if i in live]
    cheapest = min(live_wh, key=lambda o: o["offerCSV"][-2] if o.get("offerCSV") else 1 << 30, default=None)

    stats = p.get("stats") or {}
    cur = stats.get("current") or []
    rank = cur[3] if len(cur) > 3 and cur[3] and cur[3] > 0 else None

    return Presence(
        asin=p["asin"],
        title=(p.get("title") or "")[:120],
        category=category,
        rank=rank,
        normal_cents=ref_now,
        live_resale=bool(live_wh),
        live_discount=discount(cheapest["offerCSV"][-2], ref_now) if cheapest and cheapest.get("offerCSV") else None,
        live_condition=CONDITIONS.get(cheapest.get("condition", 0)) if cheapest else None,
        presence_share=present / span,
        median_discount=_wmedian(weighted),
        max_discount=max((d for d, _ in weighted), default=None),
        time_at={th: at[th] / span for th in thresholds},
        episodes={th: sum(1 for e in reconstruct_episodes(wh, amazon, new, obs, ws, th) if not e.left_censored)
                  for th in thresholds},
        units_seen=len(seen),
        units_gone=len(gone),
        conditions=dict(Counter(CONDITIONS.get(o.get("condition", 0), "?") for _, o in seen)),
        median_gap_min=gap_stats(obs)["median_gap_min"],
    )


def summarize(rows: list[Presence], thresholds) -> dict:
    n = len(rows) or 1
    med = lambda xs: statistics.median(xs) if xs else None  # noqa: E731
    return {
        "n": len(rows),
        "live_now": sum(r.live_resale for r in rows) / n,
        "live_50_now": sum((r.live_discount or 0) >= 0.5 for r in rows) / n,
        "ever_present": sum(r.presence_share > 0 for r in rows) / n,
        "median_presence": med([r.presence_share for r in rows]),
        "median_discount": med([r.median_discount for r in rows if r.median_discount is not None]),
        "hit": {th: sum(r.episodes.get(th, 0) > 0 or r.time_at.get(th, 0) > 0 for r in rows) / n for th in thresholds},
        "episodes_per_product": {th: sum(r.episodes.get(th, 0) for r in rows) / n for th in thresholds},
        "units_seen_per_product": sum(r.units_seen for r in rows) / n,
        "units_gone_per_product": sum(r.units_gone for r in rows) / n,
        "conditions": sum((Counter(r.conditions) for r in rows), Counter()),
        "median_gap_min": med([r.median_gap_min for r in rows if r.median_gap_min is not None]),
    }
