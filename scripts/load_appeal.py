"""Load appeal judgements (D42) into the `appeal` table on the VPS.

    uv run scripts/load_appeal.py MODEL PROMPT_V FILE.tsv [FILE.tsv ...]

Each line is the rubric's output (fiftyoff/appeal_rubric.md): key, score, tags, why. Rows are upserted per
(key, model), so a re-rating replaces the old one. Bad lines are reported and skipped, never guessed.
"""
import csv
import io
import subprocess
import sys
from datetime import datetime, timezone

TAGS = {"tech", "gaming", "audio", "home", "kitchen", "outdoors", "fitness", "travel", "toys", "fashion", "beauty",
        "tools", "auto", "pets", "office", "garden", "music", "baby", "health"}


def parse(path: str) -> tuple[list[tuple], list[str]]:
    rows, bad = [], []
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3 or not parts[1].strip().isdigit() or not 0 <= int(parts[1]) <= 10:
            bad.append(f"{path}:{n}: {line.strip()[:80]}")
            continue
        tags = [t for t in parts[2].replace(" ", "").split(",") if t in TAGS]
        rows.append((parts[0].strip(), int(parts[1]), tags, (parts[3] if len(parts) > 3 else "").strip()[:200]))
    return rows, bad


def main() -> None:
    model, prompt_v, files = sys.argv[1], sys.argv[2], sys.argv[3:]
    rows, bad = [], []
    for f in files:
        r, b = parse(f)
        rows += r
        bad += b
    rows = list({r[0]: r for r in rows}.values())  # last rating per key wins
    now = datetime.now(timezone.utc).isoformat()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for key, score, tags, why in rows:
        w.writerow([key, model, score, "{" + ",".join(tags) + "}", why, prompt_v, now])
    sql = ("CREATE TEMP TABLE a (LIKE appeal); "
           "\\copy a FROM STDIN WITH (FORMAT csv)\n")
    upsert = ("INSERT INTO appeal SELECT * FROM a ON CONFLICT (key, model) DO UPDATE SET score = EXCLUDED.score, "
              "tags = EXCLUDED.tags, why = EXCLUDED.why, prompt_v = EXCLUDED.prompt_v, rated_at = EXCLUDED.rated_at;\n")
    script = sql + buf.getvalue() + "\\.\n" + upsert
    out = subprocess.run(["ssh", "fiftyoff-vps", "cd fiftyoff-app && docker compose exec -T db psql -U fiftyoff -d fiftyoff "
                          "-v ON_ERROR_STOP=1 -q"], input=script, text=True, capture_output=True)
    print(f"{len(rows)} rows for model {model} ({prompt_v}); {len(bad)} bad lines skipped")
    for b in bad[:10]:
        print("  bad:", b)
    if out.returncode:
        sys.exit(out.stderr)


if __name__ == "__main__":
    main()
