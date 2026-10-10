"""How many of each front shelf's top 12 changed between shelves snapshots (scripts/shelf_snapshot.sh).

The orderings are rebuilt from each snapshot's fields, whichever version served it: l0.1 (appeal x % off x
condition), l0.2 (x freshness, boost 1.3) and l0.3 (boost 1.6), so the same pair of days gives the churn without
and with each boost.
    PYTHONPATH=. uv run python scripts/shelf_churn.py A.json.gz B.json.gz      # per shelf, A -> B
    PYTHONPATH=. uv run python scripts/shelf_churn.py research/shelves/snapshots/*  # a timeline: each snapshot vs
        the previous one and vs ~24 h earlier (the visitor who comes back hourly, and daily)
"""

import gzip
import json
import statistics
import sys

from datetime import datetime, timedelta

from fiftyoff.api import UNRATED_APPEAL, freshness

TOP = 12
VERSIONS = {"l0.1": 1.0, "l0.2": 1.3, "l0.3": 1.6}  # delight version -> freshness boost


def base(p: dict) -> float:
    a = p["appeal"]["score"] if p.get("appeal") else UNRATED_APPEAL
    return a * p["pct_off"] / 10 * p["score_parts"]["condition_factor"]


def load(path: str) -> dict:
    return json.load(gzip.open(path, "rt") if path.endswith(".gz") else open(path))


def tops(path: str) -> dict[str, dict[str, list[str]]]:
    """{shelf id: {version: top asins}}, ties broken by deal score as the API does."""
    out = {}
    for s in load(path)["shelves"]:
        ps = s["products"]
        out[s["id"]] = {v: [p["asin"] for p in sorted(ps, key=lambda p: (
            -round(base(p) * freshness(p["minutes_since_priced"], b), 1), -p["score"]))[:TOP]] for v, b in VERSIONS.items()}
    return out


def main(a: str, b: str) -> None:
    ta, tb = tops(a), tops(b)
    print(f"{a}\n  -> {b}\nchanged of the top {TOP} (shelves in both):\n")
    print(f"{'shelf':34}" + "".join(f" {v:>5}" for v in VERSIONS))
    sums: dict[str, list[int]] = {v: [] for v in VERSIONS}
    for sid in sorted(set(ta) & set(tb)):
        for v in VERSIONS:
            sums[v].append(min(TOP, len(tb[sid][v])) - len(set(ta[sid][v]) & set(tb[sid][v])))
        print(f"{sid:34}" + "".join(f" {sums[v][-1]:>5}" for v in VERSIONS))
    print(f"\n{'total':34}" + "".join(f" {sum(sums[v]):>5}" for v in VERSIONS))
    print(f"{'median per shelf':34}" + "".join(f" {statistics.median(sums[v]):>5}" for v in VERSIONS))
    print(f"shelves only in one: {sorted(set(ta) ^ set(tb))}")


def changed(ta: dict, tb: dict, v: str) -> int:
    return sum(min(TOP, len(tb[k][v])) - len(set(ta[k][v]) & set(tb[k][v])) for k in set(ta) & set(tb))


def timeline(paths: list[str]) -> None:
    """Total top-12 changes, summed over the front shelves in both snapshots, per delight version."""
    when = [datetime.strptime(p.rsplit("/", 1)[-1][:16], "%Y-%m-%dT%H%MZ") for p in paths]
    t = [tops(p) for p in paths]
    vs = " / ".join(VERSIONS)
    print(f"{'snapshot (UTC)':17} {'vs previous':>16} {'vs ~24 h ago':>16}   ({vs}, changed of the top {TOP})")
    for i in range(1, len(paths)):
        prev = " / ".join(str(changed(t[i-1], t[i], v)) for v in VERSIONS)
        j = min(range(i), key=lambda j: abs(when[i] - when[j] - timedelta(hours=24)))
        day = " / ".join(str(changed(t[j], t[i], v)) for v in VERSIONS) \
            if abs(when[i] - when[j] - timedelta(hours=24)) <= timedelta(hours=2) else "-"
        print(f"{when[i]:%m-%d %H:%M}       {prev:>16} {day:>16}")


if __name__ == "__main__":
    args = sorted(sys.argv[1:])
    if len(sys.argv) == 3:
        main(*sys.argv[1:3])
    else:
        timeline(args)
