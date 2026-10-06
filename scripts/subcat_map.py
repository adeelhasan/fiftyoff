"""D39 step 1: the subcategory map. Free: reads sweep_rows + census_rows (backfilled from raw, rule 8) and cat_node.

Where do good Resale items flow, below the root categories, and what *moves* (comes up for resale often)?
Per subcategory node (levels 2 and 3 under the root, Amazon's structural nodes skipped):
- ASINs and parents seen (kept separate, rule 9), in the window
- "seeable": the deal tiers with NO rank limit (40%+ with $100+ reference, or 30%+ with $200+)
- 50%+ with a $100+ reference, and how many of those pass today's rank limit (top 50k of the root)
- median reference, median 30-day sales-rank drops (a sales proxy independent of root size)
- moving: feed events (distinct ASIN x Keepa price-set time) at the seeable tiers, and parents with
  events on 2+ distinct days
Also the top "movers" by parent, the test case being a smart ring sold in many sizes.

    docker compose run --rm -e PYTHONPATH=/app app python scripts/subcat_map.py [--days 7]
Writes research/subcats/map-<date>.md and .json.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from fiftyoff.tracker import CENSUS_CATS

MAP_VERSION = "m0.1"
STRUCTURAL = {"Categories", "Departments", "Featured Categories", "Custom Stores", "Specialty Stores",
              "Self Service", "Shops", "Stores", "Subscribe & Save"}
TIERS = [(0.40, 10000), (0.30, 20000)]  # TrackerConfig.tiers
MAX_RANK = 50000
KEEPA_OFFSET = 21564000


def seeable(strict, ref) -> bool:
    return strict is not None and ref is not None and any(strict >= d and ref >= r for d, r in TIERS)


def path(nodes: dict, leaf: int) -> list[str]:
    out, seen, cur = [], set(), leaf
    while cur and cur in nodes and cur not in seen:
        seen.add(cur)
        name, parent = nodes[cur]
        if name and name not in STRUCTURAL:
            out.append(name)
        cur = parent
    return out[::-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="research/subcats")
    a = ap.parse_args()
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        nodes = {r[0]: (r[1], r[2]) for r in c.execute("SELECT id, name, parent_id FROM cat_node")}
        rows = c.execute(
            "SELECT 'tracked', asin, parent_asin, category, title, strict, ref_cents, rank, cats, drops30, creation_kmin, "
            "resale_cents FROM sweep_rows WHERE swept_at > now() - make_interval(days => %s) "
            "UNION ALL SELECT 'census', asin, parent_asin, category, title, strict, ref_cents, rank, cats, drops30, "
            "creation_kmin, resale_cents FROM census_rows WHERE swept_at > now() - make_interval(days => %s) "
            "AND cat_id = ANY(%s)",  # categories dropped from the census (D38) are pruned, not mapped
            (a.days, a.days, CENSUS_CATS)).fetchall()

    latest: dict[str, tuple] = {}
    events: set[tuple[str, int]] = set()
    for r in rows:
        src, asin, parent, cat, title, strict, ref, rank, cats, drops, ck, resale = r
        latest[asin] = r
        if seeable(strict, ref) and ck:
            events.add((asin, ck))
    unnamed_leaves = set()
    agg: dict[tuple, dict] = defaultdict(lambda: defaultdict(set) | {"refs": [], "drops": []})
    by_parent: dict[str, dict] = {}
    leaf_of: dict[str, tuple] = {}
    for asin, r in latest.items():
        src, _, parent, cat, title, strict, ref, rank, cats, drops, ck, resale = r
        leaf = (cats or [None])[0]
        p = path(nodes, leaf) if leaf else []
        if leaf and (leaf not in nodes or not nodes[leaf][0]):
            unnamed_leaves.add(leaf)
        root = p[0] if p else cat
        keys = [(root, p[1] if len(p) > 1 else "(unnamed)", None)]
        if len(p) > 2:
            keys.append((root, p[1], p[2]))
        leaf_of[asin] = keys[-1]
        for k in keys:
            g = agg[k]
            g["src"].add(src)
            g["asins"].add(asin)
            g["parents"].add(parent or asin)
            if seeable(strict, ref):
                g["seeable"].add(asin)
            if (strict or 0) >= 0.5 and (ref or 0) >= 10000:
                g["a50"].add(asin)
                g["refs"].append(ref)
                if drops is not None:
                    g["drops"].append(drops)
                if rank is None or rank <= MAX_RANK:
                    g["a50_ranked"].add(asin)
                g.setdefault("examples", []).append((drops or 0, title, round(strict * 100), (resale or 0) // 100))
    ev_days: dict[str, set] = defaultdict(set)
    ev_count: dict[tuple, int] = defaultdict(int)
    for asin, ck in events:
        r = latest.get(asin)
        if not r:
            continue
        parent = r[2] or asin
        ev_days[parent].add(datetime.fromtimestamp((ck + KEEPA_OFFSET) * 60, tz=timezone.utc).date())
        k = leaf_of.get(asin)
        if k:
            ev_count[k] += 1
            ev_count[(k[0], k[1], None)] += 1 if k[2] else 0
    out = []
    for k, g in agg.items():
        movers = {p for p in g["parents"] if len(ev_days.get(p, ())) >= 2}
        ex = sorted(g.get("examples", []), reverse=True)[:3]
        out.append({"root": k[0], "l2": k[1], "l3": k[2], "source": "+".join(sorted(g["src"])),
                    "asins": len(g["asins"]), "parents": len(g["parents"]), "seeable": len(g["seeable"]),
                    "a50": len(g["a50"]), "a50_within_rank": len(g["a50_ranked"]),
                    "median_ref": round(statistics.median(g["refs"]) / 100) if g["refs"] else None,
                    "median_drops30": statistics.median(g["drops"]) if g["drops"] else None,
                    "events": ev_count.get(k, 0), "parents_moving": len(movers & g["parents"]),
                    "examples": [f"{t[:60]} ({o}%, ${p})" for _, t, o, p in ex]})
    out.sort(key=lambda x: -x["a50"])
    movers = sorted(((p, len(d)) for p, d in ev_days.items() if len(d) >= 2), key=lambda x: -x[1])[:30]
    titles = {(r[2] or a): r[4] for a, r in latest.items()}
    all_drops = sorted(r[9] for r in latest.values() if r[9] is not None and (r[5] or 0) >= 0.5 and (r[6] or 0) >= 10000)
    q = lambda f: all_drops[int(f * (len(all_drops) - 1))] if all_drops else None
    summary = {"version": MAP_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(), "days": a.days,
               "asins": len(latest), "events": len(events), "named_nodes": sum(1 for v in nodes.values() if v[0]),
               "unnamed_leaves": len(unnamed_leaves),
               "drops30_quantiles_50pct": {f"p{int(f * 100)}": q(f) for f in (0.1, 0.25, 0.5, 0.75, 0.9)}}

    od = Path(a.out)
    od.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (od / f"map-{stamp}.json").write_text(json.dumps({"summary": summary, "nodes": out,
                                                       "movers": [{"parent": p, "title": titles.get(p), "days": d} for p, d in movers]},
                                                      indent=1, default=str))
    lines = [f"# Subcategory map {stamp} ({MAP_VERSION}, last {a.days} days)", "",
             f"{summary['asins']:,} ASINs seen; {summary['events']:,} feed events at the deal tiers. "
             f"{summary['named_nodes']:,} named nodes; {summary['unnamed_leaves']:,} leaves still unnamed (their items count under '(unnamed)').",
             f"30-day rank drops of 50%+ / $100+ items: {summary['drops30_quantiles_50pct']}", "",
             "| Root | Subcategory | Src | ASINs | Parents | Seeable | 50%+ | of which ≤50k rank | Med ref $ | Med drops30 | Events | Parents moving | Examples |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in out:
        if x["a50"] < 2 and x["seeable"] < 5:
            continue
        name = f"{x['l2']} › {x['l3']}" if x["l3"] else f"**{x['l2']}**"
        lines.append(f"| {x['root']} | {name} | {x['source']} | {x['asins']} | {x['parents']} | {x['seeable']} | {x['a50']} | "
                     f"{x['a50_within_rank']} | {x['median_ref']} | {x['median_drops30']} | {x['events']} | {x['parents_moving']} | "
                     f"{'; '.join(x['examples'])} |")
    lines += ["", "## Movers: parents with deal-tier feed events on the most distinct days", "",
              "| Parent | Days | Title |", "|---|---|---|"]
    lines += [f"| {p} | {d} | {(titles.get(p) or '')[:80]} |" for p, d in movers]
    (od / f"map-{stamp}.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
