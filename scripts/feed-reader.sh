#!/usr/bin/env bash
# Create or update the `feed_reader` role the API uses: it can SELECT the feed and admin views and write
# curation decisions (D36), and nothing else. Run on the box where the stack runs. Password comes from FEED_READER_PASSWORD in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
PW=$(grep '^FEED_READER_PASSWORD=' .env | cut -d= -f2- || true)
PW=${PW:-feed-dev}
docker compose exec -T db psql -U fiftyoff -d fiftyoff -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'feed_reader') THEN CREATE ROLE feed_reader LOGIN; END IF;
END \$\$;
ALTER ROLE feed_reader PASSWORD '$PW';
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM feed_reader;
GRANT USAGE ON SCHEMA public TO feed_reader;
GRANT SELECT ON feed, deal_internal, gone_internal, status_state, status_funnel, status_hourly, census_summary, census_deal TO feed_reader;
-- D39: the seen-in-feed layer and subcategory names
GRANT SELECT ON sweep_deal, cat_node TO feed_reader;
-- D35/D36: the review queue (read only; decisions moved to curation), and curation decisions + their log
GRANT SELECT ON review, review_queue, curation_admin, curation TO feed_reader;
GRANT INSERT, UPDATE ON curation TO feed_reader;
GRANT INSERT ON curation_log TO feed_reader;
GRANT USAGE ON SEQUENCE curation_log_id_seq TO feed_reader;
-- D37: Cloudflare Access users (sign-in upserts, People tab) and their change log
GRANT SELECT, INSERT, UPDATE ON app_user TO feed_reader;
GRANT INSERT ON app_user_log TO feed_reader;
GRANT USAGE ON SEQUENCE app_user_log_id_seq TO feed_reader;
-- D42: the model's appeal judgements
GRANT SELECT ON appeal TO feed_reader;
-- D45: kinds -> shelves
GRANT SELECT ON kind_map TO feed_reader;
-- D46: shelves and their roles (the admin sets a role from the shelves page)
GRANT SELECT ON shelf TO feed_reader;
GRANT UPDATE (role, updated_by, updated_at) ON shelf TO feed_reader;
-- Keyword alerts (alerts-beta.md): sign-up, confirm and My alerts write subscribers, their email endpoint and
-- their alerts; My alerts reads what an alert sent or missed. Nothing else about deliveries or events.
GRANT SELECT, INSERT, UPDATE ON subscriber, endpoint, interest TO feed_reader;
GRANT USAGE ON SEQUENCE subscriber_id_seq, endpoint_id_seq, interest_id_seq TO feed_reader;
GRANT SELECT ON alert_delivery TO feed_reader;
-- api-v1: /d/ click log (insert only) and new arrivals per shelf (per_week)
GRANT INSERT ON click TO feed_reader;
GRANT USAGE ON SEQUENCE click_id_seq TO feed_reader;
GRANT SELECT ON arrival_7d TO feed_reader;
-- trust-first: page-view counts per day, page and A/B arm (upsert)
GRANT SELECT, INSERT, UPDATE ON page_view TO feed_reader;
-- D64: deal pages opened (insert only)
GRANT INSERT ON deal_open TO feed_reader;
GRANT USAGE ON SEQUENCE deal_open_id_seq TO feed_reader;
SQL
echo "feed_reader: SELECT on the feed, gone, status and admin views; INSERT/UPDATE on curation, app_user and alerts (subscriber, endpoint, interest), INSERT on their logs and click"
