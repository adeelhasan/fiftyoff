"""How many of each front shelf's top 12 changed between shelves snapshots (scripts/shelf_snapshot.sh).

Both orderings are rebuilt from each snapshot's fields, whichever version served it: l0.1 (appeal x % off x
condition) and l0.2 (x freshness), so the same pair of days gives the churn without and with the boost.
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


def base(p: dict) -> float:
    a = p["appeal"]["score"] if p.get("appeal") else UNRATED_APPEAL
    return a * p["pct_off"] / 10 * p["score_parts"]["condition_factor"]


def load(path: str) -> dict:
    return json.load(gzip.open(path, "rt") if path.endswith(".gz") else open(path))


def tops(path: str) -> dict[str, dict[str, list[str]]]:
    """{shelf id: {"l0.1": top asins, "l0.2": top asins}}, ties broken by deal score as the API does."""
    out = {}
    for s in load(path)["shelves"]:
        ps = s["products"]
        out[s["id"]] = {
            "l0.1": [p["asin"] for p in sorted(ps, key=lambda p: (-round(base(p), 1), -p["score"]))[:TOP]],
            "l0.2": [p["asin"] for p in sorted(ps, key=lambda p: (-round(base(p) * freshness(p["minutes_since_priced"]), 1),
                                                                 -p["score"]))[:TOP]]}
    return out


def main(a: str, b: str) -> None:
    ta, tb = tops(a), tops(b)
    print(f"{a}\n  -> {b}\nchanged of the top {TOP} (shelves in both):\n")
    print(f"{'shelf':34} {'l0.1':>5} {'l0.2':>5}")
    sums = {"l0.1": [], "l0.2": []}
    for sid in sorted(set(ta) & set(tb)):
        row = []
        for v in ("l0.1", "l0.2"):
            n = min(TOP, len(tb[sid][v]))
            changed = n - len(set(ta[sid][v]) & set(tb[sid][v]))
            sums[v].append(changed)
            row.append(changed)
        print(f"{sid:34} {row[0]:>5} {row[1]:>5}")
    print(f"\n{'total':34} {sum(sums['l0.1']):>5} {sum(sums['l0.2']):>5}")
    print(f"{'median per shelf':34} {statistics.median(sums['l0.1']):>5} {statistics.median(sums['l0.2']):>5}")
    print(f"shelves only in one: {sorted(set(ta) ^ set(tb))}")


def changed(ta: dict, tb: dict, v: str) -> int:
    return sum(min(TOP, len(tb[k][v])) - len(set(ta[k][v]) & set(tb[k][v])) for k in set(ta) & set(tb))


def timeline(paths: list[str]) -> None:
    """Total top-12 changes, summed over the front shelves in both snapshots, l0.1 / l0.2."""
    when = [datetime.strptime(p.rsplit("/", 1)[-1][:16], "%Y-%m-%dT%H%MZ") for p in paths]
    t = [tops(p) for p in paths]
    print(f"{'snapshot (UTC)':17} {'vs previous':>13} {'vs ~24 h ago':>13}   (l0.1 / l0.2, changed of the top {TOP})")
    for i in range(1, len(paths)):
        prev = f"{changed(t[i-1], t[i], 'l0.1')} / {changed(t[i-1], t[i], 'l0.2')}"
        j = min(range(i), key=lambda j: abs(when[i] - when[j] - timedelta(hours=24)))
        day = f"{changed(t[j], t[i], 'l0.1')} / {changed(t[j], t[i], 'l0.2')}" \
            if abs(when[i] - when[j] - timedelta(hours=24)) <= timedelta(hours=2) else "-"
        print(f"{when[i]:%m-%d %H:%M}       {prev:>13} {day:>13}")


if __name__ == "__main__":
    args = sorted(sys.argv[1:])
    if len(sys.argv) == 3:
        main(*sys.argv[1:3])
    else:
        timeline(args)
