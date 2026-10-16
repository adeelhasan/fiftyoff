"""Keyword alerts (k0.1, docs/handoffs/alerts-beta.md): manage subscribers by hand, and run the notifier.

People sign up on the site (/api/v1/watch). This CLI is for testing and support, on the VPS, e.g.
    docker compose run --rm app notify.py subscribe you@example.com --keyword dyson   # verified and armed now
    docker compose run --rm app notify.py list
    docker compose run --rm app notify.py unwatch you@example.com --keyword dyson     # stops it
    docker compose run --rm app notify.py tier you@example.com plus      # tiers and their perks: [tiers.*] in preflight.toml
    docker compose run --rm app notify.py pause you@example.com           # or resume
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
from fiftyoff import mail, notify, notifier
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
    kws = [notify.keyword(k) for k in args.keyword]
    if not kws or None in kws:
        raise SystemExit("give one or more --keyword (2-40 characters)")
    s = conn.execute("INSERT INTO subscriber (email, tier, verified_at) VALUES (%s, %s, now()) ON CONFLICT (email) "
                     "DO UPDATE SET verified_at = coalesce(subscriber.verified_at, now()) RETURNING *",
                     (email, args.tier or "free")).fetchone()
    conn.execute("INSERT INTO endpoint (subscriber_id, kind, address) VALUES (%s, 'email', %s) ON CONFLICT (kind, address) "
                 "DO UPDATE SET disabled_at = NULL, failures = 0", (s["id"], email))
    if args.tier:
        conn.execute("UPDATE subscriber SET tier = %s WHERE id = %s", (args.tier, s["id"]))
    for k in kws:
        conn.execute("INSERT INTO interest (subscriber_id, kind, value, state, armed_at, source) "
                     "VALUES (%s, 'keyword', %s, 'watching', now(), 'cli') ON CONFLICT (subscriber_id, kind, value) "
                     "DO UPDATE SET state = 'watching', armed_at = now(), ended_at = NULL", (s["id"], k))
    have = conn.execute("SELECT count(*) AS n FROM interest WHERE subscriber_id = %s AND state = 'watching'",
                        (s["id"],)).fetchone()["n"]
    cap = notify.perks(cfg, args.tier or s["tier"])["max_interests"]
    if have > cap:
        print(f"note: tier '{args.tier or s['tier']}' allows {cap} alerts; this one has {have} (kept: the CLI doesn't enforce it)")
    return cmd_list(args, cfg, conn)


def cmd_unwatch(args, cfg, conn) -> int:
    s = _subscriber(conn, args.email)
    for k in args.keyword:
        conn.execute("UPDATE interest SET state = 'stopped', ended_at = now() WHERE subscriber_id = %s AND kind = 'keyword' "
                     "AND value = %s", (s["id"], notify.keyword(k)))
    return cmd_list(args, cfg, conn)


def cmd_set(args, cfg, conn, **fields) -> int:
    s = _subscriber(conn, args.email)
    for k, v in fields.items():
        conn.execute(f"UPDATE subscriber SET {k} = %s WHERE id = %s", (v, s["id"]))
    return cmd_list(args, cfg, conn)


def cmd_list(args, cfg, conn) -> int:
    for s in conn.execute("SELECT * FROM subscriber ORDER BY id"):
        p = notify.perks(cfg, s["tier"])
        ints = conn.execute("SELECT id, kind, value, state, armed_at, source FROM interest WHERE subscriber_id = %s "
                            "ORDER BY id", (s["id"],)).fetchall()
        sent = conn.execute("SELECT count(*) FILTER (WHERE status = 'sent') AS sent, count(*) FILTER (WHERE status = 'queued') "
                            "AS queued, count(*) FILTER (WHERE status = 'stale') AS missed FROM delivery "
                            "WHERE subscriber_id = %s", (s["id"],)).fetchone()
        print(f"{s['email']}  tier={s['tier']} (delay {p['delay_minutes']} min, up to {p['max_interests']} alerts"
              f"{', one-shot' if p['one_shot'] else ''})"
              f"{'  PAUSED' if s['paused'] else ''}{'' if s['verified_at'] else '  UNVERIFIED'}"
              f"  sent={sent['sent']} queued={sent['queued']} missed={sent['missed']}")
        for i in ints:
            armed = f" armed {i['armed_at']:%m-%d %H:%M}" if i["armed_at"] else ""
            print(f"    #{i['id']} {i['kind']}: {i['value']}  [{i['state']}]{armed}  from {i['source'] or '-'}")
    return 0


def cmd_events(args, cfg, conn) -> int:
    for r in conn.execute("SELECT status, count(*) AS n FROM deal_event WHERE at > now() - interval '24 hours' "
                          "GROUP BY 1 ORDER BY 2 DESC"):
        print(f"{r['status']:<12} {r['n']}")
    print()
    for r in conn.execute("SELECT e.id, e.at, e.kind, e.status, e.why, e.score, w.title FROM deal_event e "
                          "JOIN watch w USING (asin) ORDER BY e.id DESC LIMIT %s", (args.limit,)):
        print(f"{r['id']:>6} {r['at']:%m-%d %H:%M} {r['kind']:<7} {r['status']:<11} {r['why'] or '':<26} "
              f"{r['score'] if r['score'] is not None else '':>2} {(r['title'] or '')[:60]}")
    return 0


def cmd_test_email(args, cfg, conn) -> int:
    send, how = mail.make_sender()
    send(args.email, mail.test_mail())
    print(f"sent via {how}")
    return 0


def cmd_run(args, cfg, conn) -> int:
    conn.execute(SCHEMA)  # idempotent; the tables may not exist yet if the tracker hasn't restarted since a deploy
    send, how = mail.make_sender()
    links = notifier.links_from_env(cfg)
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] notifier up, rules {notify.RULES_VERSION}, "
          f"sender: {how}, links: {links.site}, tiers: {cfg.tiers}", flush=True)
    notifier.run(notifier.PgNotify(os.environ.get("DATABASE_URL", DEFAULT_DSN)), send, cfg, links, once=args.once,
                 log=lambda m: print(m, flush=True))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="preflight.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("subscribe")
    s.add_argument("email")
    s.add_argument("--keyword", action="append", default=[])
    s.add_argument("--tier")
    u = sub.add_parser("unwatch")
    u.add_argument("email")
    u.add_argument("--keyword", action="append", default=[])
    t = sub.add_parser("tier")
    t.add_argument("email")
    t.add_argument("tier")
    for name in ("pause", "resume"):
        sub.add_parser(name).add_argument("email")
    sub.add_parser("list")
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
    return {"subscribe": cmd_subscribe, "unwatch": cmd_unwatch, "list": cmd_list,
            "events": cmd_events, "test-email": cmd_test_email, "run": cmd_run}[args.cmd](args, cfg, conn)


if __name__ == "__main__":
    raise SystemExit(main())
