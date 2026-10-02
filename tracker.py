"""New-deal tracker (D20): Keepa sweeps find Resale deals; live checks time each unit until it's gone.

    uv run tracker.py unlock             # §7 ungating: prints the plan + Keepa balance, asks [y/N]
    uv run tracker.py run --dry-run      # plan only, no requests
    uv run tracker.py run                # long-running; in Docker: docker compose --profile tracker up -d
    uv run tracker.py status             # free, from Postgres
    uv run tracker.py report             # free, from Postgres -> research/tracker/report.md

The approval file (.fiftyoff/tracker-approval.json, gitignored) carries a token cap and an expiry.
Without a valid one, `run` waits and re-checks every 10 min instead of exiting, so a container
restart policy can't crash-loop it, and it never spends a token unapproved (CLAUDE.md rules 1-2).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import preflight
from fiftyoff.keepa import FixtureTransport, Keepa, Ledger, LiveTransport, load_api_key
from fiftyoff.tracker import MemoryStore, Tracker, TrackerConfig, iso, lifespan

APPROVAL = Path(".fiftyoff/tracker-approval.json")
ROOT = Path("research/tracker")
TOKENS_PER_DAY = 20 * 60 * 24  # base plan: 20 tokens/min
DEFAULT_DSN = "postgresql://fiftyoff:fiftyoff-dev@localhost:5432/fiftyoff"


def dsn() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DSN)


def read_approval(now: datetime) -> dict | None:
    if not APPROVAL.exists():
        return None
    a = json.loads(APPROVAL.read_text())
    if not a.get("approvedByUser") or datetime.fromisoformat(a["expires"]) <= now:
        return None
    return a


def plan_lines(c: TrackerConfig) -> list[str]:
    tiers = " or ".join(f"strict {d:.0%}+ with ${r // 100}+ reference" for d, r in c.tiers)
    return [
        f"TRACKER — sweep every {c.sweep_minutes} min (incremental, ~1-2 pages; full every {c.full_sweep_hours} h, "
        f"≤{c.full_sweep_max_pages} pages × 5 tokens)",
        f"  qualifies: {tiers}; sales rank ≤{c.max_rank:,}; 5 target categories",
        f"  live checks (~{c.check_estimate} tokens): every {c.fast_minutes} min while new (<6 h), "
        f"{c.unconfirmed_minutes} min while a unit is unconfirmed, else {c.slow_minutes} min",
        f"  spends up to the plan's refill rate (~{TOKENS_PER_DAY:,} tokens/day); cadence degrades when over",
        f"  throughput: ~{checks_per_hour(c):.0f} checks/hour after sweeps. New deals (<6 h old by Keepa's date) "
        f"go first; with hundreds of older watches, expect several hours between their checks.",
    ]


def checks_per_hour(c: TrackerConfig) -> float:
    sweeps = (2 * 5 / c.sweep_minutes) + (c.full_sweep_max_pages * 5 / (c.full_sweep_hours * 60))  # tokens/min
    return (20 - sweeps) / c.check_estimate * 60


def make_keepa(args, cap: int, cap_since: str | None) -> Keepa:
    transport = FixtureTransport(Path(args.fixtures)) if args.fixtures else LiveTransport(load_api_key())
    root = Path(args.root)
    run_dir = root / "raw" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Keepa(transport, Ledger(root / "token-ledger.jsonl"), run_dir, token_cap=cap,
                 raw_gzip=True, cap_since=cap_since)


def make_store(args):
    if args.memory:
        return MemoryStore()
    from fiftyoff.store_pg import PgStore
    return PgStore(dsn())


def cmd_unlock(args, cfg, input_fn=input) -> int:
    c = TrackerConfig.from_toml(cfg.get("tracker", {}))
    print("\n".join(plan_lines(c)))
    keepa = make_keepa(args, cap=10**9, cap_since=None)  # the balance call is free; no cap applies
    data = keepa.call("token", label="balance", estimate=0)  # free: token bucket status only
    print(f"  Keepa balance: {data.get('tokensLeft')} tokens, refill {data.get('refillRate')}/min")
    days = args.days
    cap = args.token_cap or days * TOKENS_PER_DAY
    print(f"  approval: {days} days, hard cap {cap:,} tokens for this run")
    if input_fn("Approve continuous Keepa polling by the tracker? [y/N] ").strip().lower() not in ("y", "yes"):
        print("not approved.")
        return 1
    now = datetime.now(timezone.utc)
    APPROVAL.parent.mkdir(exist_ok=True)
    APPROVAL.write_text(json.dumps({
        "approvedByUser": True, "approvedAt": now.isoformat(timespec="seconds"),
        "expires": (now + timedelta(days=days)).isoformat(timespec="seconds"),
        "tokenCap": cap, "scope": "new-deal tracker (D20)",
    }, indent=2))
    print(f"wrote {APPROVAL} (expires {(now + timedelta(days=days)):%Y-%m-%d %H:%M} UTC)")
    return 0


def cmd_run(args, cfg) -> int:
    c = TrackerConfig.from_toml(cfg.get("tracker", {}))
    print("\n".join(plan_lines(c)))
    if args.dry_run:
        print("  --dry-run: no requests made.")
        return 0
    store = make_store(args)
    tracker = keepa = approved_at = None
    steps = 0
    while args.max_steps is None or steps < args.max_steps:
        a = {"approvedAt": "1970", "tokenCap": 10**9} if args.fixtures else read_approval(datetime.now(timezone.utc))
        if a is None:
            print(f"[{iso(time.time())}] no valid {APPROVAL} (missing or expired); waiting 10 min. "
                  f"Run `tracker.py unlock` to approve.")
            time.sleep(600)
            continue
        if a["approvedAt"] != approved_at:  # (re)build the client when the approval changes
            approved_at = a["approvedAt"]
            keepa = make_keepa(args, cap=a["tokenCap"], cap_since=approved_at)
            tracker = Tracker(c, keepa, store)
        if keepa.remaining_budget() < c.check_estimate:
            print(f"[{iso(time.time())}] token cap {a['tokenCap']:,} reached for this approval; waiting 15 min")
            time.sleep(900)
            continue
        try:
            did = tracker.step()
        except Exception as e:  # a weeks-long run must survive outages; raw + ledger already record calls
            if type(e).__module__.startswith("psycopg"):
                raise  # dead DB connection: exit so Docker restarts us with a fresh one and reloaded state
            print(f"[{iso(time.time())}] error: {type(e).__name__}: {e}; pausing 2 min")
            time.sleep(120)
            continue
        steps += 1
        if did == "idle":
            time.sleep(5 if args.fixtures else 30)
    return 0


def cmd_status(args, cfg) -> int:
    from fiftyoff.store_pg import PgStore
    s = PgStore(dsn())
    q = lambda sql: s.conn.execute(sql).fetchall()
    hb = q("SELECT value FROM tracker_state WHERE key = 'heartbeat'")
    print(f"heartbeat: {iso(hb[0][0]) if hb else 'never'}")
    print("watching:", q("SELECT count(*) FILTER (WHERE retired_at IS NULL), count(*) FROM watch")[0])
    print("units by state:", dict(q("SELECT state, count(*) FROM units GROUP BY 1")))
    print("feed (qualifying, not gone):", q("SELECT count(*) FROM feed")[0][0])
    print("checks, last 24 h:", q("SELECT count(*) FROM checks WHERE checked_at > now() - interval '24 hours'")[0][0])
    a = read_approval(datetime.now(timezone.utc))
    led = Ledger(Path(args.root) / "token-ledger.jsonl")
    if a:
        print(f"approval: expires {a['expires']}, spent {led.spent(a['approvedAt']):,} of {a['tokenCap']:,} tokens")
    else:
        print("approval: none valid")
    return 0


def cmd_report(args, cfg) -> int:
    from fiftyoff.store_pg import PgStore
    from fiftyoff.tracker import Unit
    s = PgStore(dsn())
    _, units, _ = s.load()
    gone = [(u, lifespan(u)) for u in units.values() if u.state == "gone"]
    first = s.conn.execute("SELECT min(first_seen_at), max(last_seen_at) FROM units").fetchone()
    by_cat = s.conn.execute(
        "SELECT w.category, count(*) FROM units u JOIN watch w USING (asin) "
        "WHERE u.appeared_after_at IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").fetchall()
    L = ["# New-deal tracker report\n",
         f"Units from {first[0]:%Y-%m-%d %H:%M} to {first[1]:%Y-%m-%d %H:%M} UTC." if first[0] else "No units yet.",
         f"- Units tracked: {len(units)}; live {sum(u.state == 'live' for u in units.values())}, "
         f"unconfirmed {sum(u.state == 'unconfirmed' for u in units.values())}, gone {len(gone)}",
         f"- Revived after being marked gone: {sum(u.revivals > 0 for u in units.values())}",
         "\n## New units seen to appear (first seen after a check without them), by category\n",
         "| category | units |", "|---|---|"] + [f"| {c} | {n} |" for c, n in by_cat]
    L += ["\n## Gone units: lifespan bounds (minutes)\n", "| asin | cond | price | lower | upper | confidence |",
          "|---|---|---|---|---|---|"]
    for u, ls in sorted(gone, key=lambda x: (x[1]["upper_min"] is None, x[1]["upper_min"] or 0))[:200]:
        L.append(f"| {u.asin} | {u.cond} | ${u.last_price / 100:.2f} | {ls["lower_min"]:.0f} | {"≥" if ls["upper_min"] is None else ""}{ls["upper_min"] or ls["lower_min"]:.0f} | {ls['confidence']} |")
    out = Path(args.root) / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L[:6]))
    print(f"wrote {out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="preflight.toml")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--fixtures", help="serve Keepa responses from this directory (free rehearsal)")
    ap.add_argument("--memory", action="store_true", help="keep state in memory instead of Postgres")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unlock")
    u.add_argument("--days", type=int, default=14)
    u.add_argument("--token-cap", type=int)
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--max-steps", type=int)
    sub.add_parser("status")
    sub.add_parser("report")
    args = ap.parse_args(argv)
    cfg = preflight.load_config(Path(args.config))
    return {"unlock": cmd_unlock, "run": cmd_run, "status": cmd_status, "report": cmd_report}[args.cmd](args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
