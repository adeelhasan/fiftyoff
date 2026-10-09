"""The notifier service: Postgres store for fiftyoff/notify.py, the email senders, and the loop.

    docker compose up -d notifier     # runs `notify.py run`

Email goes out over SMTP (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM in .env); Resend, Postmark
and a mailbox with an app password all speak it. Without SMTP_HOST the notifier only logs what it would send.
No model and no Keepa call here: the notifier reads what the tracker and the rater stored.
"""

from __future__ import annotations

import os
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Callable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from . import notify

APPEAL_MODEL = "sonnet"  # the feed's appeal model (api.APPEAL_MODEL)

EVENT_COLS = """e.id, e.at, e.kind, e.status, e.asin, e.offer_id, u.state, u.strict_last AS strict, u.ref_last_cents AS ref_cents,
  u.cond, u.last_price_cents AS resale_cents, u.keepa_first_seen_at, u.first_seen_at, u.appeared_after_at,
  w.created_at AS priced_at, w.parent_asin, w.title,
  EXISTS (SELECT 1 FROM unlisted x WHERE x.asin = e.asin) AS unlisted"""


class PgNotify:
    def __init__(self, dsn: str):
        self.conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    def _all(self, sql: str, args=()) -> list[dict]:
        return self.conn.execute(sql, args).fetchall()

    def open_events(self) -> list[dict]:
        return self._all(f"SELECT {EVENT_COLS} FROM deal_event e JOIN units u USING (asin, offer_id) JOIN watch w USING (asin) "
                         "WHERE e.status IN ('new', 'waiting') ORDER BY e.id LIMIT 500")

    def appeal(self, keys):
        return {r["key"]: r for r in self._all("SELECT key, score, shelf, kind, aisle FROM appeal "
                                               "WHERE model = %s AND key = ANY(%s)", (APPEAL_MODEL, keys))}

    def shelves(self):
        return {r["id"]: r for r in self._all("SELECT id, name, aisle, role FROM shelf")}

    def kind_map(self):
        return {r["kind"]: r["shelf"] for r in self._all("SELECT kind, shelf FROM kind_map")}

    def set_event(self, event_id, status, d):
        self.conn.execute("UPDATE deal_event SET status = %s, why = %s, product_key = %s, shelf = %s, aisle = %s, "
                          "score = %s, rules_v = %s, decided_at = now() WHERE id = %s",
                          (status, d.get("why"), d.get("product_key"), d.get("shelf"), d.get("aisle"), d.get("score"),
                           d.get("rules_v"), event_id))

    def audience(self):
        rows = self._all(
            "SELECT s.id AS subscriber_id, s.tier, e.id AS endpoint_id, "
            "array_agg(ARRAY[i.kind, i.value]) AS interests FROM subscriber s "
            "JOIN endpoint e ON e.subscriber_id = s.id AND e.disabled_at IS NULL AND e.kind = 'email' "
            "JOIN interest i ON i.subscriber_id = s.id WHERE NOT s.paused GROUP BY s.id, s.tier, e.id")
        return [{**r, "interests": [tuple(x) for x in r["interests"]]} for r in rows]

    def recent(self, since):
        return {(r["subscriber_id"], r["product_key"]) for r in self._all(
            "SELECT DISTINCT subscriber_id, product_key FROM delivery WHERE deliver_at > %s AND status IN ('queued', 'sent')",
            (since,))}

    def add_deliveries(self, rows):
        if rows:
            with self.conn.cursor() as cur:
                cur.executemany("INSERT INTO delivery (event_id, subscriber_id, endpoint_id, product_key, deliver_at) "
                                "VALUES (%(event_id)s, %(subscriber_id)s, %(endpoint_id)s, %(product_key)s, %(deliver_at)s) "
                                "ON CONFLICT (endpoint_id, event_id) DO NOTHING", rows)

    def due(self, now):
        return self._all(
            "SELECT d.id, d.endpoint_id, p.kind AS endpoint_kind, p.address, ev.shelf, s.name AS shelf_name, "
            "u.state, u.strict_last AS strict, u.cond, u.last_price_cents AS resale_cents, w.title, "
            "EXISTS (SELECT 1 FROM unlisted x WHERE x.asin = ev.asin) AS unlisted "
            "FROM delivery d JOIN endpoint p ON p.id = d.endpoint_id JOIN deal_event ev ON ev.id = d.event_id "
            "JOIN units u ON (u.asin, u.offer_id) = (ev.asin, ev.offer_id) JOIN watch w ON w.asin = ev.asin "
            "LEFT JOIN shelf s ON s.id = ev.shelf "
            "WHERE d.status = 'queued' AND d.deliver_at <= %s AND p.disabled_at IS NULL ORDER BY d.id", (now,))

    def mark(self, ids, status, error=None):
        self.conn.execute("UPDATE delivery SET status = %s, error = %s, sent_at = CASE WHEN %s = 'sent' THEN now() END "
                          "WHERE id = ANY(%s)", (status, error, status, ids))

    def endpoint_result(self, endpoint_id, ok):
        if ok:
            self.conn.execute("UPDATE endpoint SET failures = 0, last_ok_at = now() WHERE id = %s", (endpoint_id,))
        else:  # five failures in a row disable the address
            self.conn.execute("UPDATE endpoint SET failures = failures + 1, disabled_at = CASE WHEN failures + 1 >= 5 "
                              "THEN now() END WHERE id = %s", (endpoint_id,))

    def heartbeat(self, value: dict) -> None:
        self.conn.execute("INSERT INTO tracker_state VALUES ('notifier', %s) ON CONFLICT (key) DO UPDATE SET value = "
                          "EXCLUDED.value", (Json(value),))


# ---------------------------------------------------------------- senders

def smtp_sender(env=os.environ) -> notify.Sender:
    host, port = env["SMTP_HOST"], int(env.get("SMTP_PORT") or 587)
    user, password, sender = env.get("SMTP_USER"), env.get("SMTP_PASSWORD"), env.get("MAIL_FROM") or env.get("SMTP_USER")

    def send(endpoint: dict, subject: str, text: str, html: str) -> None:
        if endpoint.get("endpoint_kind", "email") != "email":
            raise ValueError(f"no sender for {endpoint.get('endpoint_kind')}")
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = sender, endpoint["address"], subject
        m.set_content(text)
        m.add_alternative(html, subtype="html")
        with (smtplib.SMTP_SSL(host, port, timeout=30) if port == 465 else smtplib.SMTP(host, port, timeout=30)) as s:
            if port != 465:
                s.starttls()
            if user:
                s.login(user, password or "")
            s.send_message(m)
    return send


def log_sender(log: Callable[[str], None] = print) -> notify.Sender:
    def send(endpoint: dict, subject: str, text: str, html: str) -> None:
        log(f"[log only] to {endpoint['address']}: {subject}\n{text}")
    return send


def make_sender(env=os.environ, log: Callable[[str], None] = print) -> tuple[notify.Sender, str]:
    return (smtp_sender(env), "smtp") if env.get("SMTP_HOST") else (log_sender(log), "log only")


# ---------------------------------------------------------------- loop

def run(store: PgNotify, send: notify.Sender, cfg: notify.NotifyConfig, once: bool = False,
        log: Callable[[str], None] = print) -> None:
    while True:
        now = datetime.now(timezone.utc)
        try:
            counts = notify.advance(store, now, cfg)
            sent = notify.send_due(store, send, now, cfg, log)
            if counts or sent:
                log(f"[{now.isoformat(timespec='seconds')}] events {counts or '-'}, messages sent {sent}")
            store.heartbeat({"at": now.timestamp(), "events": counts, "sent": sent})
        except psycopg.Error as e:  # a DB hiccup must not kill the service; the next pass retries
            log(f"  notifier pass failed: {e!r}")
        if once:
            return
        time.sleep(cfg.poll_seconds)
