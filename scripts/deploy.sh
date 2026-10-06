#!/usr/bin/env bash
# Deploy the git-tracked files to the VPS and rebuild the image. Data, .env and approvals stay put.
#   scripts/deploy.sh            # sync + build + tests + schema check on the VPS
# Running services are not restarted; do that deliberately (docker compose --profile tracker up -d tracker).
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${HOST:-fiftyoff-vps}
git ls-files -z | rsync -az --from0 --files-from=- ./ "$HOST:fiftyoff-app/"
ssh "$HOST" 'cd ~/fiftyoff-app && docker compose build -q app && docker compose run --rm -q app 2>&1 | grep -E "passed|failed"'
# The tests never run the Postgres schema (PUNCHLIST 2026-10-05): apply it to the live database inside a
# transaction that is rolled back, so a broken view fails here instead of crash-looping the tracker.
ssh "$HOST" 'cd ~/fiftyoff-app && docker compose run --rm -q app python -c "
import os, psycopg
from fiftyoff.store_pg import SCHEMA
with psycopg.connect(os.environ[\"DATABASE_URL\"]) as c:
    c.execute(SCHEMA); c.rollback()
print(\"schema ok (applied and rolled back)\")
"'
