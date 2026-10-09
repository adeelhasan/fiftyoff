"""Which shelf a product sits on (D45/D46), shared by the shelves page and the notifier.

The rater (rubric a0.3) names a shelf id; older ratings only name a kind, which kind_map turns into a shelf.
Anything else lands on the "just in" shelf.
"""

from __future__ import annotations

UNSORTED = "just-in"  # D45: the shelf for products not rated yet


def resolve_shelf(appeal: dict | None, kind_map: dict[str, str], shelves: dict[str, dict]) -> str:
    """appeal: the product's appeal row (or None); kind_map: kind -> shelf id; shelves: shelf id -> shelf row."""
    a = appeal or {}
    sid = a.get("shelf") if a.get("shelf") in shelves else kind_map.get(a.get("kind") or "")
    return sid if sid in shelves else UNSORTED
