#!/usr/bin/env bash
# Deploy the git-tracked files to the VPS and rebuild the image. Data, .env and approvals stay put.
#   scripts/deploy.sh            # sync + build + tests on the VPS
# Running services are not restarted; do that deliberately (docker compose --profile tracker up -d tracker).
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${HOST:-fiftyoff-vps}
git ls-files -z | rsync -az --from0 --files-from=- ./ "$HOST:fiftyoff-app/"
ssh "$HOST" 'cd ~/fiftyoff-app && docker compose build -q app && docker compose run --rm -q app 2>&1 | grep -E "passed|failed"'
