"""The API rater (fiftyoff/rater.py): rates new products with the Anthropic API, paid by the Max plan's monthly API
credits (ANTHROPIC_API_KEY in .env, a key from the linked Console organization). Settings: preflight.toml [rater].

    docker compose run --rm app rater.py once --dry-run     # free: what it would rate, and this month's spend
    docker compose run --rm app rater.py compare --n 100    # supervised check against the subscription's ratings (paid)
    docker compose run --rm app rater.py once               # one round of batches (paid)
    docker compose run --rm app rater.py status             # spend this month, last batches
    docker compose --profile rater up -d rater              # the loop (`rater.py run`)

Without ANTHROPIC_API_KEY it says so and exits; it never waits on a missing key. Rule 7: ratings only, never prices,
discounts or availability, and the tracker never imports it.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg

import preflight
from fiftyoff import rater
from fiftyoff.store_pg import SCHEMA

DEFAULT_DSN = "postgresql://fiftyoff:fiftyoff-dev@localhost:5432/fiftyoff"


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


def connect():
    return psycopg.connect(os.environ.get("DATABASE_URL", DEFAULT_DSN), autocommit=True)


def need_key() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    log("no ANTHROPIC_API_KEY in .env: the API rater is off (the Mac's rate_local.py keeps rating)")
    return False


def make_call():
    from fiftyoff.claude_client import make_call  # the SDK is imported only when a call will be made
    return make_call()


def cmd_status(cfg: rater.RaterConfig, conn) -> int:
    now = datetime.now(timezone.utc)
    spent = rater.PgRaterStore(conn).spent_since(rater.month_start(now))
    print(f"{cfg.model_id}, effort {cfg.effort}: ${spent:.2f} of ${cfg.monthly_usd_cap:.2f} this month; "
          f"key {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'not set'}")
    for r in conn.execute("SELECT at, sent, loaded, bad, stop_reason, input_tokens, cache_read_tokens, output_tokens, "
                          "usd, error FROM rater_batch ORDER BY at DESC LIMIT 10"):
        print("  ", " ".join("-" if x is None else str(x) for x in r))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="preflight.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once").add_argument("--dry-run", action="store_true")
    sub.add_parser("run")
    c = sub.add_parser("compare")
    c.add_argument("--n", type=int, default=100)
    c.add_argument("--against", default="local", help="the rated_by backend to compare with")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    cfg = rater.RaterConfig.from_toml(preflight.load_config(Path(args.config)).get("rater", {}))
    with connect() as conn:
        conn.execute(SCHEMA)  # idempotent: rater_batch may not exist yet if the tracker hasn't restarted since a deploy
        store = rater.PgRaterStore(conn)
        if args.cmd == "status":
            return cmd_status(cfg, conn)
        if args.cmd == "once" and args.dry_run:
            rater.round_(store, None, cfg, log, dry=True)
            return 0
        if not need_key():
            return 0
        call = make_call()
        if args.cmd == "compare":
            rater.compare(store, call, cfg, datetime.now(timezone.utc), args.n, args.against, log)
            return 0
        if args.cmd == "once":
            rater.round_(store, call, cfg, log)
            return 0
        log(f"rater up: {cfg.model_id}, effort {cfg.effort}, every {cfg.interval_minutes} min, cap ${cfg.monthly_usd_cap}/month")
        while True:
            rater.round_(store, call, cfg, log)
            time.sleep(cfg.interval_minutes * 60)


if __name__ == "__main__":
    raise SystemExit(main())
