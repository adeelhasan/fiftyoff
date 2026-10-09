"""Live confidence: how likely a Resale unit is still available right now (D30).

Not the rule-9 timing label on gone units: this one is about display. Every unit decays from its last
confirmed sighting, faster when it's the kind of deal that sells fast:

    p = exp(-hours since last confirmed / tau) x (UNCONFIRMED_FACTOR if our last check missed it)

- tau = HOT_TAU_H for a hot deal: 50%+ off and priced in the last HOT_PRICED_H hours, the same window
  in which the tracker checks it every 15 min (a fresh price drop to a steal: one observed on 2026-10-02 sold within ~2.5 h).
- tau = SETTLED_TAU_H otherwise: listings that have sat at this price for 6 h or more.
- A failed refresh adds no information, so it changes nothing here: the age keeps growing.

HIGH >= 0.8, MEDIUM >= 0.5, LOW below. The feed holds back LOW by default. The taus are a first guess;
calibrate them from measured lifespans (gone units with HIGH/MEDIUM timing) and sightings. Versioned (rule 8).
"""

from __future__ import annotations

import math
from datetime import datetime

CONFIDENCE_VERSION = "c0.3"  # c0.2: "hot" window 24 h -> 6 h, matching the tracker's fast lane (NEW_WINDOW)
                             # c0.3 (D43): settled tau 24 h -> 48 h, as settled deals are re-checked daily
                             # (LOW after ~33 h without a sighting instead of ~17 h; 9 of ~450 went overnight)
HOT_TAU_H, SETTLED_TAU_H, HOT_PRICED_H = 3.0, 48.0, 6.0
HEADLINE = 0.50
UNCONFIRMED_FACTOR = 0.35
HIGH, MEDIUM = 0.8, 0.5
RANK = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}


def live_confidence(r: dict, now: datetime) -> dict:
    age_h = max(0.0, (now - r["last_confirmed_at"]).total_seconds() / 3600)
    priced = r.get("priced_at")
    hot = (r.get("strict") or 0) >= HEADLINE and priced is not None \
        and (now - priced).total_seconds() / 3600 < HOT_PRICED_H
    p = math.exp(-age_h / (HOT_TAU_H if hot else SETTLED_TAU_H))
    if r.get("unconfirmed"):
        p *= UNCONFIRMED_FACTOR
    label = "HIGH" if p >= HIGH else "MEDIUM" if p >= MEDIUM else "LOW"
    return {"p": round(p, 2), "label": label, "hot": hot}
