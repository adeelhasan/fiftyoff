"""Postgres Store for the tracker. Raw Keepa responses on disk stay the source of truth (rule 4/8);
these tables are derived state that can be rebuilt from them.

Public-display columns are only those Keepa consented to (D19), exposed through the `feed` view.
Everything else (reference price, rank, history) stays internal until Keepa's follow-up answer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import psycopg

from .tracker import Unit, Watch

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracker_state (key text PRIMARY KEY, value jsonb NOT NULL);

CREATE TABLE IF NOT EXISTS watch (
  asin text PRIMARY KEY, parent_asin text, title text, category text, rank int, image text,
  added_at timestamptz NOT NULL, last_check_at timestamptz, last_qualifying_at timestamptz,
  retired_at timestamptz, created_at timestamptz, ok_checks int NOT NULL DEFAULT 0
);
ALTER TABLE watch ADD COLUMN IF NOT EXISTS created_at timestamptz;
ALTER TABLE watch ADD COLUMN IF NOT EXISTS ok_checks int NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS sweep_rows (
  id bigserial PRIMARY KEY, swept_at timestamptz NOT NULL, asin text NOT NULL, parent_asin text,
  category text, title text, resale_cents int, ref_cents int, strict real, keepa_pct int,
  cond text, comment text, rank int, creation_kmin int, image text, qualifies bool, formula text
);
CREATE INDEX IF NOT EXISTS sweep_rows_asin ON sweep_rows (asin, swept_at);

CREATE TABLE IF NOT EXISTS checks (
  id bigserial PRIMARY KEY, checked_at timestamptz NOT NULL, asin text NOT NULL, offers_ok bool,
  ref_cents int, ref_parts jsonb, best_strict real, tokens int, formula text
);
CREATE INDEX IF NOT EXISTS checks_asin ON checks (asin, checked_at);

CREATE TABLE IF NOT EXISTS check_offers (
  check_id bigint NOT NULL REFERENCES checks(id), offer_id bigint, price_cents int, cond text,
  comment text, strict real
);

CREATE TABLE IF NOT EXISTS units (
  asin text NOT NULL, offer_id bigint NOT NULL, state text NOT NULL,
  first_seen_at timestamptz NOT NULL, appeared_after_at timestamptz, last_seen_at timestamptz NOT NULL,
  absent_since_at timestamptz, gone_at timestamptz, first_price_cents int, last_price_cents int,
  cond text, comment text, strict_first real, strict_last real, ref_last_cents int,
  revivals int NOT NULL DEFAULT 0, checks_seen int NOT NULL DEFAULT 0, keepa_first_seen_at timestamptz,
  PRIMARY KEY (asin, offer_id)
);
ALTER TABLE units ADD COLUMN IF NOT EXISTS keepa_first_seen_at timestamptz;

-- Demand signals for the internal deal score (D28). Never exposed by the API (D19).
CREATE TABLE IF NOT EXISTS product (
  asin text PRIMARY KEY, brand text, cat_path text[], reviews int, rating real, drops30 int, drops90 int,
  monthly_sold int, amazon_sells bool, rank int, updated_at timestamptz NOT NULL
);

-- Public deal feed: D19-consented columns only (title, link, our % off, condition, current Resale
-- price) plus our own "last confirmed" time. Show with a "Data by Keepa" link to keepa.com.
CREATE OR REPLACE VIEW feed AS
SELECT u.asin, w.title, w.category, w.image, u.cond, u.last_price_cents AS resale_cents,
       round((u.strict_last * 100)::numeric) AS pct_off, u.last_seen_at AS last_confirmed_at,
       u.state = 'unconfirmed' AS unconfirmed,
       'https://www.amazon.com/dp/' || u.asin || '?aod=1' AS url
FROM units u JOIN watch w USING (asin)
WHERE u.state <> 'gone' AND w.retired_at IS NULL
  -- tiers mirror TrackerConfig.tiers (preflight.toml [tracker]); keep in sync
  AND ((u.strict_last >= 0.40 AND u.ref_last_cents >= 10000) OR (u.strict_last >= 0.30 AND u.ref_last_cents >= 20000));

-- Internal views the API reads (as feed_reader) to score, group and filter. They carry signals the
-- API must not emit (reference price, reviews, rank...): fiftyoff/api.py picks the public fields.
CREATE OR REPLACE VIEW deal_internal AS
SELECT u.asin, u.offer_id, w.title, w.category, w.image, u.cond, u.last_price_cents AS resale_cents,
       u.ref_last_cents AS ref_cents, u.strict_last AS strict, u.last_seen_at AS last_confirmed_at,
       u.state = 'unconfirmed' AS unconfirmed, u.keepa_first_seen_at, u.first_seen_at,
       p.brand, p.cat_path, p.reviews, p.rating, p.drops30, p.monthly_sold, p.amazon_sells, p.rank,
       w.created_at AS priced_at  -- Keepa's creationDate: when the deal's current Resale price was set
FROM units u JOIN watch w USING (asin) LEFT JOIN product p USING (asin)
WHERE u.state <> 'gone' AND w.retired_at IS NULL AND ((u.strict_last >= 0.40 AND u.ref_last_cents >= 10000) OR (u.strict_last >= 0.30 AND u.ref_last_cents >= 20000));

-- Recently gone qualifying units, retired watches included (D27: shown with their last price).
CREATE OR REPLACE VIEW gone_internal AS
SELECT u.asin, u.offer_id, w.title, w.category, w.image, u.cond, u.last_price_cents AS resale_cents,
       u.ref_last_cents AS ref_cents, u.strict_last AS strict, u.last_seen_at, u.gone_at,
       p.brand, p.cat_path, p.reviews, p.rating, p.drops30, p.monthly_sold, p.amazon_sells, p.rank,
       u.first_seen_at, u.appeared_after_at, u.keepa_first_seen_at, u.absent_since_at, u.revivals
FROM units u JOIN watch w USING (asin) LEFT JOIN product p USING (asin)
WHERE u.state = 'gone' AND u.gone_at > now() - interval '7 days' AND ((u.strict_last >= 0.40 AND u.ref_last_cents >= 10000) OR (u.strict_last >= 0.30 AND u.ref_last_cents >= 20000));
"""


def _ts(t: float | None):
    return None if t is None else datetime.fromtimestamp(t, tz=timezone.utc)


def _f(d: datetime | None) -> float | None:
    return None if d is None else d.timestamp()


class PgStore:
    def __init__(self, dsn: str):
        self.conn = psycopg.connect(dsn, autocommit=True)
        self.conn.execute(SCHEMA)

    def load(self):
        watch, units = {}, {}
        for r in self.conn.execute("SELECT asin, parent_asin, title, category, rank, image, added_at, "
                                   "last_check_at, last_qualifying_at, retired_at, created_at, ok_checks FROM watch"):
            watch[r[0]] = Watch(asin=r[0], parent=r[1], title=r[2], cat=r[3], rank=r[4], image=r[5],
                                added=_f(r[6]), last_check=_f(r[7]) or 0.0, last_qualifying=_f(r[8]),
                                retired=_f(r[9]), created=_f(r[10]), ok_checks=r[11])
        for r in self.conn.execute("SELECT asin, offer_id, state, first_seen_at, appeared_after_at, last_seen_at, "
                                   "absent_since_at, gone_at, first_price_cents, last_price_cents, cond, comment, "
                                   "strict_first, strict_last, ref_last_cents, revivals, checks_seen, keepa_first_seen_at FROM units"):
            units[(r[0], r[1])] = Unit(asin=r[0], offer_id=r[1], state=r[2], first_seen=_f(r[3]),
                                       appeared_after=_f(r[4]), last_seen=_f(r[5]), absent_since=_f(r[6]),
                                       gone_at=_f(r[7]), first_price=r[8], last_price=r[9], cond=r[10],
                                       comment=r[11], strict_first=r[12], strict_last=r[13], ref_last=r[14],
                                       revivals=r[15], checks_seen=r[16], keepa_first_seen=_f(r[17]))
        state = {k: v for k, v in self.conn.execute("SELECT key, value FROM tracker_state")}
        return watch, units, state

    def put_state(self, key, value):
        self.conn.execute("INSERT INTO tracker_state VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = "
                          "EXCLUDED.value", (key, json.dumps(value)))

    def save_watch(self, w: Watch):
        self.conn.execute(
            "INSERT INTO watch (asin, parent_asin, title, category, rank, image, added_at, last_check_at, "
            "last_qualifying_at, retired_at, created_at, ok_checks) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (asin) DO UPDATE SET "
            "parent_asin=EXCLUDED.parent_asin, title=EXCLUDED.title, category=EXCLUDED.category, rank=EXCLUDED.rank, "
            "image=EXCLUDED.image, added_at=EXCLUDED.added_at, last_check_at=EXCLUDED.last_check_at, "
            "last_qualifying_at=EXCLUDED.last_qualifying_at, retired_at=EXCLUDED.retired_at, "
            "created_at=EXCLUDED.created_at, ok_checks=EXCLUDED.ok_checks",
            (w.asin, w.parent, w.title, w.cat, w.rank, w.image, _ts(w.added), _ts(w.last_check or None),
             _ts(w.last_qualifying), _ts(w.retired), _ts(w.created), w.ok_checks))

    def save_unit(self, u: Unit):
        self.conn.execute(
            "INSERT INTO units (asin, offer_id, state, first_seen_at, appeared_after_at, last_seen_at, absent_since_at, "
            "gone_at, first_price_cents, last_price_cents, cond, comment, strict_first, strict_last, ref_last_cents, "
            "revivals, checks_seen, keepa_first_seen_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (asin, offer_id) "
            "DO UPDATE SET state=EXCLUDED.state, last_seen_at=EXCLUDED.last_seen_at, "
            "absent_since_at=EXCLUDED.absent_since_at, gone_at=EXCLUDED.gone_at, "
            "last_price_cents=EXCLUDED.last_price_cents, strict_last=EXCLUDED.strict_last, "
            "ref_last_cents=EXCLUDED.ref_last_cents, revivals=EXCLUDED.revivals, checks_seen=EXCLUDED.checks_seen",
            (u.asin, u.offer_id, u.state, _ts(u.first_seen), _ts(u.appeared_after), _ts(u.last_seen),
             _ts(u.absent_since), _ts(u.gone_at), u.first_price, u.last_price, u.cond, u.comment,
             u.strict_first, u.strict_last, u.ref_last, u.revivals, u.checks_seen, _ts(u.keepa_first_seen)))

    def add_sweep_rows(self, t, rows):
        if not rows:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO sweep_rows (swept_at, asin, parent_asin, category, title, resale_cents, ref_cents, strict, "
                "keepa_pct, cond, comment, rank, creation_kmin, image, qualifies, formula) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(_ts(t), r["asin"], r["parent"], r["cat"], r["title"], r["resale"], r["ref"], r["strict"],
                  r["keepa_pct"], r["cond"], r["comment"], r["rank"], r["creation"], r["image"], r["qualifies"],
                  r["formula"]) for r in rows])

    def save_product(self, t, asin, sig):
        cols = list(sig)
        self.conn.execute(
            f"INSERT INTO product (asin, {', '.join(cols)}, updated_at) VALUES (%s, {', '.join(['%s'] * len(cols))}, %s) "
            f"ON CONFLICT (asin) DO UPDATE SET {', '.join(f'{c} = COALESCE(EXCLUDED.{c}, product.{c})' for c in cols)}, "
            "updated_at = EXCLUDED.updated_at",
            (asin, *sig.values(), _ts(t)))

    def add_check(self, t, check, offers):
        cid = self.conn.execute(
            "INSERT INTO checks (checked_at, asin, offers_ok, ref_cents, ref_parts, best_strict, tokens, formula) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (_ts(t), check["asin"], check["offers_ok"], check["ref"], json.dumps(check["ref_parts"]),
             check["best"], check["tokens"], check["formula"])).fetchone()[0]
        if offers:
            with self.conn.cursor() as cur:
                cur.executemany("INSERT INTO check_offers VALUES (%s,%s,%s,%s,%s,%s)",
                                [(cid, o["offer_id"], o["price"], o["cond"], o["comment"], o["strict"]) for o in offers])
