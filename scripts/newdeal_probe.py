"""One-off probe: are there real 50%+ deals on NEW Amazon items, beyond Resale? (10-08, user)

Two Keepa /deal queries, each over the 90-day window and sorted by sales rank:
  amazon  priceType AMAZON (Amazon itself sells it), at least 50% under its own 90-day average
  new     priceType NEW (lowest new offer, any seller), at least 50% under its 90-day average
Keepa's deltaPercent is measured against that price's own history, so an inflated list price
can't make a deal on its own. On top of that we take a strict % off: the smallest discount
against the 30-day and 90-day averages, and against the cheapest other new offer right now.

Paid: up to PAGES pages per query x 5 tokens, under the pre-flight cap in preflight.toml.
Raw responses go to research/raw/newdeal/<run>/ before parsing; tokens go to the ledger.

  uv run scripts/newdeal_probe.py --dry-run      # zero cost: prints the plan
  uv run scripts/newdeal_probe.py                # live: probe balance, then [y/N]
  uv run scripts/newdeal_probe.py --from <dir>   # re-print a saved run, no calls
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fiftyoff.analysis import discount  # noqa: E402
from fiftyoff.keepa import (AMAZON, DEAL_PAGE_COST, DEAL_PAGE_SIZE, DOMAIN_US, NEW, WAREHOUSE, Keepa,  # noqa: E402
                            Ledger, LiveTransport, load_api_key)

import preflight  # noqa: E402

FORMULA_VERSION = "n0.2"  # strict % off = min vs own 7/30/90-day averages, the list price, other new offers now
                          # n0.1 used 30/90 only: placeholder spikes (e.g. a $5,034 "average" on $449 glasses) passed
PAGES = 2
MIN_PRICE_CENTS = 2000
RANGE_90D = 3
SORT_RANK = 3
LIST = 4  # csv index of the list price
RANK = 3  # csv index of the sales rank
QUERIES = {"amazon": AMAZON, "new": NEW}


def query(price_type: int, page: int) -> dict:
    return {
        "page": page, "domainId": DOMAIN_US, "priceTypes": [price_type], "dateRange": RANGE_90D,
        "isRangeEnabled": True, "deltaPercentRange": [50, 100],
        "currentRange": [MIN_PRICE_CENTS, preflight.PRICE_CEILING],
        "isFilterEnabled": True, "filterErotic": True, "singleVariation": True, "sortType": SORT_RANK,
        "excludeCategories": preflight.MEDIA_ROOTS,
    }


def at(arr, i):
    v = arr[i] if arr and i < len(arr) else None
    return v if v is not None and v > 0 else None


def row(d: dict, pt: int) -> dict | None:
    cur, avg = d.get("current") or [], d.get("avg") or []
    price = at(cur, pt)
    if price is None:
        return None
    refs = {"avg7": at(avg[1] if len(avg) > 1 else None, pt), "avg30": at(avg[2] if len(avg) > 2 else None, pt),
            "avg90": at(avg[3] if len(avg) > 3 else None, pt), "list": at(cur, LIST)}
    other = at(cur, NEW if pt == AMAZON else AMAZON)
    if other is not None and other != price:
        refs["other_now"] = other  # someone else sells it new right now
    offs = {k: discount(price, v) for k, v in refs.items() if v}
    offs = {k: v for k, v in offs.items() if v is not None}
    strict = min(offs.values()) if offs else None
    dp = d.get("deltaPercent") or []
    return {
        "asin": d["asin"], "title": (d.get("title") or "")[:70], "price": price, "strict": strict,
        "by": min(offs, key=offs.get) if offs else None, "keepa_pct": at(dp[RANGE_90D] if len(dp) > 3 else None, pt),
        "list": at(cur, LIST), "rank": at(cur, RANK), "resale": at(cur, WAREHOUSE),
        "drops30": d.get("salesRankDrops30"), "lightning": bool(d.get("lightningEnd")),
    }


def report(pages: dict[str, list[dict]], cat_names: dict) -> None:
    for name, pt in QUERIES.items():
        deals = pages.get(name) or []
        rows = [r for d in deals for r in [row(d, pt)] if r]
        total = pages.get(name + "_total")
        strict50 = [r for r in rows if r["strict"] is not None and r["strict"] >= 0.5]
        print(f"\n=== {name.upper()}  (Keepa total ≥50% vs 90-day avg, ≥$20: {total}; sampled {len(rows)} by sales rank)")
        print(f"  strict ≥50% ({FORMULA_VERSION}): {len(strict50)} of {len(rows)}"
              f"   ·  also has Resale: {sum(1 for r in rows if r['resale'])}"
              f"   ·  lightning: {sum(1 for r in rows if r['lightning'])}")
        why = {}
        for r in rows:
            if r not in strict50:
                why[r["by"] or "no ref"] = why.get(r["by"] or "no ref", 0) + 1
        if why:
            print("  failed strict, by the reference that broke it:", why)
        print(f"  {'strict':>6} {'keepa':>5} {'price':>8} {'resale':>8} {'rank':>8} {'d30':>4}  title")
        for r in sorted(strict50, key=lambda r: r["rank"] or 10**9)[:25]:
            res = f"${r['resale']/100:.2f}" if r["resale"] else "—"
            print(f"  {r['strict']*100:5.0f}% {r['keepa_pct'] or 0:4d}% ${r['price']/100:7.2f} {res:>8} "
                  f"{r['rank'] or 0:>8} {r['drops30'] or 0:>4}  {r['title']}")


def load_saved(run: Path) -> tuple[dict, dict]:
    pages: dict[str, list] = {}
    cats: dict = {}
    for f in sorted(run.glob("*.json")):
        name = f.stem.split("-")[1]
        if name not in QUERIES:
            continue
        r = json.loads(f.read_text())["response"]
        deals = r.get("deals") or {}
        pages.setdefault(name, []).extend(deals.get("dr") or [])
        if f.stem.endswith("p0"):
            pages[name + "_total"] = sum(deals.get("categoryCount") or [])
            cats.update(dict(zip(deals.get("categoryIds") or [], deals.get("categoryNames") or [])))
    return pages, cats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from", dest="saved")
    args = ap.parse_args()
    if args.saved:
        report(*load_saved(Path(args.saved)))
        return 0

    cap = tomllib.loads(Path("preflight.toml").read_text())["budget"]["token_cap"]
    ledger = Ledger(Path("research/token-ledger.jsonl"))
    n = len(QUERIES) * PAGES
    print(f"NEW-DEAL PROBE ({FORMULA_VERSION}) — Keepa /deal, amazon.com, ≥50% vs 90-day avg, ≥$20, no media")
    for name, pt in QUERIES.items():
        print(f"  {name:<7} priceType {pt}, {PAGES} page(s) by sales rank")
    print(f"  worst case: {n} pages = {n * DEAL_PAGE_COST} tokens (+1 balance probe)")
    print(f"  pre-flight budget: {ledger.spent()} spent of {cap} cap ({cap - ledger.spent()} left)")
    if args.dry_run:
        print("  --dry-run: no requests made.")
        return 0

    run = preflight.run_id()
    keepa = Keepa(LiveTransport(load_api_key()), ledger, Path("research/raw/newdeal") / run, cap)
    preflight.probe(keepa)
    if not preflight.confirm(f"Spend up to {n * DEAL_PAGE_COST} tokens on {n} deal pages?"):
        print("aborted.")
        return 1
    for name, pt in QUERIES.items():
        for page in range(PAGES):
            data = keepa.call("deal", label=f"{name}-p{page}", estimate=DEAL_PAGE_COST, body=query(pt, page))
            if len((data.get("deals") or {}).get("dr") or []) < DEAL_PAGE_SIZE:
                break
    print(f"  spent: see ledger; raw in research/raw/newdeal/{run}")
    report(*load_saved(Path("research/raw/newdeal") / run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
