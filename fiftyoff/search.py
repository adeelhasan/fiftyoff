"""Word matching shared by search (api_v1, trust-first §4.1) and keyword alerts (notify, k0.1), so an alert's
keyword means exactly what the same words mean in the header search."""

from __future__ import annotations

import re

WORD = re.compile(r"[a-z0-9]+")


def words(*texts: str | None) -> frozenset[str]:
    return frozenset(w for t in texts if t for w in WORD.findall(t.lower()))


def matches(q: str, index: frozenset[str]) -> bool:
    """trust-first §4.1: every query word starts some word of the title or brand ("sony wh" finds "Sony WH-1000XM5")."""
    terms = WORD.findall(q.lower())
    return bool(terms) and all(any(w.startswith(t) for w in index) for t in terms)
