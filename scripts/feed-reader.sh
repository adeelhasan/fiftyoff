#!/usr/bin/env bash
# Create or update the read-only `feed_reader` role the API uses: it can SELECT the feed view and
# nothing else. Run on the box where the stack runs. Password comes from FEED_READER_PASSWORD in .env.
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
GRANT SELECT ON feed TO feed_reader;
SQL
echo "feed_reader: SELECT on feed only"
