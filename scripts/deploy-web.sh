#!/usr/bin/env bash
# Build the static site (web/) and rsync web/out/ to the VPS, where the api container serves it from a bind mount
# (compose.yaml: ./web/out:/srv/web:ro). No restart needed. web/out isn't git-tracked, so scripts/deploy.sh can't carry it.
#   scripts/deploy-web.sh
set -euo pipefail
cd "$(dirname "$0")/../web"
HOST=${HOST:-fiftyoff-vps}
[ -d node_modules ] || npm ci
# web/fixtures is a copy of the API's canonical fixtures; say so when they drift (doesn't block a deploy).
diff -rq fixtures ../tests/fixtures/api_v1 >/dev/null || echo "note: web/fixtures differs from tests/fixtures/api_v1; recopy it" >&2
NEXT_PUBLIC_API= npm run build
# Fail before shipping a build that leaks a field the API never sends (D19 / api-v1.md "Never in v1").
if grep -rIlE '"(score|score_parts|delight|appeal|rank|monthly_sold)"' out --include=*.html --include=*.js; then
  echo "refusing to deploy: a forbidden field name appears in web/out" >&2; exit 1
fi
if grep -rIlq 'B0NEW00001' out; then echo "refusing to deploy: fixture data is in web/out (built with NEXT_PUBLIC_API=fixtures?)" >&2; exit 1; fi
ssh "$HOST" 'mkdir -p ~/fiftyoff-app/web/out'
# Assets first, then the HTML, so a page never points at a chunk that isn't there yet.
rsync -az out/_next/ "$HOST:fiftyoff-app/web/out/_next/"
rsync -az --delete --delay-updates out/ "$HOST:fiftyoff-app/web/out/"
echo "deployed web/out to $HOST"
