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
-- D35/D36: the review queue (read only; decisions moved to curation), and curation decisions + their log
GRANT SELECT ON review, review_queue, curation_admin, curation TO feed_reader;
GRANT INSERT, UPDATE ON curation TO feed_reader;
GRANT INSERT ON curation_log TO feed_reader;
GRANT USAGE ON SEQUENCE curation_log_id_seq TO feed_reader;
SQL
echo "feed_reader: SELECT on the feed, gone, status and admin views; INSERT/UPDATE on curation, INSERT on curation_log"
