"""Track 1 (D16): Resale presence on popular products — the browser-extension question.

    uv run track1.py universe [--dry-run]   # Product Finder: popular $100+ products per category
    uv run track1.py sample                 # offline: rank-stratified sample -> research/track1/sample.json
    uv run track1.py history [--dry-run]    # /product offers per sampled ASIN (resumable)
    uv run track1.py report                 # offline -> research/track1/report.md + data.json

Same rules as preflight.py: budget cap, [y/N], raw saved before parsing, every call ledgered.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import preflight
from fiftyoff import presence
from fiftyoff.keepa import DOMAIN_US, history_offer_cost, unix_to_keepa

CATEGORIES = {
    "Electronics": 172282,
    "Home & Kitchen": 1055398,
    "Appliances": 2619525011,
    "Tools & Home Improvement": 228013,
    "Sports & Outdoors": 3375251,
}
FINDER_MAX = 10_000


def universe_query(cfg: dict, cat: int, per_page: int, resale_only: bool = False) -> dict:
    t = cfg["track1"]
    q = {
        "rootCategory": [cat],
        "avg90_NEW_gte": t["min_normal_cents"],
        "current_SALES_gte": 1,
        "current_SALES_lte": t["max_rank"],
        "singleVariation": True,
        "sort": [["current_SALES", "asc"]],
        "perPage": per_page,
        "page": 0,
    }
    if resale_only:
        q["current_WAREHOUSE_gte"] = 1
    return q


def out_dir(ctx) -> Path:
    d = ctx.root / "track1"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_universe(ctx) -> int:
    t = ctx.cfg["track1"]
    worst = len(CATEGORIES) * (10 + FINDER_MAX // 100 + 11)
    print(f"UNIVERSE — Product Finder, {len(CATEGORIES)} categories, 90-day New avg >= ${t['min_normal_cents'] // 100}, "
          f"sales rank <= {t['max_rank']:,}, one variation per parent")
    print(f"  per category: full ASIN list (10 + 1 per 100 ASINs) + a Resale-now count (11)")
    print(f"  worst case {worst} tokens;", preflight.budget_line(ctx))
    if ctx.dry_run:
        print("  --dry-run: no requests made.")
        return 0
    keepa = ctx.client("track1-universe")
    preflight.probe(keepa)
    if not ctx.confirm(f"Spend up to {worst} tokens on the product universe?"):
        return 1
    for name, cat in CATEGORIES.items():
        a = keepa.call("query", label=f"universe-{cat}", estimate=10 + FINDER_MAX // 100,
                       params={"domain": DOMAIN_US}, body=universe_query(ctx.cfg, cat, FINDER_MAX))
        b = keepa.call("query", label=f"resale-now-{cat}", estimate=11,
                       params={"domain": DOMAIN_US}, body=universe_query(ctx.cfg, cat, 50, resale_only=True))
        print(f"  {name:<26} {a.get('totalResults'):>6,} products, {b.get('totalResults'):>6,} with a Resale offer now "
              f"({a.get('tokensConsumed')}+{b.get('tokensConsumed')} tokens)")
    print(" ", preflight.budget_line(ctx))
    return 0


def load_universe(ctx) -> dict:
    out = {}
    for run in preflight.all_runs(ctx.root, "track1-universe"):
        for rec in preflight.raw_files(run, "query"):
            cat = rec["request"]["body"]["rootCategory"][0]
            kind = "resale" if rec["label"].startswith("resale-now") else "all"
            resp = rec["response"]
            out.setdefault(cat, {})[kind] = {"total": resp.get("totalResults"), "asins": resp.get("asinList") or []}
    return out


def cmd_sample(ctx) -> int:
    per = ctx.cfg["track1"]["per_category"]
    uni = load_universe(ctx)
    sample = []
    for name, cat in CATEGORIES.items():
        asins = (uni.get(cat) or {}).get("all", {}).get("asins", [])
        if not asins:
            continue
        # Evenly spaced through the rank-sorted list, so every popularity band is represented.
        step = max(1, len(asins) / per)
        picks = [asins[min(len(asins) - 1, int(i * step))] for i in range(min(per, len(asins)))]
        sample += [{"asin": a, "category": name, "rank_position": i} for i, a in enumerate(picks)]
    path = out_dir(ctx) / "sample.json"
    path.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "sample": sample}, indent=2))
    print(f"sampled {len(sample)} ASINs -> {path}")
    print("  by category:", dict(Counter(s["category"] for s in sample)))
    return 0


def fetched_asins(ctx) -> set[str]:
    done = set()
    for run in preflight.all_runs(ctx.root, "track1-history"):
        for rec in preflight.raw_files(run, "product"):
            done |= {p["asin"] for p in rec["response"].get("products") or []}
    return done


def cmd_history(ctx) -> int:
    t = ctx.cfg["track1"]
    sample = json.loads((out_dir(ctx) / "sample.json").read_text())["sample"]
    todo = [s["asin"] for s in sample if s["asin"] not in fetched_asins(ctx)]
    batch = t["batch_size"]
    per = history_offer_cost(1, t["offers"], historical_variations=False)
    print(f"HISTORY — {len(todo)} of {len(sample)} ASINs left, offers={t['offers']} days={t['fetch_days']}, "
          f"batches of {batch}; worst case {per * len(todo)} tokens (expect ~7/ASIN)")
    print(" ", preflight.budget_line(ctx))
    if ctx.dry_run or not todo:
        return 0
    keepa = ctx.client("track1-history")
    preflight.probe(keepa)
    if not ctx.confirm(f"Spend up to {per * len(todo)} tokens on {len(todo)} product histories?"):
        return 1
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        data = keepa.call("product", label=f"product-batch{i // batch:03d}", estimate=per * len(chunk), params={
            "domain": DOMAIN_US, "asin": ",".join(chunk), "offers": t["offers"],
            "days": t["fetch_days"], "stats": t["days"],
        })
        print(f"  {i + len(chunk):>4}/{len(todo)}  {data.get('tokensConsumed')} tokens, {data.get('tokensLeft')} left")
    print(" ", preflight.budget_line(ctx))
    return 0


def load_profiles(ctx) -> list[presence.Presence]:
    t = ctx.cfg["track1"]
    ths = tuple(ctx.cfg["analysis"]["thresholds"])
    cats = {s["asin"]: s["category"] for s in json.loads((out_dir(ctx) / "sample.json").read_text())["sample"]}
    rows = {}
    for run in preflight.all_runs(ctx.root, "track1-history"):
        for rec in preflight.raw_files(run, "product"):
            resp = rec["response"]
            ts = resp.get("timestamp")
            now = unix_to_keepa(ts / 1000) if ts else unix_to_keepa(
                datetime.fromisoformat(rec["request"]["sentAt"]).timestamp())
            prods = resp.get("products") or []
            for p in prods:
                r = presence.resale_profile(p, now, t["days"], ths, cats.get(p["asin"], "?"))
                r.tokens = round((resp.get("tokensConsumed") or 0) / max(1, len(prods)), 1)
                rows[r.asin] = r
    return list(rows.values())


def band(cents, edges=(10000, 25000, 50000)):
    if not cents:
        return "unknown"
    lab = ["<$100", "$100–250", "$250–500", "$500+"]
    return lab[sum(cents >= e for e in edges)]


def rank_band(r):
    if not r:
        return "no rank"
    return "rank ≤5k" if r <= 5000 else "rank 5k–20k" if r <= 20000 else "rank 20k–50k" if r <= 50000 else "rank >50k"


def cmd_report(ctx) -> int:
    ths = tuple(ctx.cfg["analysis"]["thresholds"])
    rows = load_profiles(ctx)
    if not rows:
        print("no history yet")
        return 1
    uni = load_universe(ctx)
    groups = {"all": rows}
    for key, fn in (("cat", lambda r: r.category), ("price", lambda r: band(r.normal_cents)), ("rank", lambda r: rank_band(r.rank))):
        for r in rows:
            groups.setdefault(f"{key}:{fn(r)}", []).append(r)
    summ = {g: presence.summarize(rs, ths) for g, rs in groups.items()}
    universe = {name: {"total": (uni.get(cat) or {}).get("all", {}).get("total"),
                       "resale_now": (uni.get(cat) or {}).get("resale", {}).get("total")}
                for name, cat in CATEGORIES.items()}
    data = {"algo": presence.PRESENCE_ALGO_VERSION, "thresholds": ths, "universe": universe,
            "summaries": {g: {**s, "conditions": dict(s["conditions"])} for g, s in summ.items()},
            "products": [asdict(r) for r in rows]}
    (out_dir(ctx) / "data.json").write_text(json.dumps(data, default=str))
    (out_dir(ctx) / "report.md").write_text(render(data, ths))
    a = summ["all"]
    print(f"{a['n']} products: live Resale now {a['live_now']:.0%}, ever present in 180d {a['ever_present']:.0%}, "
          f"hit 50%+ {a['hit'][0.5]:.0%}, median presence {a['median_presence']:.0%}")
    return 0


def render(data, ths) -> str:
    pct = lambda x: "—" if x is None else f"{x:.0%}"  # noqa: E731
    L = ["# Track 1 — Resale presence on popular products\n",
         f"Algorithm `{data['algo']}`. Popular = sales rank ≤ 50k in its root category; normal price = 90-day New avg ≥ $100.\n",
         "## Universe (Product Finder, whole catalogue)\n",
         "| category | popular $100+ products | with a Resale offer now (Keepa's latest) | share |", "|---|---|---|---|"]
    for k, u in data["universe"].items():
        share = u["resale_now"] / u["total"] if u["total"] and u["resale_now"] is not None else None
        L.append(f"| {k} | {u['total']:,} | {u['resale_now']:,} | {pct(share)} |" if u["total"] else f"| {k} | — | — | — |")
    L += ["\n## Sample profiles\n",
          "| group | n | live Resale now | live at 50%+ now | ever present (180d) | median presence share | median discount when present | "
          + " | ".join(f"hit {int(t * 100)}%+" for t in ths) + " | 50%+ episodes / product | Resale units seen / product | units gone / product | median check gap |",
          "|" + "---|" * (11 + len(ths))]
    for g, s in data["summaries"].items():
        L.append(f"| {g} | {s['n']} | {pct(s['live_now'])} | {pct(s['live_50_now'])} | {pct(s['ever_present'])} | {pct(s['median_presence'])} | "
                 f"{pct(s['median_discount'])} | " + " | ".join(pct(s['hit'][t] if t in s['hit'] else s['hit'].get(str(t))) for t in ths)
                 + f" | {s['episodes_per_product'].get(0.5, 0):.2f} | {s['units_seen_per_product']:.1f} | {s['units_gone_per_product']:.1f} | "
                 f"{'—' if s['median_gap_min'] is None else f'{s['median_gap_min'] / 60:.1f}h'} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="preflight.toml")
    ap.add_argument("--fixtures")
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("universe", "history"):
        sub.add_parser(name).add_argument("--dry-run", action="store_true")
    sub.add_parser("sample")
    sub.add_parser("report")
    args = ap.parse_args(argv)
    ctx = preflight.Ctx(args)
    return {"universe": cmd_universe, "sample": cmd_sample, "history": cmd_history, "report": cmd_report}[args.cmd](ctx)


if __name__ == "__main__":
    sys.exit(main())
