"""History sample (D3 as revised by D13): the best deals found now, by strict discount.

The user approves the list before any history spend.
"""

from __future__ import annotations

from dataclasses import asdict

from .analysis import DealRow, bucket_label


def propose(rows: list[DealRow], target: int = 15, min_ref_cents: int = 4000,
            max_per_category: int = 4) -> list[dict]:
    """Highest strict discount first, one ASIN per parent family, capped per root category."""
    ranked = sorted(
        (r for r in rows if r.strict is not None and (r.strict_ref_cents or 0) >= min_ref_cents),
        key=lambda r: (-r.strict, -(r.strict_ref_cents or 0)),
    )
    picked: list[dict] = []
    parents: set[str] = set()
    per_cat: dict[str, int] = {}
    for r in ranked:
        if len(picked) >= target:
            break
        if r.parent in parents or per_cat.get(r.root_cat, 0) >= max_per_category:
            continue
        parents.add(r.parent)
        per_cat[r.root_cat] = per_cat.get(r.root_cat, 0) + 1
        picked.append({"cohort": r.root_cat, "bucket": bucket_label(r.strict), **asdict(r)})
    return picked
