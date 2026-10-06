-- Tracking-efficiency measurements (2026-10-05 session; baseline for the D39 tracking changes).
-- Run on the VPS: docker compose exec -T db psql -U fiftyoff -d fiftyoff -f - < this-file
-- Token split by operation is in research/tracker/token-ledger.jsonl (label prefix: check / census / sweep).

-- A. Check spend, last 24 h, by discount band x age since Keepa priced it
-- checks in the last 24 h by what the product was at the time
WITH c AS (
  SELECT c.*, w.created_at, w.added_at,
    CASE WHEN NOT c.offers_ok THEN 'failed'
         WHEN c.best_strict IS NULL THEN 'no resale unit'
         WHEN c.best_strict >= 0.5 THEN '50%+'
         WHEN c.best_strict >= 0.4 THEN '40-49%'
         WHEN c.best_strict >= 0.3 THEN '30-39%'
         ELSE '<30%' END AS band,
    CASE WHEN c.checked_at - w.created_at < interval '6 hours' THEN 'priced <6h'
         WHEN c.checked_at - w.created_at < interval '2 days' THEN '6h-2d'
         WHEN c.checked_at - w.created_at < interval '7 days' THEN '2-7d'
         ELSE '7d+' END AS age
  FROM checks c JOIN watch w USING (asin) WHERE c.checked_at > now() - interval '24 hours')
SELECT band, age, count(*) checks, sum(tokens) tokens, count(DISTINCT asin) asins FROM c GROUP BY ROLLUP(band), age ORDER BY band NULLS LAST, age;

-- B. Yield: band at first check vs later; change rate between consecutive checks; fresh 50%+ lifespans
-- 1. per ASIN: first ok check band vs. best band ever reached later
WITH ok AS (SELECT asin, checked_at, best_strict, row_number() OVER (PARTITION BY asin ORDER BY checked_at) rn
            FROM checks WHERE offers_ok),
f AS (SELECT asin, best_strict first_s FROM ok WHERE rn = 1),
later AS (SELECT asin, max(best_strict) best_later, count(*) n FROM ok WHERE rn > 1 GROUP BY asin)
SELECT CASE WHEN first_s IS NULL THEN 'no unit' WHEN first_s>=0.5 THEN '50+' WHEN first_s>=0.4 THEN '40-49' WHEN first_s>=0.3 THEN '30-39' ELSE '<30' END first_band,
  count(*) asins, sum(n) later_checks,
  count(*) FILTER (WHERE best_later >= 0.5 AND coalesce(first_s,0) < 0.5) rose_to_50,
  count(*) FILTER (WHERE best_later IS NOT NULL AND first_s IS NULL) unit_appeared
FROM f LEFT JOIN later USING (asin) GROUP BY 1 ORDER BY 1;
-- 2. consecutive-check change rate: did best_strict or the live offer set change vs the previous check?
WITH s AS (
  SELECT c.id, c.asin, c.checked_at, c.best_strict, w.created_at,
    (SELECT string_agg(o.offer_id::text||':'||o.price_cents, ',' ORDER BY o.offer_id) FROM check_offers o WHERE o.check_id=c.id) sig
  FROM checks c JOIN watch w USING (asin) WHERE c.offers_ok AND c.checked_at > now() - interval '48 hours'),
p AS (SELECT s.*, lag(sig) OVER (PARTITION BY asin ORDER BY checked_at) prev_sig,
        lag(checked_at) OVER (PARTITION BY asin ORDER BY checked_at) prev_t FROM s)
SELECT CASE WHEN checked_at - created_at < interval '6 hours' THEN 'priced <6h' ELSE 'older' END age,
  CASE WHEN best_strict >= 0.5 THEN '50+' WHEN best_strict >= 0.3 THEN '30-49' ELSE 'other' END band,
  count(*) checks, count(*) FILTER (WHERE sig IS DISTINCT FROM prev_sig) changed,
  round(100.0*count(*) FILTER (WHERE sig IS DISTINCT FROM prev_sig)/count(*)) pct,
  round(avg(extract(epoch FROM checked_at-prev_t)/60)) avg_gap_min
FROM p WHERE prev_sig IS NOT NULL OR prev_t IS NOT NULL GROUP BY 1,2 ORDER BY 1,2;
-- 3. 50%+ units first seen fresh: lifespan (gone within N h of first seen)
SELECT count(*) fresh_50_units,
  count(*) FILTER (WHERE gone_at - coalesce(appeared_after_at, first_seen_at) < interval '2 hours') gone_2h,
  count(*) FILTER (WHERE gone_at - coalesce(appeared_after_at, first_seen_at) < interval '6 hours') gone_6h,
  count(*) FILTER (WHERE gone_at - coalesce(appeared_after_at, first_seen_at) < interval '24 hours') gone_24h,
  count(*) FILTER (WHERE state='gone') gone_any
FROM units WHERE strict_first >= 0.5 AND appeared_after_at IS NOT NULL;

-- C. Same-unit Resale reprices, and how near misses reached 50%
-- 1. same unit (asin, offer_id) across checks: does its price move?
WITH o AS (SELECT c.asin, o.offer_id, c.checked_at, o.price_cents,
             lag(o.price_cents) OVER (PARTITION BY c.asin, o.offer_id ORDER BY c.checked_at) prev
           FROM check_offers o JOIN checks c ON c.id = o.check_id WHERE c.offers_ok),
u AS (SELECT asin, offer_id, count(*) obs,
        count(*) FILTER (WHERE price_cents < prev) drops, count(*) FILTER (WHERE price_cents > prev) rises,
        max(checked_at) - min(checked_at) span,
        min(price_cents) lo, max(price_cents) hi
      FROM o GROUP BY 1,2 HAVING count(*) >= 2)
SELECT count(*) units_seen_twice, round(avg(extract(epoch FROM span)/86400)::numeric,1) avg_days_observed,
  count(*) FILTER (WHERE drops > 0) units_with_drop, count(*) FILTER (WHERE rises > 0) units_with_rise,
  sum(drops) total_drops, sum(rises) total_rises,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY (hi-lo)::real/hi) FILTER (WHERE drops > 0)::numeric, 2) med_drop_size
FROM u;
-- 2. drop sizes and timing (how long after the unit was first seen)
WITH o AS (SELECT c.asin, o.offer_id, c.checked_at, o.price_cents,
             lag(o.price_cents) OVER (PARTITION BY c.asin, o.offer_id ORDER BY c.checked_at) prev
           FROM check_offers o JOIN checks c ON c.id = o.check_id WHERE c.offers_ok)
SELECT round((1 - price_cents::real/prev)::numeric, 2) drop_pct, count(*) n
FROM o WHERE price_cents < prev GROUP BY 1 ORDER BY 2 DESC LIMIT 12;
-- 3. the near misses that reached 50%+: which mechanism?
WITH ok AS (SELECT c.id, asin, checked_at, best_strict, ref_cents, row_number() OVER (PARTITION BY asin ORDER BY checked_at) rn FROM checks c WHERE offers_ok),
f AS (SELECT * FROM ok WHERE rn = 1 AND best_strict >= 0.3 AND best_strict < 0.5),
hit AS (SELECT DISTINCT ON (ok.asin) ok.* FROM ok JOIN f USING (asin) WHERE ok.rn > 1 AND ok.best_strict >= 0.5 ORDER BY ok.asin, ok.checked_at)
SELECT h.asin, round(f.best_strict::numeric,2) s0, round(h.best_strict::numeric,2) s1, f.ref_cents/100 ref0, h.ref_cents/100 ref1,
  (SELECT min(price_cents)/100 FROM check_offers WHERE check_id = f.id) p0, (SELECT min(price_cents)/100 FROM check_offers WHERE check_id = h.id) p1,
  EXISTS (SELECT 1 FROM check_offers a JOIN check_offers b ON a.offer_id = b.offer_id WHERE a.check_id = f.id AND b.check_id = h.id AND b.price_cents < a.price_cents) same_unit_drop
FROM hit h JOIN f USING (asin);

-- D. Discovery lag: Keepa's price-set time -> our watch list
SELECT count(*) n, round((percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM added_at - created_at)/60))::numeric) med_min
FROM watch WHERE added_at > now() - interval '3 days' AND created_at IS NOT NULL AND added_at >= created_at;
