#!/usr/bin/env bash
# Save the shelves home view (front shelves, top 50 each; shelves with more in full) to
# research/shelves/snapshots/<UTC time>.json.gz, for scripts/shelf_churn.py. Free: reads our own API on the VPS.
#   scripts/shelf_snapshot.sh              # from the laptop, over ssh
#   HOST=local scripts/shelf_snapshot.sh   # on the VPS (hourly from the deploy user's crontab, D48)
#   rsync -a fiftyoff-vps:fiftyoff-app/research/shelves/snapshots/ research/shelves/snapshots/   # fetch them
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${HOST:-fiftyoff-vps}
OUT=research/shelves/snapshots/$(date -u +%Y-%m-%dT%H%MZ).json
mkdir -p "$(dirname "$OUT")"
# the preview password is read on the VPS and never leaves it (rule 6's spirit)
CMD='cd ~/fiftyoff-app && set -a && . ./.env && set +a && curl -sf --max-time 120 -u "fiftyoff:$PREVIEW_PASSWORD" "localhost:8000/api/shelves?$0"'
get() { if [ "$HOST" = local ]; then bash -c "$CMD" "$1"; else ssh "$HOST" "bash -c '$CMD' '$1'"; fi; }
get "per=50" > "$OUT.home"
for id in $(python3 -c "import json,sys; print(' '.join(s['id'] for s in json.load(open(sys.argv[1]))['shelves'] if s['count'] > 50))" "$OUT.home"); do
  get "shelf=$id" > "$OUT.$id"
done
python3 - "$OUT" <<'EOF'
import glob, gzip, json, os, sys
out = sys.argv[1]
d = json.load(open(out + ".home"))
for f in glob.glob(out + ".*"):
    if not f.endswith(".home"):
        full = json.load(open(f))["shelves"][0]
        d["shelves"] = [full if s["id"] == full["id"] else s for s in d["shelves"]]
    os.remove(f)
with gzip.open(out + ".gz", "wt") as f:
    json.dump(d, f)
print(out + ".gz", d["delight_version"], d["count"], "products on", len(d["shelves"]), "shelves")
EOF
