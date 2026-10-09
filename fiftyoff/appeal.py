"""Appeal judgements (D42, D44, D46): parse and validate the rubric's output lines, and build the upsert.

Shared by scripts/load_appeal.py (batch files) and scripts/rate_local.py (the rater). Bad lines are reported
and skipped, never guessed. No model is called here (rule 7: the tracker never imports a model client).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

TAGS = {"tech", "gaming", "audio", "home", "kitchen", "outdoors", "fitness", "travel", "toys", "fashion", "beauty",
        "tools", "auto", "pets", "office", "garden", "music", "baby", "health"}
AISLES = {"tech", "gaming", "audio-tv", "kitchen", "home-appliances", "home-decor", "diy", "outdoors", "fitness-sports",
          "travel", "fashion", "beauty-health", "toys-kids", "pets", "office-school", "auto", "music", "other"}
SHELVES = Path(__file__).parent / "shelves.tsv"
RUBRIC = Path(__file__).parent / "appeal_rubric.md"


def shelf_ids() -> set[str]:
    return {line.split("\t")[0] for line in SHELVES.read_text().splitlines()}


def parse_lines(lines: Iterable[str], v: str, where: str = "", ids: set[str] | None = None) -> tuple[list[tuple], list[str]]:
    """Rubric output lines -> rows (key, score, tags, why, aisle, kind, fit, shelf, size), plus the bad lines.
    a0.1: key, score, tags, why; a0.2: key, score, aisle, kind, fit, why;
    a0.3: key, score, aisle, shelf, kind, fit, size, why (shelf = an id from fiftyoff/shelves.tsv)."""
    v2, v3 = v >= "a0.2", v >= "a0.3"
    if v3 and ids is None:
        ids = shelf_ids()
    rows, bad = [], []
    for n, line in enumerate(lines, 1):
        p = [x.strip() for x in line.rstrip("\n").split("\t")]
        ok = len(p) >= (8 if v3 else 6 if v2 else 3) and p[1].isdigit() and 0 <= int(p[1]) <= 10
        if v3:
            ok = ok and p[2] in AISLES and p[3] in ids and p[4] and p[5] in ("y", "n")
        elif v2:
            ok = ok and p[2] in AISLES and p[3] and p[4] in ("y", "n")
        if not ok:
            bad.append(f"{where}:{n}: {line.strip()[:100]}")
            continue
        if v3:
            size = None if p[6] in ("", "-") else p[6][:40]
            rows.append((p[0], int(p[1]), [], p[7][:200], p[2], p[4].lower()[:60], p[5] == "y", p[3], size))
        elif v2:
            rows.append((p[0], int(p[1]), [], p[5][:200], p[2], p[3].lower()[:60], p[4] == "y", None, None))
        else:
            tags = [t for t in p[2].replace(" ", "").split(",") if t in TAGS]
            rows.append((p[0], int(p[1]), tags, (p[3] if len(p) > 3 else "")[:200], None, None, None, None, None))
    return rows, bad


def upsert_script(model: str, prompt_v: str, rows: list[tuple], rated_by: str = "batch") -> str:
    """A psql script that upserts the rows into `appeal` (last rating per key wins)."""
    rows = list({r[0]: r for r in rows}.values())
    now = datetime.now(timezone.utc).isoformat()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for key, score, tags, why, aisle, kind, fit, shelf, size in rows:
        w.writerow([key, model, score, "{" + ",".join(tags) + "}", why, prompt_v, now, aisle, kind,
                    "" if fit is None else str(fit).lower(), shelf or "", size or "", rated_by])
    cols = "key, model, score, tags, why, prompt_v, rated_at, aisle, kind, fit, shelf, size, rated_by"
    return (f"CREATE TEMP TABLE a AS SELECT {cols} FROM appeal LIMIT 0;\n"
            f"\\copy a ({cols}) FROM STDIN WITH (FORMAT csv)\n" + buf.getvalue() + "\\.\n"
            f"INSERT INTO appeal ({cols}) SELECT {cols} FROM a ON CONFLICT (key, model) DO UPDATE SET "
            "score = EXCLUDED.score, tags = EXCLUDED.tags, why = EXCLUDED.why, prompt_v = EXCLUDED.prompt_v, "
            "rated_at = EXCLUDED.rated_at, aisle = EXCLUDED.aisle, kind = EXCLUDED.kind, fit = EXCLUDED.fit, "
            "shelf = EXCLUDED.shelf, size = EXCLUDED.size, rated_by = EXCLUDED.rated_by;\n")
