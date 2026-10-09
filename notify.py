"""Notifications v1 (exploratory): subscribe an address to shelves, and run the notifier (fiftyoff/notify.py).

No registration yet: subscribers are added here, on the VPS, e.g.
    docker compose run --rm app notify.py subscribe you@example.com --shelf headphones-earbuds --aisle kitchen
    docker compose run --rm app notify.py list
    docker compose run --rm app notify.py unwatch you@example.com --aisle kitchen
    docker compose run --rm app notify.py tier you@example.com plus      # tiers and their perks: [tiers.*] in preflight.toml
    docker compose run --rm app notify.py pause you@example.com           # or resume
    docker compose run --rm app notify.py shelves [--aisle kitchen]       # shelf ids and who watches them
    docker compose run --rm app notify.py events                          # what the notifier decided lately
    docker compose run --rm app notify.py test-email you@example.com      # one message through the configured sender
    docker compose up -d notifier                                          # the loop (`notify.py run`)
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

import preflight
from fiftyoff import notify, notifier
from fiftyoff.store_pg import SCHEMA

DEFAULT_DSN = "postgresql://fiftyoff:fiftyoff-dev@localhost:5432/fiftyoff"


def connect():
    return psycopg.connect(os.environ.get("DATABASE_URL", DEFAULT_DSN), autocommit=True, row_factory=dict_row)


def _subscriber(conn, email: str) -> dict:
    s = conn.execute("SELECT * FROM subscriber WHERE email = %s", (email.lower(),)).fetchone()
    if not s:
        raise SystemExit(f"no subscriber {email}")
    return s


def cmd_subscribe(args, cfg, conn) -> int:
    email = args.email.lower()
    shelves = {r["id"]: r for r in conn.execute("SELECT id, aisle FROM shelf")}
    aisles = {r["aisle"] for r in shelves.values()}
    bad = [s for s in args.shelf if s not in shelves] + [a for a in args.aisle if a not in aisles]
    if bad:
        raise SystemExit(f"unknown shelf or aisle: {', '.join(bad)} (see `notify.py shelves`)")
    s = conn.execute("INSERT INTO subscriber (email, tier) VALUES (%s, %s) ON CONFLICT (email) DO UPDATE SET email = "
                     "EXCLUDED.email RETURNING *", (email, args.tier or "free")).fetchone()
    conn.execute("INSERT INTO endpoint (subscriber_id, kind, address) VALUES (%s, 'email', %s) ON CONFLICT (kind, address) "
                 "DO UPDATE SET disabled_at = NULL, failures = 0", (s["id"], email))
    if args.tier:
        conn.execute("UPDATE subscriber SET tier = %s WHERE id = %s", (args.tier, s["id"]))
    have = conn.execute("SELECT count(*) AS n FROM interest WHERE subscriber_id = %s", (s["id"],)).fetchone()["n"]
    new = [("shelf", x) for x in args.shelf] + [("aisle", x) for x in args.aisle]
    cap = notify.perks(cfg, args.tier or s["tier"])["max_interests"]
    if have + len(new) > cap and not args.force:
        print(f"note: tier '{args.tier or s['tier']}' allows {cap} interests; this makes {have + len(new)} "
              "(kept anyway while testing; the cap isn't enforced yet)")
    for kind, value in new:
        conn.execute("INSERT INTO interest (subscriber_id, kind, value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                     (s["id"], kind, value))
    return cmd_list(args, cfg, conn)


def cmd_unwatch(args, cfg, conn) -> int:
    s = _subscriber(conn, args.email)
    for kind, values in (("shelf", args.shelf), ("aisle", args.aisle)):
        for v in values:
            conn.execute("DELETE FROM interest WHERE subscriber_id = %s AND kind = %s AND value = %s", (s["id"], kind, v))
    return cmd_list(args, cfg, conn)


def cmd_set(args, cfg, conn, **fields) -> int:
    s = _subscriber(conn, args.email)
    for k, v in fields.items():
        conn.execute(f"UPDATE subscriber SET {k} = %s WHERE id = %s", (v, s["id"]))
    return cmd_list(args, cfg, conn)


def cmd_list(args, cfg, conn) -> int:
    for s in conn.execute("SELECT * FROM subscriber ORDER BY id"):
        p = notify.perks(cfg, s["tier"])
        ints = conn.execute("SELECT kind, value FROM interest WHERE subscriber_id = %s ORDER BY kind, value", (s["id"],)).fetchall()
        sent = conn.execute("SELECT count(*) FILTER (WHERE status = 'sent') AS sent, count(*) FILTER (WHERE status = 'queued') "
                            "AS queued FROM delivery WHERE subscriber_id = %s", (s["id"],)).fetchone()
        print(f"{s['email']}  tier={s['tier']} (delay {p['delay_minutes']} min, up to {p['max_interests']} interests)"
              f"{'  PAUSED' if s['paused'] else ''}  sent={sent['sent']} queued={sent['queued']}")
        for i in ints:
            print(f"    {i['kind']}: {i['value']}")
    return 0


def cmd_shelves(args, cfg, conn) -> int:
    rows = conn.execute("SELECT s.id, s.name, s.aisle, s.role, coalesce(w.watching, 0) AS watching FROM shelf s "
                        "LEFT JOIN shelf_watchers w ON w.shelf_id = s.id WHERE %s::text IS NULL OR s.aisle = %s "
                        "ORDER BY s.aisle, s.role, s.id", (args.aisle, args.aisle)).fetchall()
    for r in rows:
        print(f"{r['aisle']:<16} {r['role']:<7} {r['id']:<34} {r['watching']:>3} watching  {r['name']}")
    return 0


def cmd_events(args, cfg, conn) -> int:
    for r in conn.execute("SELECT status, count(*) AS n FROM deal_event WHERE at > now() - interval '24 hours' "
                          "GROUP BY 1 ORDER BY 2 DESC"):
        print(f"{r['status']:<12} {r['n']}")
    print()
    for r in conn.execute("SELECT e.id, e.at, e.kind, e.status, e.why, e.shelf, e.score, w.title FROM deal_event e "
                          "JOIN watch w USING (asin) ORDER BY e.id DESC LIMIT %s", (args.limit,)):
        print(f"{r['id']:>6} {r['at']:%m-%d %H:%M} {r['kind']:<7} {r['status']:<11} {r['why'] or r['shelf'] or '':<26} "
              f"{r['score'] if r['score'] is not None else '':>2} {(r['title'] or '')[:60]}")
    return 0


def cmd_test_email(args, cfg, conn) -> int:
    send, how = notifier.make_sender()
    item = {"title": "Test deal: fiftyoff notifications", "strict": 0.55, "cond": "Used - Like New",
            "resale_cents": 4999, "shelf": "headphones-earbuds", "shelf_name": "headphones & earbuds"}
    subject, text, html = notify.render([item], cfg)
    send({"address": args.email, "endpoint_kind": "email"}, "[test] " + subject, text, html)
    print(f"sent via {how}")
    return 0


def cmd_run(args, cfg, conn) -> int:
    conn.execute(SCHEMA)  # idempotent; the tables may not exist yet if the tracker hasn't restarted since a deploy
    send, how = notifier.make_sender()
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] notifier up, rules {notify.RULES_VERSION}, "
          f"sender: {how}, tiers: {cfg.tiers}", flush=True)
    notifier.run(notifier.PgNotify(os.environ.get("DATABASE_URL", DEFAULT_DSN)), send, cfg, once=args.once,
                 log=lambda m: print(m, flush=True))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="preflight.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("subscribe")
    s.add_argument("email")
    s.add_argument("--shelf", action="append", default=[])
    s.add_argument("--aisle", action="append", default=[])
    s.add_argument("--tier")
    s.add_argument("--force", action="store_true")
    u = sub.add_parser("unwatch")
    u.add_argument("email")
    u.add_argument("--shelf", action="append", default=[])
    u.add_argument("--aisle", action="append", default=[])
    t = sub.add_parser("tier")
    t.add_argument("email")
    t.add_argument("tier")
    for name in ("pause", "resume"):
        sub.add_parser(name).add_argument("email")
    sub.add_parser("list")
    sub.add_parser("shelves").add_argument("--aisle")
    sub.add_parser("events").add_argument("--limit", type=int, default=30)
    sub.add_parser("test-email").add_argument("email")
    sub.add_parser("run").add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    cfg = notify.NotifyConfig.from_toml(preflight.load_config(Path(args.config)))
    conn = connect()
    if args.cmd == "tier":
        return cmd_set(args, cfg, conn, tier=args.tier)
    if args.cmd in ("pause", "resume"):
        return cmd_set(args, cfg, conn, paused=args.cmd == "pause")
    return {"subscribe": cmd_subscribe, "unwatch": cmd_unwatch, "list": cmd_list, "shelves": cmd_shelves,
            "events": cmd_events, "test-email": cmd_test_email, "run": cmd_run}[args.cmd](args, cfg, conn)


if __name__ == "__main__":
    raise SystemExit(main())
