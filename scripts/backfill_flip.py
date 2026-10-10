"""Flip estimate backfill, free: the cheapest other used offer (arbitrage.other_used) for each ASIN's latest
check, from the saved raw Keepa responses (rule 8). New checks record it themselves; this fills the rest.
Idempotent: only check rows whose ref_flags lack `used_3p` are touched.

    docker compose run --rm app python scripts/backfill_flip.py [--raw research/tracker/raw]
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path

import psycopg

from fiftyoff.arbitrage import other_used


def latest_checks(raw: Path) -> dict[str, Path]:
    """ASIN -> its newest raw check file (run folders sort by time, files by sequence within a run)."""
    out: dict[str, tuple[tuple, Path]] = {}
    for f in raw.glob("*/*-check-*.json.gz"):
        seq, _, asin = f.name.removesuffix(".json.gz").split("-", 2)
        key = (f.parent.name, int(seq) if seq.isdigit() else 0)
        if asin not in out or key > out[asin][0]:
            out[asin] = (key, f)
    return {a: f for a, (_, f) in out.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("research/tracker/raw"))
    args = ap.parse_args()
    files = latest_checks(args.raw)
    n = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for asin, f in files.items():
            with gzip.open(f, "rt") as fh:
                prods = (json.load(fh).get("response") or {}).get("products") or []
            if not prods:
                continue
            cur = conn.execute(
                "UPDATE checks SET ref_flags = coalesce(ref_flags, '{}'::jsonb) || %s::jsonb WHERE id = "
                "(SELECT id FROM checks WHERE asin = %s AND offers_ok ORDER BY checked_at DESC LIMIT 1) "
                "AND NOT coalesce(ref_flags ? 'used_3p', false)", (json.dumps(other_used(prods[0])), asin))
            n += cur.rowcount
    print(f"{len(files)} ASINs with a raw check; {n} latest checks given used_3p")


if __name__ == "__main__":
    main()
