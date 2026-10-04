"""Human curation (D36), kept apart from the rules' own `review` state (D35).

`review` is machine state: the tracker moves it between pending (held) and cleared. `curation` is the
admin's decision per ASIN: `auto` (the rules decide), `approved` (list even if held) or `hidden` (never
list), plus channel tags and a note. Every change is logged (`curation_log`): the audit trail, and
labelled data for tuning the rules.

`listed` is the spec; the `unlisted` view in store_pg.py mirrors it in SQL. Keep them in sync.
"""

from __future__ import annotations

from .tracker import REVIEW_REOPEN

VISIBILITY = ("auto", "approved", "hidden")
NOTE_MAX = 500
DEFAULT_TAGS = ("featured", "newsletter")


def within(decided_ref: int | None, ref: int | None) -> bool:
    """An approval holds while the reference stays within 20% of where it was made. No baseline fails
    closed: the deal needs a fresh look."""
    return bool(decided_ref and ref) and abs(ref - decided_ref) / decided_ref <= REVIEW_REOPEN


def listed(visibility: str | None, review_status: str | None, decided_ref: int | None, ref: int | None) -> bool:
    if visibility == "hidden":
        return False
    if review_status != "pending":
        return True
    return visibility == "approved" and within(decided_ref, ref)


def apply(current: dict | None, change: dict, allowed_tags, ref: int | None) -> tuple[dict, list[tuple]]:
    """New curation row + log entries (field, old, new) for one admin change. `ref` is the deal's current
    reference, stamped as the baseline when approving. Raises ValueError on a bad change."""
    cur = current or {"visibility": "auto", "tags": [], "note": None, "decided_ref_cents": None}
    new = {**cur, "tags": list(cur.get("tags") or [])}
    unknown = set(change) - {"visibility", "tags_add", "tags_remove", "note"}
    if unknown or not change:
        raise ValueError(f"unknown or empty change: {sorted(unknown)}")
    if "visibility" in change:
        v = change["visibility"]
        if v not in VISIBILITY:
            raise ValueError(f"visibility must be one of {VISIBILITY}")
        new["visibility"] = v
        # re-approving refreshes the baseline (that's how a lapsed approval is renewed)
        new["decided_ref_cents"] = ref if v == "approved" else None
    for key in ("tags_add", "tags_remove"):
        tags = change.get(key) or []
        if not isinstance(tags, list) or any(t not in allowed_tags for t in tags):
            raise ValueError(f"tags must be from {list(allowed_tags)}")
    new["tags"] = sorted((set(new["tags"]) | set(change.get("tags_add") or [])) - set(change.get("tags_remove") or []))
    if "note" in change:
        note = (change["note"] or "").strip() or None
        if note and len(note) > NOTE_MAX:
            raise ValueError("note too long")
        new["note"] = note
    log = [(f, _s(cur.get(f)), _s(new[f])) for f in ("visibility", "tags", "note", "decided_ref_cents")
           if _s(cur.get(f)) != _s(new[f])]
    return new, log


def _s(v) -> str | None:
    if v is None:
        return None
    return ",".join(v) if isinstance(v, list) else str(v)
