"""The notifier service: the Postgres store for fiftyoff/notify.py (keyword alerts, k0.1) and the loop.

    docker compose up -d notifier     # runs `notify.py run`

Email goes out through fiftyoff/mail.py: SMTP (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM in .env)
or, without SMTP_HOST, a log line. Links in emails are signed with SECRET_KEY (.env).
No model and no Keepa call here: the notifier reads what the tracker and the rater stored.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Callable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from . import mail, notify
from .api_v1 import slug
from .score import image_url

APPEAL_MODEL = "sonnet"  # the feed's appeal model (api.APPEAL_MODEL)

EVENT_COLS = """e.id, e.at, e.kind, e.status, e.asin, e.offer_id, u.state, u.strict_last AS strict, u.ref_last_cents AS ref_cents,
  u.cond, u.last_price_cents AS resale_cents, u.keepa_first_seen_at, u.first_seen_at, u.appeared_after_at,
  w.created_at AS priced_at, w.parent_asin, w.title, p.brand,
  EXISTS (SELECT 1 FROM unlisted x WHERE x.asin = e.asin) AS unlisted"""


class PgNotify:
    def __init__(self, dsn: str):
        self.conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    def _all(self, sql: str, args=()) -> list[dict]:
        return self.conn.execute(sql, args).fetchall()

    def open_events(self) -> list[dict]:
        return self._all(f"SELECT {EVENT_COLS} FROM deal_event e JOIN units u USING (asin, offer_id) JOIN watch w USING (asin) "
                         "LEFT JOIN product p ON p.asin = e.asin "
                         "WHERE e.status IN ('new', 'waiting') ORDER BY e.id LIMIT 500")

    def appeal(self, keys):
        return {r["key"]: r for r in self._all("SELECT key, score FROM appeal WHERE model = %s AND key = ANY(%s)",
                                               (APPEAL_MODEL, keys))}

    def set_event(self, event_id, status, d):
        self.conn.execute("UPDATE deal_event SET status = %s, why = %s, product_key = %s, score = %s, rules_v = %s, "
                          "decided_at = now() WHERE id = %s",
                          (status, d.get("why"), d.get("product_key"), d.get("score"), d.get("rules_v"), event_id))

    def audience(self):
        """Verified, unpaused subscribers' watching keyword alerts, with their email endpoint."""
        return self._all(
            "SELECT s.id AS subscriber_id, s.tier, e.id AS endpoint_id, i.id AS interest_id, i.value AS keyword, i.armed_at "
            "FROM subscriber s JOIN endpoint e ON e.subscriber_id = s.id AND e.disabled_at IS NULL AND e.kind = 'email' "
            "JOIN interest i ON i.subscriber_id = s.id AND i.kind = 'keyword' AND i.state = 'watching' "
            "WHERE NOT s.paused AND s.verified_at IS NOT NULL ORDER BY i.id")

    def windows(self):
        return {r["interest_id"]: r["at"] for r in self._all(
            "SELECT interest_id, min(deliver_at) AS at FROM delivery WHERE status = 'queued' AND interest_id IS NOT NULL "
            "GROUP BY interest_id")}

    def recent(self, since):
        return {(r["subscriber_id"], r["product_key"]) for r in self._all(
            "SELECT DISTINCT subscriber_id, product_key FROM delivery WHERE deliver_at > %s AND status IN ('queued', 'sent')",
            (since,))}

    def add_deliveries(self, rows):
        if rows:
            with self.conn.cursor() as cur:
                cur.executemany("INSERT INTO delivery (event_id, subscriber_id, endpoint_id, interest_id, product_key, deliver_at) "
                                "VALUES (%(event_id)s, %(subscriber_id)s, %(endpoint_id)s, %(interest_id)s, %(product_key)s, "
                                "%(deliver_at)s) ON CONFLICT (endpoint_id, event_id) DO NOTHING", rows)

    def due(self, now):
        rows = self._all(
            "SELECT d.id, d.subscriber_id, d.endpoint_id, d.interest_id, p.address, s.tier, s.paused, "
            "i.value AS keyword, i.state AS interest_state, ev.at, ev.asin, "
            "u.state, u.strict_last AS strict, u.cond, u.last_price_cents AS resale_cents, u.ref_last_cents AS ref_cents, "
            "w.title, w.image, EXISTS (SELECT 1 FROM unlisted x WHERE x.asin = ev.asin) AS unlisted "
            "FROM delivery d JOIN endpoint p ON p.id = d.endpoint_id JOIN subscriber s ON s.id = d.subscriber_id "
            "JOIN interest i ON i.id = d.interest_id JOIN deal_event ev ON ev.id = d.event_id "
            "JOIN units u ON (u.asin, u.offer_id) = (ev.asin, ev.offer_id) JOIN watch w ON w.asin = ev.asin "
            "WHERE d.status = 'queued' AND d.deliver_at <= %s AND p.disabled_at IS NULL ORDER BY d.id", (now,))
        return [{**r, "slug": slug(r["asin"], r["title"]), "image": image_url(r["image"])} for r in rows]

    def mark(self, ids, status, error=None):
        self.conn.execute("UPDATE delivery SET status = %s, error = %s, sent_at = CASE WHEN %s = 'sent' THEN now() END "
                          "WHERE id = ANY(%s)", (status, error, status, ids))

    def end_interest(self, interest_id, state, now):
        self.conn.execute("UPDATE interest SET state = %s, ended_at = %s WHERE id = %s AND state = 'watching'",
                          (state, now, interest_id))
        self.conn.execute("UPDATE delivery SET status = 'dropped' WHERE interest_id = %s AND status = 'queued'", (interest_id,))

    def armed_before(self, t):
        return self._all(
            "SELECT i.id AS interest_id, i.subscriber_id, i.value AS keyword, i.armed_at, s.tier, s.paused, "
            "(SELECT e.address FROM endpoint e WHERE e.subscriber_id = s.id AND e.kind = 'email' AND e.disabled_at IS NULL "
            " LIMIT 1) AS address "
            "FROM interest i JOIN subscriber s ON s.id = i.subscriber_id "
            "WHERE i.kind = 'keyword' AND i.state = 'watching' AND i.armed_at < %s", (t,))

    def endpoint_result(self, endpoint_id, ok):
        if ok:
            self.conn.execute("UPDATE endpoint SET failures = 0, last_ok_at = now() WHERE id = %s", (endpoint_id,))
        else:  # five failures in a row disable the address
            self.conn.execute("UPDATE endpoint SET failures = failures + 1, disabled_at = CASE WHEN failures + 1 >= 5 "
                              "THEN now() END WHERE id = %s", (endpoint_id,))

    def heartbeat(self, value: dict) -> None:
        self.conn.execute("INSERT INTO tracker_state VALUES ('notifier', %s) ON CONFLICT (key) DO UPDATE SET value = "
                          "EXCLUDED.value", (Json(value),))


def links_from_env(cfg: notify.NotifyConfig, env=os.environ) -> mail.Links:
    key = env.get("SECRET_KEY") or ""
    if not key:
        raise SystemExit("SECRET_KEY is not set in .env: email links can't be signed")
    return mail.Links(cfg.site.rstrip("/"), key)


# ---------------------------------------------------------------- loop

def run(store: PgNotify, send: mail.Sender, cfg: notify.NotifyConfig, links: mail.Links, once: bool = False,
        log: Callable[[str], None] = print) -> None:
    while True:
        now = datetime.now(timezone.utc)
        try:
            counts = notify.advance(store, now, cfg)
            sent = notify.send_due(store, send, now, cfg, links, log)
            expired = notify.expire(store, send, now, cfg, links, log)
            if counts or sent or expired:
                log(f"[{now.isoformat(timespec='seconds')}] events {counts or '-'}, emails sent {sent}, expired {expired}")
            store.heartbeat({"at": now.timestamp(), "events": counts, "sent": sent, "expired": expired})
        except psycopg.Error as e:  # a DB hiccup must not kill the service; the next pass retries
            log(f"  notifier pass failed: {e!r}")
        if once:
            return
        time.sleep(cfg.poll_seconds)
