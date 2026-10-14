"""Appeal judgements (D42, D44, D46): parse and validate the rubric's output lines, and build the upsert.

Shared by scripts/load_appeal.py (batch files), scripts/rate_local.py (the subscription rater) and fiftyoff/rater.py
(the API rater): one candidate query, one prompt, one validator. Bad lines are reported and skipped, never guessed.
No model is called here (rule 7: the tracker never imports a model client).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

TAGS = {"tech", "gaming", "audio", "home", "kitchen", "outdoors", "fitness", "travel", "toys", "fashion", "beauty",
        "tools", "auto", "pets", "office", "garden", "music", "baby", "health"}
AISLES = {"tech", "gaming", "audio-tv", "kitchen", "home-appliances", "home-decor", "diy", "outdoors", "fitness-sports",
          "travel", "fashion", "beauty-health", "toys-kids", "pets", "office-school", "auto", "music", "other"}
SHELVES = Path(__file__).parent / "shelves.tsv"
RUBRIC = Path(__file__).parent / "appeal_rubric.md"


# What needs a rating, one row per key (parent ASIN, else ASIN): key, title, brand, category path. Format {limit}
# with an int. The subscription rater wraps it in COPY over ssh; the API rater runs it with psycopg.
CANDIDATES_SQL = """WITH d AS (
  -- 0: an alert is waiting on the rating; 1: a headline 50%+ deal in any layer (live, sweep, census), newest
  -- price first so fresh deals reach their shelf soonest (D48); 2: other active watches (D47 decides their checks)
  SELECT w.asin, w.parent_asin, w.title, w.category, NULL AS brand, NULL::text[] AS cat_path, now() AS priced_at, 0 AS pri
    FROM deal_event e JOIN watch w USING (asin) WHERE e.status IN ('new', 'waiting')
  UNION ALL SELECT asin, parent_asin, title, category, brand, cat_path, priced_at, 1 FROM deal_internal WHERE strict >= 0.5
  UNION ALL SELECT asin, parent_asin, title, category, brand, cat_path, priced_at, 1 FROM sweep_deal WHERE strict >= 0.5
  UNION ALL SELECT asin, parent_asin, title, category, brand, cat_path, priced_at, 1 FROM census_deal WHERE strict >= 0.5
  UNION ALL SELECT asin, parent_asin, title, category, NULL, NULL, added_at, 2 FROM watch WHERE retired_at IS NULL),
k AS (SELECT DISTINCT ON (coalesce(parent_asin, asin)) coalesce(parent_asin, asin) AS key, asin, title, category,
        brand, cat_path, priced_at, pri
      FROM d WHERE title IS NOT NULL ORDER BY coalesce(parent_asin, asin), pri, priced_at DESC NULLS LAST)
SELECT k.key, regexp_replace(k.title, '[\\t\\n\\r]+', ' ', 'g'),
       regexp_replace(coalesce(k.brand, p.brand, ''), '[\\t\\n\\r]+', ' ', 'g'),
       regexp_replace(coalesce(array_to_string(coalesce(k.cat_path, p.cat_path), ' > '), k.category, ''), '[\\t\\n\\r]+', ' ', 'g')
FROM k LEFT JOIN product p ON p.asin = k.asin
WHERE NOT EXISTS (SELECT 1 FROM appeal a WHERE a.key IN (k.key, k.asin) AND a.model = 'sonnet')
ORDER BY k.pri, k.priced_at DESC NULLS LAST LIMIT {limit}"""

UPSERT_CONFLICT = ("ON CONFLICT (key, model) DO UPDATE SET score = EXCLUDED.score, tags = EXCLUDED.tags, why = EXCLUDED.why, "
                   "prompt_v = EXCLUDED.prompt_v, rated_at = EXCLUDED.rated_at, aisle = EXCLUDED.aisle, kind = EXCLUDED.kind, "
                   "fit = EXCLUDED.fit, shelf = EXCLUDED.shelf, size = EXCLUDED.size, rated_by = EXCLUDED.rated_by")
COLS = "key, model, score, tags, why, prompt_v, rated_at, aisle, kind, fit, shelf, size, rated_by"


def rubric_version() -> str:
    m = re.search(r"#\s*Appeal rubric (a\d+\.\d+)", RUBRIC.read_text())
    if not m:
        raise SystemExit("can't read the rubric version from fiftyoff/appeal_rubric.md")
    return m.group(1)


def products_block(lines: list[str]) -> str:
    return ("## Products\n\nOne per line: `key<TAB>title<TAB>brand<TAB>category path`. "
            "Rate every one, in input order, and output only the tab-separated lines.\n\n" + "\n".join(lines) + "\n")


def prompt(lines: list[str]) -> str:
    """The whole prompt in one piece (claude -p). The API rater sends the rubric as a cached system prompt instead."""
    return RUBRIC.read_text() + "\n\n" + products_block(lines)


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
    return (f"CREATE TEMP TABLE a AS SELECT {COLS} FROM appeal LIMIT 0;\n"
            f"\\copy a ({COLS}) FROM STDIN WITH (FORMAT csv)\n" + buf.getvalue() + "\\.\n"
            f"INSERT INTO appeal ({COLS}) SELECT {COLS} FROM a {UPSERT_CONFLICT};\n")


def upsert_rows(conn, model: str, prompt_v: str, rows: list[tuple], rated_by: str) -> int:
    """The same upsert as upsert_script, through a psycopg connection (the API rater on the VPS)."""
    rows = list({r[0]: r for r in rows}.values())
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.executemany(f"INSERT INTO appeal ({COLS}) VALUES ({', '.join(['%s'] * 13)}) {UPSERT_CONFLICT}",
                        [(key, model, score, tags, why, prompt_v, now, aisle, kind, fit, shelf, size, rated_by)
                         for key, score, tags, why, aisle, kind, fit, shelf, size in rows])
    return len(rows)
