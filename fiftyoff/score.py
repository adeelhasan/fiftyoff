"""Deal score: how attractive a Resale unit is, 0-100 (D28). Internal ranking only.

The inputs include signals we may not show (reference price, reviews, sales-rank drops; D19), so the
API emits the score and never the inputs. Versioned so a ranking can be replayed (rule 8).

score = 100 x condition factor x weighted mean of:
- discount: strict % off, 30% -> 0, 75%+ -> 1
- demand:   mean of what's known: review count (10k -> 1), sales-rank drops in 30 days (30 -> 1),
            bought last month (1k -> 1), Amazon itself sells it
- savings:  $ saved on a log scale ($10 -> 0, $100 -> 0.5, $1,000+ -> 1)
- rating:   3.5 stars -> 0, 5 -> 1
"""

from __future__ import annotations

import math
import re

SCORE_VERSION = "s0.2"  # s0.2: $ saved weighs more, so big-ticket deals beat cheap ones at a slightly higher %
WEIGHTS = {"discount": 0.40, "demand": 0.25, "savings": 0.25, "rating": 0.10}
CONDITION_FACTOR = {"Used - Like New": 1.0, "Used - Very Good": 0.92, "Used - Good": 0.75,
                    "Used - Acceptable": 0.55}
UNKNOWN_DEMAND, UNKNOWN_RATING = 0.3, 0.5


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def parts(r: dict) -> dict[str, float]:
    strict = r.get("strict") or 0.0
    demand = []
    if r.get("reviews") is not None:
        demand.append(_clamp(math.log10(r["reviews"] + 1) / 4))
    if r.get("drops30") is not None:
        demand.append(_clamp(r["drops30"] / 30))
    if r.get("monthly_sold"):
        demand.append(_clamp(math.log10(r["monthly_sold"]) / 3))
    if r.get("amazon_sells") is not None:
        demand.append(1.0 if r["amazon_sells"] else 0.0)
    saved = ((r.get("ref_cents") or 0) - (r.get("resale_cents") or 0)) / 100
    return {
        "discount": _clamp((strict - 0.30) / 0.45),
        "demand": sum(demand) / len(demand) if demand else UNKNOWN_DEMAND,
        "savings": _clamp(math.log10(saved / 10) / 2) if saved > 10 else 0.0,
        "rating": _clamp((r["rating"] - 3.5) / 1.5) if r.get("rating") else UNKNOWN_RATING,
    }


def score(r: dict) -> int:
    p = parts(r)
    base = sum(WEIGHTS[k] * p[k] for k in WEIGHTS)
    return round(100 * CONDITION_FACTOR.get(r.get("cond"), 0.6) * base)


def breakdown(r: dict) -> dict:
    """Points each part contributes (they sum to the score, before rounding), plus the condition factor.
    Derived numbers only: safe to show, unlike the raw inputs (D19)."""
    p, cf = parts(r), CONDITION_FACTOR.get(r.get("cond"), 0.6)
    return {**{k: round(100 * cf * WEIGHTS[k] * p[k], 1) for k in WEIGHTS}, "condition_factor": cf}


def image_url(image) -> str | None:
    """Keepa's deal `image` is a list of char codes ("41RgPV8KZL.jpg"); Postgres stored it as the
    text "{52,49,...}". Either form -> an Amazon image URL."""
    if not image:
        return None
    if isinstance(image, str):
        if not image.startswith("{"):
            name = image
        else:
            name = "".join(chr(int(c)) for c in re.findall(r"\d+", image))
    else:
        name = "".join(chr(c) for c in image)
    return f"https://m.media-amazon.com/images/I/{name}" if re.fullmatch(r"[\w.+-]+\.(jpg|png|gif)", name) else None
