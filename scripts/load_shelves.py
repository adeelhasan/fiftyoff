"""Load shelves and the kind map (D46) into the database on the VPS.

    uv run scripts/load_shelves.py VERSION   # reads fiftyoff/shelves.tsv and fiftyoff/kind_map.tsv

shelves.tsv: id, name, aisle, proposed role, reason, product count. kind_map.tsv: kind, shelf id.
A shelf whose role the user already set keeps it; otherwise its role is the model's proposal. Shelves that are
no longer in the file stay in the table (ids are permanent) but get no new kinds.
"""
import csv
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent / "fiftyoff"
ROLES = {"front", "aisle", "hidden"}


def main() -> None:
    version = sys.argv[1]
    shelves = [line.split("\t") for line in (ROOT / "shelves.tsv").read_text().splitlines() if line.strip()]
    kinds = [line.split("\t") for line in (ROOT / "kind_map.tsv").read_text().splitlines() if line.strip()]
    ids = {s[0] for s in shelves}
    aisle = {s[0]: s[2] for s in shelves}
    assert all(s[3] in ROLES for s in shelves), "bad role"
    assert all(k[1] in ids for k in kinds), "kind mapped to an unknown shelf"
    sb, kb = io.StringIO(), io.StringIO()
    csv.writer(sb, lineterminator="\n").writerows([[s[0], s[1], s[2], s[3], s[3], s[4], version] for s in shelves])
    csv.writer(kb, lineterminator="\n").writerows([[k[0], k[1], aisle[k[1]], version] for k in kinds])
    script = (
        "BEGIN;\nCREATE TEMP TABLE s (id text, name text, aisle text, role text, proposed_role text, role_reason text, version text);\n"
        "\\copy s FROM STDIN WITH (FORMAT csv)\n" + sb.getvalue() + "\\.\n"
        "INSERT INTO shelf (id, name, aisle, role, proposed_role, role_reason, version) SELECT * FROM s "
        "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, aisle = EXCLUDED.aisle, proposed_role = EXCLUDED.proposed_role, "
        "role_reason = EXCLUDED.role_reason, version = EXCLUDED.version, "
        "role = CASE WHEN shelf.updated_by IS NULL THEN EXCLUDED.proposed_role ELSE shelf.role END;\n"
        "DELETE FROM kind_map;\n\\copy kind_map (kind, shelf, aisle, version) FROM STDIN WITH (FORMAT csv)\n"
        + kb.getvalue() + "\\.\nCOMMIT;\n")
    out = subprocess.run(["ssh", "fiftyoff-vps", "cd fiftyoff-app && docker compose exec -T db psql -U fiftyoff -d fiftyoff "
                          "-v ON_ERROR_STOP=1 -q"], input=script, text=True, capture_output=True)
    if out.returncode:
        sys.exit(out.stderr)
    print(f"{len(shelves)} shelves, {len(kinds)} kinds ({version})")


if __name__ == "__main__":
    main()
