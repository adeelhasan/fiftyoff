-- D42: products at strict 50%+ in any feed layer that the model hasn't rated yet, one per key (parent ASIN, else ASIN).
-- Output is the rater's input (key, category, brand, title), tab-separated:
--   ssh fiftyoff-vps 'cd fiftyoff-app && docker compose exec -T db psql -U fiftyoff -d fiftyoff -At -F "	"' \
--     < scripts/sql/appeal-unrated.sql > new.tsv
WITH d AS (
  SELECT asin, parent_asin, title, category, brand, strict FROM deal_internal
  UNION ALL SELECT asin, parent_asin, title, category, NULL, strict FROM sweep_deal
  UNION ALL SELECT asin, parent_asin, title, category, NULL, strict FROM census_deal),
k AS (SELECT DISTINCT ON (coalesce(parent_asin, asin)) coalesce(parent_asin, asin) AS key, asin, category,
       coalesce(brand, '') AS brand, replace(replace(title, E'\t', ' '), E'\n', ' ') AS title
      FROM d WHERE strict >= 0.5 AND title IS NOT NULL ORDER BY coalesce(parent_asin, asin), strict DESC)
SELECT key, category, brand, title FROM k
WHERE NOT EXISTS (SELECT 1 FROM appeal a WHERE a.key IN (k.key, k.asin) AND a.model = 'sonnet');
