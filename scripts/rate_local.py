"""Rate new products on the user's Claude subscription (headless Claude Code), so alerts know their shelf.

    uv run scripts/rate_local.py --dry-run          # show the candidates, rate nothing
    uv run scripts/rate_local.py                    # one batch: pull, rate with Sonnet, check, load
    uv run scripts/rate_local.py --loop 10          # every 10 minutes until stopped
    uv run scripts/rate_local.py --max-batches 4    # batches until nothing is left, at most 4 (launchd, every 30 min:
                                                    #   scripts/launchd/app.fiftyoff.rate.plist)

Runs on the Mac, never in the tracker (rule 7): candidates come from the VPS over ssh, the rubric is
fiftyoff/appeal_rubric.md, every output line is checked (fiftyoff/appeal.py) and only keys we sent are loaded,
as model `sonnet` with rated_by = 'local'. Products with an alert waiting on their rating go first, then every
unrated 50%+ deal in any layer (live, sweep, census; the same set as scripts/sql/appeal-unrated.sql), newest price
first, then other unrated watches. Inputs and outputs are kept under research/appeal/local/. The `api` backend (a funded key,
on the VPS) comes later.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from fiftyoff.appeal import CANDIDATES_SQL, parse_lines, prompt, rubric_version, upsert_script  # noqa: E402

PSQL = "cd fiftyoff-app && docker compose exec -T db psql -U fiftyoff -d fiftyoff -v ON_ERROR_STOP=1 -q"
OUT = Path("research/appeal/local")
MODEL = "sonnet"

CANDIDATES = "COPY (" + CANDIDATES_SQL + ") TO STDOUT;"



def ssh_psql(script: str) -> str:
    out = subprocess.run(["ssh", "fiftyoff-vps", PSQL], input=script, text=True, capture_output=True)
    if out.returncode:
        raise SystemExit(out.stderr)
    return out.stdout


def batch(limit: int, dry: bool) -> int:
    rows = [r.split("\t") for r in ssh_psql(CANDIDATES.format(limit=int(limit))).splitlines() if r.strip()]
    if not rows:
        print("nothing to rate")
        return 0
    lines = ["\t".join(r) for r in rows]
    if dry:
        print("\n".join(lines))
        print(f"{len(rows)} candidates")
        return 0
    v = rubric_version()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")  # seconds: batches can start in the same minute
    d = OUT / stamp
    d.mkdir(parents=True, exist_ok=True)
    (d / "input.tsv").write_text("\n".join(lines) + "\n")
    out = subprocess.run(["claude", "-p", "--model", MODEL], input=prompt(lines), text=True, capture_output=True)
    (d / "output.tsv").write_text(out.stdout)
    if out.returncode:
        raise SystemExit(f"claude failed: {out.stderr[:500]}")
    sent = {r[0] for r in rows}
    got = [ln for ln in out.stdout.splitlines() if ln.split("\t")[0].strip() in sent]
    good, bad = parse_lines(got, v, str(d / "output.tsv"))
    if good:
        ssh_psql(upsert_script(MODEL, v, good, rated_by="local"))
    missing = sent - {g[0] for g in good}
    print(f"[{stamp}] {len(rows)} sent, {len(good)} loaded ({v}), {len(bad)} bad lines, {len(missing)} missing -> {d}")
    for b in bad[:5]:
        print("  bad:", b)
    return len(good)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=60, help="products per batch")
    ap.add_argument("--loop", type=float, help="repeat every N minutes")
    ap.add_argument("--max-batches", type=int, default=1, help="run batches until none is full, at most this many")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    while True:
        for _ in range(args.max_batches):
            if batch(args.limit, args.dry_run) < args.limit:
                break
        if not args.loop or args.dry_run:
            return 0
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    raise SystemExit(main())
