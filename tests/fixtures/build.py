"""Synthetic Keepa responses shaped like the documented objects. Values are invented.

These prove parsing and reconstruction logic, NOT Keepa semantics — only a live run can do that.
Regenerate the JSON files with: uv run python -m tests.fixtures.build
"""

from __future__ import annotations

import json
from pathlib import Path

NOW = 7_950_000  # Keepa minutes (~2026-03); fixtures carry their own clock via "timestamp"
DAY = 1440
N_TYPES = 36
ENVELOPE = {"tokensLeft": 1180, "refillRate": 20, "refillIn": 30000, "tokenFlowReduction": 0.0,
            "processingTimeInMs": 5}


def _arr(**vals):
    a = [-1] * N_TYPES
    for k, v in vals.items():
        a[int(k[1:])] = v
    return a


def deal(asin, parent, root, wh, amazon, new, avg90_new, reported, cond=2, title="Item"):
    avg = [_arr(i0=amazon, i1=new) for _ in range(3)] + [_arr(i0=amazon, i1=avg90_new)]
    dp = [_arr(i9=reported) for _ in range(4)]
    return {
        "asin": asin, "parentAsin": parent, "title": title, "rootCat": root, "categories": [root],
        "current": _arr(i0=amazon, i1=new, i9=wh), "currentSince": _arr(), "deltaLast": _arr(),
        "delta": [_arr() for _ in range(4)], "deltaPercent": dp, "avg": avg,
        "lastUpdate": NOW - 30, "creationDate": NOW - 30, "lightningEnd": 0,
        "warehouseCondition": cond, "warehouseConditionComment": "Minor cosmetic damage",
    }


CATS = {1055398: "Home & Kitchen", 3375251: "Sports & Outdoors", 228013: "Tools & Home Improvement",
        172282: "Electronics", 165793011: "Toys & Games"}


def deal_page() -> dict:
    dr = [
        # Kitchen: strict 55% vs new_now; Keepa says 58% (vs amazon_now)
        deal("B0KITCHEN1", "P0KITCHEN", 1055398, 9000, 21500, 20000, 20000, 58, title="Espresso Machine"),
        # Kitchen variant of the same parent (variation inflation)
        deal("B0KITCHEN2", "P0KITCHEN", 1055398, 9100, 21500, 20000, 20000, 58, cond=3, title="Espresso Machine, Red"),
        # Fitness: Keepa says 52% but 90-day avg new is lower -> strict 40%
        deal("B0FITNESS1", None, 3375251, 15000, 31000, 30000, 25000, 52, title="Adjustable Dumbbells"),
        # Tools: 62% strict
        deal("B0TOOLS001", None, 228013, 7600, 20000, 20000, 20000, 62, cond=3, title="Cordless Drill Kit"),
        # Electronics: Keepa 50%, no Amazon offer, strict vs new 33%
        deal("B0ELEC0001", None, 172282, 20000, -1, 30000, 30000, 50, cond=4, title="27in Monitor"),
        # Toys: outside cohorts
        deal("B0TOYS0001", None, 165793011, 2000, 5000, 5000, 5000, 60, title="Puzzle"),
        # Cheap kitchen item below the $40 reference floor
        deal("B0CHEAP001", None, 1055398, 1000, 3000, 3000, 3000, 66, title="Spatula"),
    ]
    ids = list(CATS)
    counts = [sum(1 for d in dr if d["rootCat"] == c) for c in ids]
    return {**ENVELOPE, "tokensConsumed": 5, "timestamp": (NOW + 21_564_000) * 60_000,
            "deals": {"dr": dr, "categoryIds": ids, "categoryNames": [CATS[c] for c in ids],
                      "categoryCount": counts}}


def product(asin="B0KITCHEN1") -> dict:
    """Hourly offer observations over 180 days, Amazon $215, New $200, and three Warehouse episodes."""
    start = NOW - 180 * DAY
    obs = list(range(start, NOW + 1, 60))
    extra = []
    for t in obs:
        extra += [t, 12]
    e1 = start + 80 * DAY          # 55% for 3h, then the offer disappears      -> band 1–6 hr, HIGH
    e2 = start + 130 * DAY         # 57.5% for one observation, then gone       -> spans bands
    e3 = NOW - 10 * DAY            # 53% for 8h, then price rises to $120       -> 6+ hr, price_rose
    wh = [start - DAY, -1, e1, 9000, e1 + 180, -1, e2, 8500, e2 + 60, -1, e3, 9400, e3 + 480, 12000]
    offers = [
        {"offerId": 0, "lastSeen": e3 + 480, "sellerId": "A2L77EE7U53NWQ", "isWarehouseDeal": True,
         "isAmazon": False, "condition": 2, "conditionComment": "Box damaged",
         "savingBasis": 20000, "savingBasisType": 4, "offerCSV": [e3, 9400, 0, e3 + 480, 12000, 0]},
        {"offerId": 1, "lastSeen": NOW, "sellerId": "ANEWSELLER", "isWarehouseDeal": False,
         "isAmazon": False, "condition": 1, "offerCSV": [start, 20000, 0]},
    ]
    csv = [None] * N_TYPES
    csv[0] = [start - 30 * DAY, 21500]
    csv[1] = [start - 30 * DAY, 20000]
    csv[9] = wh
    csv[15] = extra
    p = {"asin": asin, "title": "Espresso Machine", "parentAsin": "P0KITCHEN", "csv": csv,
         "offers": offers, "liveOffersOrder": [1], "variations": [{"asin": "B0KITCHEN2"}],
         "historicalVariations": ["B0OLDVAR01"],
         "stats": {"totalOfferCount": 2, "retrievedOfferCount": 2}}
    return {**ENVELOPE, "tokensConsumed": 7, "timestamp": (NOW + 21_564_000) * 60_000, "products": [p]}


def probe() -> dict:
    return {**ENVELOPE, "tokensConsumed": 0, "products": []}


def write(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "deal-p0.json").write_text(json.dumps(deal_page()))
    (directory / "probe.json").write_text(json.dumps(probe()))
    for asin in ("B0KITCHEN1", "B0FITNESS1", "B0TOOLS001", "B0ELEC0001", "B0TOYS0001"):
        (directory / f"product-{asin}.json").write_text(json.dumps(product(asin)))


if __name__ == "__main__":
    write(Path(__file__).parent / "keepa")
