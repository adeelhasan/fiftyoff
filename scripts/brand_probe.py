"""One-off probe: how many Resale deals do well-known brands have on Keepa? (10-13, user, categories planning)

One Keepa /deal query per brand: the tracker's sweep body (Resale, 1-day range, Keepa delta >= 30, >= $20,
all variations) with no category filter and `brand: [name]`. Our strict % off comes from analysis.deal_row,
the same formula the sweep and census use, so the counts at 50%+ and 30-49% (near misses) match the feed's.

Paid: up to PAGES pages per brand x 5 tokens, under the pre-flight cap in preflight.toml.
Raw responses go to research/raw/brand/<run>/ before parsing; tokens go to the ledger.
rows.tsv in the run folder lists every row, for diffing against the feed on the VPS.

  uv run scripts/brand_probe.py --dry-run      # zero cost: prints the plan
  uv run scripts/brand_probe.py                # live: probe balance, then [y/N]
  uv run scripts/brand_probe.py --from <dir>   # re-print a saved run, no calls
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fiftyoff import analysis  # noqa: E402
from fiftyoff.keepa import DEAL_PAGE_COST, DEAL_PAGE_SIZE, Keepa, Ledger, LiveTransport, load_api_key  # noqa: E402
from fiftyoff.tracker import TrackerConfig, sweep_query  # noqa: E402

import preflight  # noqa: E402

PAGES = 3
BRANDS = ["Dyson", "Philips", "Samsung", "KitchenAid", "Vitamix", "Pandora", "Swarovski",  # the user's picks
          "Michael Kors", "Fossil", "Jabra", "NETGEAR", "Thule", "iRobot", "GreenPan", "ASUS", "Callaway",  # in our feed
          "DELTA"]  # control: a faucet brand the sweep already covers well


def query(brand: str, page: int) -> dict:
    q = sweep_query(TrackerConfig(), page)
    del q["includeCategories"]
    return {**q, "brand": [brand]}


def slug(brand: str) -> str:
    return brand.lower().replace(" ", "_")


def load_saved(run: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(run.glob("*-p[0-9].json")):  # 002-dyson-p0.json; skips 001-probe.json
        brand_slug = f.stem.split("-", 1)[1].rsplit("-p", 1)[0]
        r = json.loads(f.read_text())["response"]
        deals = r.get("deals") or {}
        b = out.setdefault(brand_slug, {"deals": [], "cats": {}, "pages": 0})
        b["deals"].extend(deals.get("dr") or [])
        b["cats"].update(dict(zip(deals.get("categoryIds") or [], deals.get("categoryNames") or [])))
        b["pages"] += 1
    return out


def report(run: Path) -> None:
    saved = load_saved(run)
    lines = ["brand\tasin\tparent\troot\tcond\tresale_cents\tref_cents\tstrict\tkeepa_pct\ttitle"]
    print(f"\n{'brand':<13} {'rows':>4} {'pages':>5} {'50%+':>5} {'30-49':>5} {'<30':>4}  root categories")
    for brand in BRANDS:
        b = saved.get(slug(brand))
        if b is None:
            print(f"{brand:<13}  (not queried)")
            continue
        rows = [r for d in b["deals"] for r in [analysis.deal_row(d, b["cats"], 0, source=brand)] if r]
        s = [r.strict or 0 for r in rows]
        roots: dict[str, int] = {}
        for r in rows:
            roots[r.root_cat] = roots.get(r.root_cat, 0) + 1
        top = ", ".join(f"{k} {v}" for k, v in sorted(roots.items(), key=lambda kv: -kv[1])[:4])
        more = "+" if b["pages"] >= PAGES and len(b["deals"]) >= PAGES * DEAL_PAGE_SIZE else ""
        print(f"{brand:<13} {len(rows):>4}{more:1} {b['pages']:>4} {sum(x >= 0.5 for x in s):>5} "
              f"{sum(0.3 <= x < 0.5 for x in s):>5} {sum(x < 0.3 for x in s):>4}  {top}")
        for r in rows:
            lines.append("\t".join(str(x) for x in (brand, r.asin, r.parent, r.root_cat, r.condition, r.warehouse_cents,
                                                     r.strict_ref_cents or "", f"{r.strict:.3f}" if r.strict is not None else "",
                                                     r.keepa_reported or "", r.title.replace("\t", " "))))
    (run / "rows.tsv").write_text("\n".join(lines) + "\n")
    print(f"\nrows: {run / 'rows.tsv'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from", dest="saved")
    args = ap.parse_args()
    if args.saved:
        report(Path(args.saved))
        return 0

    cap = tomllib.loads(Path("preflight.toml").read_text())["budget"]["token_cap"]
    ledger = Ledger(Path("research/token-ledger.jsonl"))
    n = len(BRANDS) * PAGES
    print("BRAND PROBE — Keepa /deal, Resale, sweep body without categories, one query per brand")
    print(f"  brands: {', '.join(BRANDS)}")
    print(f"  example body: {json.dumps(query(BRANDS[0], 0))}")
    print(f"  worst case: {n} pages = {n * DEAL_PAGE_COST} tokens (+1 balance probe); "
          f"most brands should stop after 1 page")
    print(f"  pre-flight budget: {ledger.spent()} spent of {cap} cap ({cap - ledger.spent()} left)")
    if args.dry_run:
        print("  --dry-run: no requests made.")
        return 0

    run = preflight.run_id()
    out = Path("research/raw/brand") / run
    keepa = Keepa(LiveTransport(load_api_key()), ledger, out, cap)
    preflight.probe(keepa)
    if not preflight.confirm(f"Spend up to {n * DEAL_PAGE_COST} tokens on {n} deal pages?"):
        print("aborted.")
        return 1
    for brand in BRANDS:
        for page in range(PAGES):
            data = keepa.call("deal", label=f"{slug(brand)}-p{page}", estimate=DEAL_PAGE_COST, body=query(brand, page))
            if len((data.get("deals") or {}).get("dr") or []) < DEAL_PAGE_SIZE:
                break
    print(f"  spent: see ledger; raw in {out}")
    report(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
