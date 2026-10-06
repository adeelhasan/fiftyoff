"""D39 backfill, free: subcategory ids + 30-day rank drops on old sweep/census rows, and subcategory names,
from the saved raw Keepa responses (rule 8). Idempotent: only rows with cats IS NULL are touched.

Rows get the values from their ASIN's latest saved feed object (categories don't change; drops30 moves
slowly, so old rows carry a recent value: fine for the subcategory map, recorded in D39).

    docker compose run --rm app python scripts/backfill_d39.py [--raw research/tracker/raw]
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path

import psycopg

from fiftyoff.tracker import feed_signals


def scan(raw: Path):
    feed: dict[str, tuple[str, dict]] = {}  # asin -> (sentAt, signals) from its latest feed object
    nodes: dict[int, tuple[str | None, int | None]] = {}
    files = sorted(raw.glob("*/*.json.gz"))
    for i, f in enumerate(files):
        label = f.name.split("-", 1)[1]
        if not label.startswith(("sweep-", "census-", "check-")):
            continue
        with gzip.open(f, "rt") as fh:
            d = json.load(fh)
        resp, sent = d.get("response") or {}, d.get("request", {}).get("sentAt", "")
        if label.startswith("check-"):
            for p in resp.get("products") or []:
                tree = [c for c in p.get("categoryTree") or [] if c.get("catId")]
                for j, c in enumerate(tree):
                    nodes[c["catId"]] = (c.get("name"), tree[j - 1]["catId"] if j else None)
            continue
        for x in (resp.get("deals") or {}).get("dr") or []:
            if x.get("asin") and sent >= feed.get(x["asin"], ("",))[0]:
                feed[x["asin"]] = (sent, feed_signals(x))
        if i % 2000 == 0:
            print(f"  {i}/{len(files)} files, {len(feed)} asins, {len(nodes)} nodes", flush=True)
    return feed, nodes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="research/tracker/raw")
    a = ap.parse_args()
    feed, nodes = scan(Path(a.raw))
    print(f"scanned: {len(feed)} asins with feed signals, {len(nodes)} named nodes")
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO cat_node (id, name, parent_id, updated_at) VALUES (%s,%s,%s,now()) ON CONFLICT (id) DO UPDATE "
                "SET name = COALESCE(EXCLUDED.name, cat_node.name), parent_id = COALESCE(EXCLUDED.parent_id, cat_node.parent_id)",
                [(k, n, p) for k, (n, p) in nodes.items()])
        c.execute("CREATE TEMP TABLE bf (asin text PRIMARY KEY, cats bigint[], drops30 int)")
        with c.cursor() as cur:
            with cur.copy("COPY bf (asin, cats, drops30) FROM STDIN") as cp:
                for asin, (_, s) in feed.items():
                    cp.write_row((asin, s["cats"], s["drops30"]))
        for t in ("sweep_rows", "census_rows"):
            n = c.execute(f"UPDATE {t} r SET cats = bf.cats, drops30 = bf.drops30 FROM bf "
                          f"WHERE r.asin = bf.asin AND r.cats IS NULL").rowcount
            left = c.execute(f"SELECT count(*) FROM {t} WHERE cats IS NULL").fetchone()[0]
            print(f"{t}: {n} rows backfilled, {left} still without cats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
