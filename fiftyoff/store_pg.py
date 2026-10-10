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
-- D34: reference-trust flags (REF_FLAGS_VERSION) and, for deal rows, the reference candidates
ALTER TABLE checks ADD COLUMN IF NOT EXISTS ref_flags jsonb;
ALTER TABLE sweep_rows ADD COLUMN IF NOT EXISTS ref_parts jsonb;
ALTER TABLE sweep_rows ADD COLUMN IF NOT EXISTS ref_flags jsonb;

-- Demand signals for the internal deal score (D28). Never exposed by the API (D19).
CREATE TABLE IF NOT EXISTS product (
  asin text PRIMARY KEY, brand text, cat_path text[], reviews int, rating real, drops30 int, drops90 int,
  monthly_sold int, amazon_sells bool, rank int, updated_at timestamptz NOT NULL
);

-- D35 review hold: the rules' state. pending (held) or cleared (the reasons went away). The user's
-- decisions live in `curation` (D36). decided_at / decided_ref_cents / note are D35 leftovers, kept for history.
CREATE TABLE IF NOT EXISTS review (
  asin text PRIMARY KEY, status text NOT NULL, layer text NOT NULL, reasons jsonb NOT NULL, rules text,
  title text, image text, cond text, resale_cents int, ref_cents int, strict real, ref_flags jsonb, ref_parts jsonb,
  first_held_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
  decided_at timestamptz, decided_ref_cents int, note text
);

-- D36 curation: the admin's decision per ASIN (fiftyoff/curation.py). auto = the rules decide; approved =
-- listed even if held, while the reference stays within 20% of decided_ref_cents; hidden = never listed.
CREATE TABLE IF NOT EXISTS curation (
  asin text PRIMARY KEY, visibility text NOT NULL DEFAULT 'auto' CHECK (visibility IN ('auto', 'approved', 'hidden')),
  tags text[] NOT NULL DEFAULT '{}', note text, decided_ref_cents int,
  updated_at timestamptz NOT NULL, updated_by text NOT NULL
);
-- Append-only: the audit trail, and labelled data for tuning the review rules.
CREATE TABLE IF NOT EXISTS curation_log (
  id bigserial PRIMARY KEY, asin text NOT NULL, field text NOT NULL, old text, new text,
  by text NOT NULL, at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS curation_log_asin ON curation_log (asin, at);

-- D36 migration (a no-op once done): D35 decisions move to curation; review keeps the rules' state only.
INSERT INTO curation_log (asin, field, old, new, by, at)
SELECT asin, 'visibility', 'auto', CASE status WHEN 'approved' THEN 'approved' ELSE 'hidden' END, 'migration',
       coalesce(decided_at, now())
FROM review WHERE status IN ('approved', 'rejected') AND asin NOT IN (SELECT asin FROM curation);
INSERT INTO curation (asin, visibility, note, decided_ref_cents, updated_at, updated_by)
SELECT asin, CASE status WHEN 'approved' THEN 'approved' ELSE 'hidden' END, note,
       CASE status WHEN 'approved' THEN decided_ref_cents END, coalesce(decided_at, now()), 'migration'
FROM review WHERE status IN ('approved', 'rejected')
ON CONFLICT (asin) DO NOTHING;
UPDATE review SET status = CASE WHEN reasons = '[]'::jsonb THEN 'cleared' ELSE 'pending' END
WHERE status IN ('approved', 'rejected');

-- D37 Cloudflare Access users: one row per verified email, upserted as people sign in (throttled).
-- ADMIN_EMAILS (env) are owners: always admin. Role changes from the People tab are logged.
CREATE TABLE IF NOT EXISTS app_user (
  email text PRIMARY KEY CHECK (email = lower(email)),
  role text NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer', 'admin')),
  active bool NOT NULL DEFAULT true, first_seen timestamptz, last_seen timestamptz, note text,
  updated_at timestamptz, updated_by text
);
CREATE TABLE IF NOT EXISTS app_user_log (
  id bigserial PRIMARY KEY, email text NOT NULL, field text NOT NULL, old text, new text,
  by text NOT NULL, at timestamptz NOT NULL
);

-- D42: the model's appeal judgement, one row per product key (parent ASIN, else ASIN) and model. Ours, not Keepa's:
-- derived from the title, brand and category. `prompt_v` is the rubric version (fiftyoff/appeal_rubric.md).
CREATE TABLE IF NOT EXISTS appeal (
  key text NOT NULL, model text NOT NULL, score smallint NOT NULL, tags text[], why text,
  prompt_v text NOT NULL, rated_at timestamptz NOT NULL, PRIMARY KEY (key, model)
);
-- D44 (rubric a0.2): our own shelves. aisle = one of a fixed list, kind = what it is ("robot vacuums"),
-- fit = the buyer's size or fit decides whether it works (clothing, shoes, rings).
ALTER TABLE appeal ADD COLUMN IF NOT EXISTS aisle text;
ALTER TABLE appeal ADD COLUMN IF NOT EXISTS kind text;
ALTER TABLE appeal ADD COLUMN IF NOT EXISTS fit bool;
-- D45: our categorisation v0. Each rater's kind maps to a shelf (what a shopper browses as one row) in one aisle.
CREATE TABLE IF NOT EXISTS kind_map (
  kind text PRIMARY KEY, shelf text NOT NULL, aisle text NOT NULL, version text NOT NULL
);
-- D46: shelves v0.1 with permanent ids and a role: front (home view), aisle (inside its aisle), hidden (only with
-- "show everything"). The model proposes the role; the user's choice (role) overrides it. kind_map.shelf = shelf.id.
CREATE TABLE IF NOT EXISTS shelf (
  id text PRIMARY KEY, name text NOT NULL, aisle text NOT NULL, role text NOT NULL, proposed_role text NOT NULL,
  role_reason text, version text NOT NULL, updated_by text, updated_at timestamptz
);
-- D46 (rubric a0.3): the rater picks the shelf id, and states the size when the title gives one.
ALTER TABLE appeal ADD COLUMN IF NOT EXISTS shelf text;
ALTER TABLE appeal ADD COLUMN IF NOT EXISTS size text;

-- The one listing predicate (mirrors fiftyoff/curation.py `listed`): an ASIN is out of every feed view when
-- hidden, or held by the rules without an approval whose reference is still within 20% (REVIEW_REOPEN;
-- keep in sync). No baseline (decided_ref_cents NULL) fails closed.
CREATE OR REPLACE VIEW unlisted AS
SELECT asin, 'hidden' AS why FROM curation WHERE visibility = 'hidden'
UNION ALL
SELECT r.asin, CASE WHEN c.visibility = 'approved' THEN 'approval_lapsed' ELSE 'held' END
FROM review r LEFT JOIN curation c USING (asin)
WHERE r.status = 'pending' AND coalesce(c.visibility, 'auto') <> 'hidden'
  -- coalesce: no curation row or no baseline gives NULL, which must count as "not approved", not drop the row
  AND NOT coalesce(c.visibility = 'approved' AND c.decided_ref_cents > 0 AND r.ref_cents > 0
                   AND abs(r.ref_cents - c.decided_ref_cents)::real / c.decided_ref_cents <= 0.20, false);

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
  AND ((u.strict_last >= 0.40 AND u.ref_last_cents >= 10000) OR (u.strict_last >= 0.30 AND u.ref_last_cents >= 20000))
  AND NOT EXISTS (SELECT 1 FROM unlisted x WHERE x.asin = u.asin);  -- D36

-- Internal views the API reads (as feed_reader) to score, group and filter. They carry signals the
-- API must not emit (reference price, reviews, rank...): fiftyoff/api.py picks the public fields.
CREATE OR REPLACE VIEW deal_internal AS
SELECT u.asin, u.offer_id, w.title, w.category, w.image, u.cond, u.last_price_cents AS resale_cents,
       u.ref_last_cents AS ref_cents, u.strict_last AS strict, u.last_seen_at AS last_confirmed_at,
       u.state = 'unconfirmed' AS unconfirmed, u.keepa_first_seen_at, u.first_seen_at,
       p.brand, p.cat_path, p.reviews, p.rating, p.drops30, p.monthly_sold, p.amazon_sells, p.rank,
       w.created_at AS priced_at,  -- Keepa's creationDate: when the deal's current Resale price was set
       w.parent_asin,  -- D39: cards group variants by parent
       (SELECT k.ref_flags FROM checks k WHERE k.asin = u.asin AND k.offers_ok
        ORDER BY k.checked_at DESC LIMIT 1) AS ref_flags,  -- 10-06: list price for the inversion test
       (SELECT count(*) FROM units v WHERE v.asin = u.asin AND v.state <> 'gone') AS resale_live  -- flip estimate
FROM units u JOIN watch w USING (asin) LEFT JOIN product p USING (asin)
WHERE u.state <> 'gone' AND w.retired_at IS NULL AND ((u.strict_last >= 0.40 AND u.ref_last_cents >= 10000) OR (u.strict_last >= 0.30 AND u.ref_last_cents >= 20000))
  AND NOT EXISTS (SELECT 1 FROM unlisted x WHERE x.asin = u.asin);  -- D36

-- D32 census: supply in other categories, sweep-only (no watches, no checks).
CREATE TABLE IF NOT EXISTS census_rows (
  id bigserial PRIMARY KEY, swept_at timestamptz NOT NULL, cat_id bigint NOT NULL, asin text NOT NULL,
  parent_asin text, category text, title text, resale_cents int, ref_cents int, strict real, keepa_pct int,
  cond text, rank int, creation_kmin int, qualifies bool, formula text
);
CREATE INDEX IF NOT EXISTS census_rows_cat ON census_rows (cat_id, swept_at);
ALTER TABLE census_rows ADD COLUMN IF NOT EXISTS image text;
ALTER TABLE census_rows ADD COLUMN IF NOT EXISTS ref_parts jsonb;
ALTER TABLE census_rows ADD COLUMN IF NOT EXISTS ref_flags jsonb;

-- D39: leaf subcategory ids and 30-day sales-rank drops from each deal-feed object, and the node names.
ALTER TABLE sweep_rows ADD COLUMN IF NOT EXISTS cats bigint[];
ALTER TABLE sweep_rows ADD COLUMN IF NOT EXISTS drops30 int;
ALTER TABLE census_rows ADD COLUMN IF NOT EXISTS cats bigint[];
ALTER TABLE census_rows ADD COLUMN IF NOT EXISTS drops30 int;
ALTER TABLE sweep_rows ADD COLUMN IF NOT EXISTS qualify_v text;  -- tracker.QUALIFY_VERSION (rule 8); NULL = before q0.3
CREATE TABLE IF NOT EXISTS cat_node (
  id bigint PRIMARY KEY, name text, parent_id bigint, updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS sweep_rows_swept ON sweep_rows (swept_at);
CREATE INDEX IF NOT EXISTS census_rows_swept ON census_rows (swept_at);

-- D39 seen-in-feed layer: each ASIN's LATEST feed sighting in 7 days, kept only if that sighting is still a
-- deal. Seen in Keepa's deal feed at swept_at, never live-checked (the API drops ASINs it live-checks, and
-- shows a 36 h window by default, 7 days in "Seen only"). Shaped like deal_internal, plus parent, leaf
-- subcategories and reference flags. Holds don't apply here (the flags show on the card); hidden does (D36).
-- Census (D33/D38): its own qualification (rank limit per category, Like New clothing).
CREATE OR REPLACE VIEW census_deal AS
WITH c AS (SELECT DISTINCT ON (asin) * FROM census_rows WHERE swept_at > now() - interval '7 days'
           ORDER BY asin, swept_at DESC, id DESC)
SELECT c.asin, NULL::bigint AS offer_id, c.title, c.category, c.image, c.cond, c.resale_cents, c.ref_cents,
       c.strict, c.swept_at AS last_confirmed_at, false AS unconfirmed,
       NULL::timestamptz AS keepa_first_seen_at, NULL::timestamptz AS first_seen_at,
       NULL::text AS brand, NULL::text[] AS cat_path, NULL::int AS reviews, NULL::real AS rating,
       c.drops30, NULL::int AS monthly_sold, NULL::bool AS amazon_sells, c.rank,
       to_timestamp((c.creation_kmin + 21564000) * 60.0) AS priced_at, c.cat_id,
       c.parent_asin, c.cats, c.ref_flags,
       ((c.strict >= 0.40 AND c.ref_cents >= 10000) OR (c.strict >= 0.30 AND c.ref_cents >= 20000)) AS in_tiers
FROM c
-- D39 (10-06): seeing has no rank limit here either (Clothing had 486 Like New 50%+ deals in a week, 22 within
-- 50k). Tiers mirror TrackerConfig.tiers; the Clothing condition rule mirrors CENSUS_CONDS (D38).
-- D46: plus 50%+ from a $40 reference for the shelves page; the main feed keeps `in_tiers` rows only.
WHERE ((c.strict >= 0.40 AND c.ref_cents >= 10000) OR (c.strict >= 0.30 AND c.ref_cents >= 20000)
       OR (c.strict >= 0.50 AND c.ref_cents >= 4000))
  AND (c.cat_id <> 7141123011 OR c.cond = 'Used - Like New')
  AND NOT EXISTS (SELECT 1 FROM curation x WHERE x.asin = c.asin AND x.visibility = 'hidden');

-- Tracked roots: the deal tiers with NO rank limit (D39: depth). Tiers mirror TrackerConfig.tiers.
CREATE OR REPLACE VIEW sweep_deal AS
WITH s AS (SELECT DISTINCT ON (asin) * FROM sweep_rows WHERE swept_at > now() - interval '7 days'
           ORDER BY asin, swept_at DESC, id DESC)
SELECT s.asin, NULL::bigint AS offer_id, s.title, s.category, s.image, s.cond, s.resale_cents, s.ref_cents,
       s.strict, s.swept_at AS last_confirmed_at, false AS unconfirmed,
       NULL::timestamptz AS keepa_first_seen_at, NULL::timestamptz AS first_seen_at,
       NULL::text AS brand, NULL::text[] AS cat_path, NULL::int AS reviews, NULL::real AS rating,
       s.drops30, NULL::int AS monthly_sold, NULL::bool AS amazon_sells, s.rank,
       to_timestamp((s.creation_kmin + 21564000) * 60.0) AS priced_at, NULL::bigint AS cat_id,
       s.parent_asin, s.cats, s.ref_flags,
       ((s.strict >= 0.40 AND s.ref_cents >= 10000) OR (s.strict >= 0.30 AND s.ref_cents >= 20000)) AS in_tiers
FROM s
-- D46: plus 50%+ from a $40 reference for the shelves page; the main feed keeps `in_tiers` rows only.
WHERE ((s.strict >= 0.40 AND s.ref_cents >= 10000) OR (s.strict >= 0.30 AND s.ref_cents >= 20000)
       OR (s.strict >= 0.50 AND s.ref_cents >= 4000))
  AND NOT EXISTS (SELECT 1 FROM curation x WHERE x.asin = s.asin AND x.visibility = 'hidden');

-- Latest pass per category, one row per listing (ASIN + condition + price), summarised. ASIN-level counts.
CREATE OR REPLACE VIEW census_summary AS
WITH last AS (SELECT cat_id, max(swept_at) AS swept_at FROM census_rows
              WHERE swept_at > now() - interval '24 hours' GROUP BY cat_id),  -- D38: dropped categories age out
r AS (SELECT c.* FROM census_rows c JOIN last USING (cat_id, swept_at))
SELECT cat_id, max(category) AS category, max(swept_at) AS swept_at,
  count(DISTINCT (asin, cond, resale_cents)) AS listings,  -- a page fetched twice in one pass counts once
  count(DISTINCT asin) AS products,
  count(DISTINCT asin) FILTER (WHERE qualifies) AS qualifying_products,
  count(DISTINCT asin) FILTER (WHERE strict >= 0.5 AND (rank IS NULL OR rank <= 50000)) AS products_50,
  count(DISTINCT asin) FILTER (WHERE strict >= 0.5 AND ref_cents >= 10000 AND (rank IS NULL OR rank <= 50000)) AS products_50_100,
  round((percentile_cont(0.5) WITHIN GROUP (ORDER BY strict))::numeric, 2) AS median_strict,
  round(avg(CASE WHEN rank <= 50000 THEN 1.0 ELSE 0.0 END)::numeric, 2) AS share_popular,
  round((percentile_cont(0.5) WITHIN GROUP (ORDER BY ref_cents))::numeric / 100) AS median_ref_usd
FROM r GROUP BY cat_id;

-- Status page (admin): aggregates only, read by the API as feed_reader.
CREATE OR REPLACE VIEW status_state AS
SELECT key, value FROM tracker_state WHERE key IN ('heartbeat', 'status', 'last_sweep', 'last_full_sweep');

CREATE OR REPLACE VIEW status_funnel AS SELECT
  (SELECT count(*) FROM watch WHERE retired_at IS NULL) AS watching,
  (SELECT count(*) FROM watch) AS watched_ever,
  (SELECT count(*) FROM units WHERE state = 'live') AS units_live,
  (SELECT count(*) FROM units WHERE state = 'unconfirmed') AS units_unconfirmed,
  (SELECT count(*) FROM units WHERE state = 'gone') AS units_gone,
  (SELECT count(*) FROM units WHERE revivals > 0) AS units_revived,
  (SELECT count(*) FROM product) AS products_with_signals,
  (SELECT min(first_seen_at) FROM units) AS tracking_since;

CREATE OR REPLACE VIEW status_hourly AS
WITH h AS (SELECT generate_series(date_trunc('hour', now()) - interval '23 hours', date_trunc('hour', now()),
                                  interval '1 hour') AS h)
SELECT h.h AS hour,
  (SELECT count(*) FROM watch w WHERE w.added_at >= h.h AND w.added_at < h.h + interval '1 hour') AS new_watches,
  (SELECT count(DISTINCT u.asin) FROM units u JOIN watch w USING (asin)
    WHERE w.created_at >= h.h AND w.created_at < h.h + interval '1 hour' AND u.strict_first >= 0.5) AS new_50,
  (SELECT count(*) FROM checks c WHERE c.checked_at >= h.h AND c.checked_at < h.h + interval '1 hour') AS checks,
  (SELECT count(*) FROM checks c WHERE c.checked_at >= h.h AND c.checked_at < h.h + interval '1 hour'
    AND NOT c.offers_ok) AS failed,
  (SELECT coalesce(sum(c.tokens), 0) FROM checks c WHERE c.checked_at >= h.h AND c.checked_at < h.h + interval '1 hour') AS check_tokens,
  (SELECT count(*) FROM units u WHERE u.gone_at >= h.h AND u.gone_at < h.h + interval '1 hour') AS gone
FROM h ORDER BY 1;

-- Recently gone qualifying units, retired watches included (D27: shown with their last price).
CREATE OR REPLACE VIEW gone_internal AS
SELECT u.asin, u.offer_id, w.title, w.category, w.image, u.cond, u.last_price_cents AS resale_cents,
       u.ref_last_cents AS ref_cents, u.strict_last AS strict, u.last_seen_at, u.gone_at,
       p.brand, p.cat_path, p.reviews, p.rating, p.drops30, p.monthly_sold, p.amazon_sells, p.rank,
       u.first_seen_at, u.appeared_after_at, u.keepa_first_seen_at, u.absent_since_at, u.revivals
FROM units u JOIN watch w USING (asin) LEFT JOIN product p USING (asin)
WHERE u.state = 'gone' AND u.gone_at > now() - interval '7 days' AND ((u.strict_last >= 0.40 AND u.ref_last_cents >= 10000) OR (u.strict_last >= 0.30 AND u.ref_last_cents >= 20000))
  AND NOT EXISTS (SELECT 1 FROM unlisted x WHERE x.asin = u.asin);  -- D36

-- Admin (D36): the review queue with the curation decision and whether the ASIN is listed now.
CREATE OR REPLACE VIEW review_queue AS
SELECT r.asin, r.status, r.layer, r.reasons, r.rules, r.title, r.image, r.cond, r.resale_cents, r.ref_cents,
       r.strict, r.ref_flags, r.ref_parts, r.first_held_at, r.updated_at,
       coalesce(c.visibility, 'auto') AS visibility, coalesce(c.tags, '{}') AS tags, c.note,
       c.decided_ref_cents, c.updated_at AS decided_at, c.updated_by AS decided_by,
       x.why AS unlisted_why, x.asin IS NULL AS listed
FROM review r LEFT JOIN curation c USING (asin) LEFT JOIN unlisted x USING (asin);

-- Admin (D36): every curated ASIN, with a title from the review queue or the watch list.
CREATE OR REPLACE VIEW curation_admin AS
SELECT c.asin, c.visibility, c.tags, c.note, c.decided_ref_cents, c.updated_at, c.updated_by,
       coalesce(r.title, w.title) AS title, coalesce(r.image, w.image) AS image, r.status AS review_status,
       r.reasons, r.ref_cents, r.resale_cents, r.strict, x.why AS unlisted_why, x.asin IS NULL AS listed
FROM curation c LEFT JOIN review r USING (asin) LEFT JOIN watch w USING (asin) LEFT JOIN unlisted x USING (asin);
-- Notifications v1 (exploratory, 2026-10-08; fiftyoff/notify.py). The tracker records unit events in the same
-- transaction as the unit (outbox); the notifier decides who hears of them. Subscribers are added by CLI
-- (notify.py) until registration exists. Tiers are config ([tiers.*] in preflight.toml), not schema.
ALTER TABLE appeal ADD COLUMN IF NOT EXISTS rated_by text;  -- batch | local | api (rater backends)
CREATE TABLE IF NOT EXISTS deal_event (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL, kind text NOT NULL, asin text NOT NULL, offer_id bigint NOT NULL,
  status text NOT NULL DEFAULT 'new', why text, product_key text, shelf text, aisle text, score smallint,
  rules_v text, decided_at timestamptz
);
CREATE INDEX IF NOT EXISTS deal_event_open ON deal_event (id) WHERE status IN ('new', 'waiting');
CREATE TABLE IF NOT EXISTS subscriber (
  id bigserial PRIMARY KEY, email text UNIQUE CHECK (email = lower(email)), tier text NOT NULL DEFAULT 'free',
  paused bool NOT NULL DEFAULT false, note text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS endpoint (
  id bigserial PRIMARY KEY, subscriber_id bigint NOT NULL REFERENCES subscriber(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('email', 'webpush', 'apns', 'fcm')), address text NOT NULL, keys jsonb,
  failures int NOT NULL DEFAULT 0, last_ok_at timestamptz, disabled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (kind, address)
);
CREATE TABLE IF NOT EXISTS interest (
  subscriber_id bigint NOT NULL REFERENCES subscriber(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('shelf', 'aisle', 'keyword', 'similar')), value text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (subscriber_id, kind, value)
);
CREATE TABLE IF NOT EXISTS delivery (
  id bigserial PRIMARY KEY, event_id bigint NOT NULL REFERENCES deal_event(id),
  subscriber_id bigint NOT NULL REFERENCES subscriber(id) ON DELETE CASCADE,
  endpoint_id bigint NOT NULL REFERENCES endpoint(id) ON DELETE CASCADE, product_key text NOT NULL,
  deliver_at timestamptz NOT NULL, status text NOT NULL DEFAULT 'queued', sent_at timestamptz, error text,
  UNIQUE (endpoint_id, event_id)
);
CREATE INDEX IF NOT EXISTS delivery_due ON delivery (deliver_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS delivery_key ON delivery (subscriber_id, product_key);
-- Watchers per shelf: a shelf interest, or an aisle interest (front and aisle shelves only); active subscribers only.
CREATE OR REPLACE VIEW shelf_watchers AS
SELECT s.id AS shelf_id, count(DISTINCT i.subscriber_id) AS watching
FROM shelf s
JOIN interest i ON (i.kind = 'shelf' AND i.value = s.id) OR (i.kind = 'aisle' AND i.value = s.aisle AND s.role <> 'hidden')
JOIN subscriber sub ON sub.id = i.subscriber_id AND NOT sub.paused
WHERE EXISTS (SELECT 1 FROM endpoint e WHERE e.subscriber_id = sub.id AND e.disabled_at IS NULL)
GROUP BY s.id;
"""


def _ts(t: float | None):
    return None if t is None else datetime.fromtimestamp(t, tz=timezone.utc)


def _json(v) -> str | None:
    return None if v is None else json.dumps(v)


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

    def save_unit(self, u: Unit, event: str | None = None):
        with self.conn.transaction():  # the unit and its event land together or not at all (outbox)
            self._save_unit(u)
            if event:
                self.conn.execute("INSERT INTO deal_event (at, kind, asin, offer_id) VALUES (%s, %s, %s, %s)",
                                  (_ts(u.last_seen), event, u.asin, u.offer_id))

    def _save_unit(self, u: Unit):
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
                "keepa_pct, cond, comment, rank, creation_kmin, image, qualifies, formula, ref_parts, ref_flags, "
                "cats, drops30, qualify_v) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(_ts(t), r["asin"], r["parent"], r["cat"], r["title"], r["resale"], r["ref"], r["strict"],
                  r["keepa_pct"], r["cond"], r["comment"], r["rank"], r["creation"], r["image"], r["qualifies"],
                  r["formula"], _json(r.get("ref_parts")), _json(r.get("ref_flags")), r.get("cats"),
                  r.get("drops30"), r.get("qualify_v")) for r in rows])

    def save_product(self, t, asin, sig):
        cols = list(sig)
        self.conn.execute(
            f"INSERT INTO product (asin, {', '.join(cols)}, updated_at) VALUES (%s, {', '.join(['%s'] * len(cols))}, %s) "
            f"ON CONFLICT (asin) DO UPDATE SET {', '.join(f'{c} = COALESCE(EXCLUDED.{c}, product.{c})' for c in cols)}, "
            "updated_at = EXCLUDED.updated_at",
            (asin, *sig.values(), _ts(t)))

    def add_census_rows(self, t, cat_id, rows):
        if not rows:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO census_rows (swept_at, cat_id, asin, parent_asin, category, title, resale_cents, ref_cents, "
                "strict, keepa_pct, cond, rank, creation_kmin, qualifies, formula, image, ref_parts, ref_flags, cats, "
                "drops30) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(_ts(t), cat_id, r["asin"], r["parent"], r["cat"], r["title"], r["resale"], r["ref"], r["strict"],
                  r["keepa_pct"], r["cond"], r["rank"], r["creation"], r["qualifies"], r["formula"], r.get("image"),
                  _json(r.get("ref_parts")), _json(r.get("ref_flags")), r.get("cats"), r.get("drops30")) for r in rows])

    def known_cats(self):
        return {r[0] for r in self.conn.execute("SELECT id FROM cat_node")}

    def unnamed_cats(self):
        """Leaf ids on feed rows without a cat_node row, those with the most 40%+ rows first."""
        return [r[0] for r in self.conn.execute(
            "SELECT id FROM (SELECT unnest(cats) id, strict FROM sweep_rows UNION ALL "
            "SELECT unnest(cats), strict FROM census_rows) x WHERE id NOT IN (SELECT id FROM cat_node) "
            "GROUP BY id ORDER BY count(*) FILTER (WHERE strict >= 0.4) DESC, count(*) DESC")]

    def save_cat_nodes(self, t, nodes):
        with self.conn.cursor() as cur:  # a named node is never overwritten by an unnamed one
            cur.executemany(
                "INSERT INTO cat_node (id, name, parent_id, updated_at) VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE "
                "SET name = COALESCE(EXCLUDED.name, cat_node.name), parent_id = COALESCE(EXCLUDED.parent_id, cat_node.parent_id), "
                "updated_at = EXCLUDED.updated_at", [(cid, name, parent, _ts(t)) for cid, name, parent in nodes])

    def get_review(self, asin):
        from psycopg.rows import dict_row
        with self.conn.cursor(row_factory=dict_row) as cur:
            return cur.execute("SELECT status FROM review WHERE asin = %s",
                               (asin,)).fetchone()

    def put_review(self, t, r):
        self.conn.execute(
            "INSERT INTO review (asin, status, layer, reasons, rules, title, image, cond, resale_cents, ref_cents, strict, "
            "ref_flags, ref_parts, first_held_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (asin) DO UPDATE SET status=EXCLUDED.status, layer=EXCLUDED.layer, reasons=EXCLUDED.reasons, "
            "rules=EXCLUDED.rules, title=EXCLUDED.title, image=COALESCE(EXCLUDED.image, review.image), cond=EXCLUDED.cond, "
            "resale_cents=EXCLUDED.resale_cents, ref_cents=EXCLUDED.ref_cents, strict=EXCLUDED.strict, "
            "ref_flags=EXCLUDED.ref_flags, ref_parts=EXCLUDED.ref_parts, updated_at=EXCLUDED.updated_at, "
            "first_held_at=CASE WHEN review.status = 'cleared' AND EXCLUDED.status = 'pending' "
            "THEN EXCLUDED.first_held_at ELSE review.first_held_at END",
            (r["asin"], r["status"], r["layer"], json.dumps(r["reasons"]), r["rules"], r["title"], r.get("image"),
             r.get("cond"), r["resale"], r["ref"], r["strict"], _json(r.get("ref_flags")), _json(r.get("ref_parts")),
             _ts(t), _ts(t)))

    def add_check(self, t, check, offers):
        cid = self.conn.execute(
            "INSERT INTO checks (checked_at, asin, offers_ok, ref_cents, ref_parts, best_strict, tokens, formula, ref_flags) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (_ts(t), check["asin"], check["offers_ok"], check["ref"], json.dumps(check["ref_parts"]),
             check["best"], check["tokens"], check["formula"], _json(check.get("ref_flags")))).fetchone()[0]
        if offers:
            with self.conn.cursor() as cur:
                cur.executemany("INSERT INTO check_offers VALUES (%s,%s,%s,%s,%s,%s)",
                                [(cid, o["offer_id"], o["price"], o["cond"], o["comment"], o["strict"]) for o in offers])
