"""Load appeal judgements (D42, D44) into the `appeal` table on the VPS.

    uv run scripts/load_appeal.py MODEL PROMPT_V FILE.tsv [FILE.tsv ...]

Each line is the rubric's output (fiftyoff/appeal_rubric.md):
- a0.1: key, score, tags, why
- a0.2: key, score, aisle, kind, fit, why
- a0.3: key, score, aisle, shelf, kind, fit, size, why (shelf = an id from fiftyoff/shelves.tsv)
Rows are upserted per (key, model), so a re-rating replaces the old one. Bad lines are reported and skipped, never guessed.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from fiftyoff.appeal import parse_lines, upsert_script  # noqa: E402

PSQL = "cd fiftyoff-app && docker compose exec -T db psql -U fiftyoff -d fiftyoff -v ON_ERROR_STOP=1 -q"


def parse(path: str, v: str) -> tuple[list[tuple], list[str]]:
    with open(path, encoding="utf-8") as f:
        return parse_lines(f, v, path)


def main() -> None:
    model, prompt_v, files = sys.argv[1], sys.argv[2], sys.argv[3:]
    rows, bad = [], []
    for f in files:
        r, b = parse(f, prompt_v)
        rows += r
        bad += b
    out = subprocess.run(["ssh", "fiftyoff-vps", PSQL], input=upsert_script(model, prompt_v, rows),
                         text=True, capture_output=True)
    print(f"{len({r[0] for r in rows})} rows for model {model} ({prompt_v}); {len(bad)} bad lines skipped")
    for b in bad[:10]:
        print("  bad:", b)
    if out.returncode:
        sys.exit(out.stderr)


if __name__ == "__main__":
    main()
