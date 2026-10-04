"""D34 replay: run the reference-trust flags (analysis.REF_FLAGS_VERSION) over the saved raw Keepa
responses and size the two candidate policies, so the user can choose between them:

- strict: drop every deal whose reference comes only from third-party New sellers;
- flag:   drop only deals with an inflation flag (above_list, vs_refurb, thin).

Free: it reads research/tracker/raw only (rule 8). Nothing in the feed changes.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import analysis
from .keepa import CONDITIONS
from .tracker import TrackerConfig, qualifies, strict_ref_from_stats

FLAG_ORDER = ("third_party_only", "above_list", "vs_refurb", "thin", "used_cheaper")


def _sent(r: dict) -> float:
    return datetime.fromisoformat(r["request"]["sentAt"]).timestamp()


def check_obs(p: dict, cfg: TrackerConfig) -> dict | None:
    """A check response, reduced the way the tracker sees it: cheapest live Resale unit vs the strict ref."""
    if not p.get("offersSuccessful"):
        return None
    stats = p.get("stats") or {}
    ref, parts = strict_ref_from_stats(stats)
    live = set(p.get("liveOffersOrder") or [])
    prices = [o["offerCSV"][-2] for i, o in enumerate(p.get("offers") or [])
              if o.get("isWarehouseDeal") and i in live and o.get("offerCSV") and (o["offerCSV"][-2] or 0) > 0]
    if not prices:
        return None
    resale = min(prices)
    cur = stats.get("current") or []
    rank = cur[3] if len(cur) > 3 and cur[3] > 0 else None
    strict = analysis.discount(resale, ref)
    windows = [stats.get(k) or [] for k in ("current", "avg", "avg30", "avg90")]
    return {"asin": p.get("asin"), "title": (p.get("title") or "")[:90], "resale": resale, "ref": ref,
            "strict": strict, "qualifies": qualifies(strict, ref, rank, cfg), "parts": parts,
            "f": analysis.ref_flags(windows, ref, resale, [stats.get(k) or [] for k in ("avg180", "avg365")])}


def deal_obs(d: dict, cfg: TrackerConfig) -> dict | None:
    r = analysis.deal_row(d, {}, 0)
    if not r:
        return None
    cur = d.get("current") or []
    rank = cur[3] if len(cur) > 3 and cur[3] > 0 else None
    return {"asin": r.asin, "title": r.title[:90], "resale": r.warehouse_cents, "ref": r.strict_ref_cents,
            "strict": r.strict, "qualifies": qualifies(r.strict, r.strict_ref_cents, rank, cfg),
            "parts": r.ref_parts, "f": r.ref_flags, "cond": r.condition}


def _observations(raw: Path, cfg: TrackerConfig):
    """Every (kind, t, obs) in the archive, oldest first."""
    for f in sorted(raw.glob("*/*.json.gz")):
        k = "check" if "-check-" in f.name else "census" if "-census-" in f.name else None
        if not k:
            continue
        try:
            r = json.loads(gzip.open(f).read())
            t = _sent(r)
        except (OSError, ValueError, KeyError):
            continue
        resp = r.get("response") or {}
        if k == "check":
            p = (resp.get("products") or [None])[0]
            o = p and check_obs(p, cfg)
            if o:
                yield k, t, o
        else:
            for d in (resp.get("deals") or {}).get("dr") or []:
                o = deal_obs(d, cfg)
                if o:
                    yield k, t, o


def flow(raw: Path, cfg: TrackerConfig) -> dict:
    """D35 review burden: per UTC day, ASINs first seen qualifying and first seen held, per layer.
    Approval is per ASIN, so first-held is what lands in the queue."""
    first_q, first_h = {}, {}
    for k, t, o in _observations(raw, cfg):
        if not o["qualifies"]:
            continue
        first_q.setdefault((k, o["asin"]), t)
        if analysis.review_reasons(o["f"], o["strict"]):
            first_h.setdefault((k, o["asin"]), (t, tuple(analysis.review_reasons(o["f"], o["strict"]))))
    day = lambda t: datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
    out: dict = {}
    for (k, _), t in first_q.items():
        out.setdefault((k, day(t)), Counter())["qualifying"] += 1
    for (k, _), (t, why) in first_h.items():
        c = out.setdefault((k, day(t)), Counter())
        c["held"] += 1
        for w in why:
            c[w] += 1
    return out


def flow_section(fl: dict) -> list[str]:
    reasons = ("above_list", "vs_refurb", "thin", "too_good")
    L = ["\n## Review queue flow (newly held ASINs per day)\n",
         "The first time an ASIN qualifies and the first time it would be held; one approval clears an ASIN. "
         "The first day of each layer includes everything already listed when collection started.\n",
         "| layer | day (UTC) | new qualifying | newly held | " + " | ".join(reasons) + " |",
         "|---|---|---|---|" + "---|" * len(reasons)]
    for (k, d), c in sorted(fl.items()):
        L.append(f"| {k} | {d} | {c['qualifying']} | {c['held']} | " + " | ".join(str(c[r]) for r in reasons) + " |")
    return L


def latest(raw: Path, cfg: TrackerConfig, since_hours: float) -> tuple[dict, dict, float]:
    """Newest observation per ASIN in the last `since_hours` of the archive: (checks, census, newest t)."""
    files = sorted(raw.glob("*/*.json.gz"))
    kinds = [(f, "check" if "-check-" in f.name else "census" if "-census-" in f.name else None) for f in files]
    newest = 0.0
    for f, k in reversed(kinds):
        if k:
            newest = _sent(json.loads(gzip.open(f).read()))
            break
    cut = newest - since_hours * 3600
    out = {"check": {}, "census": {}}
    for f, k in kinds:
        if not k:
            continue
        try:
            r = json.loads(gzip.open(f).read())
            t = _sent(r)
        except (OSError, ValueError, KeyError):
            continue
        if t < cut:
            continue
        resp = r.get("response") or {}
        if k == "check":
            p = (resp.get("products") or [None])[0]
            o = p and check_obs(p, cfg)
            if o:
                out[k][o["asin"]] = {**o, "t": t}
        else:
            for d in (resp.get("deals") or {}).get("dr") or []:
                o = deal_obs(d, cfg)
                if o:
                    out[k][o["asin"]] = {**o, "t": t}
    return out["check"], out["census"], newest


def _usd(c):
    return "—" if not c else f"${c / 100:,.2f}"


def _pct(x):
    return "—" if x is None else f"{x:.0%}"


def layer_section(name: str, obs: dict, watch: tuple[str, ...]) -> list[str]:
    q = [o for o in obs.values() if o["qualifies"]]
    head = [o for o in q if o["strict"] >= 0.5]
    near = [o for o in q if o["strict"] < 0.5]
    strict_drop = lambda o: "third_party_only" in o["f"]["flags"]
    flag_drop = lambda o: o["f"]["suspect"]
    L = [f"\n## {name}\n",
         f"{len(obs)} ASINs observed; {len(q)} qualify ({len(head)} headline ≥50%, {len(near)} near miss).\n",
         "| policy | headline dropped | near misses dropped | all dropped |", "|---|---|---|---|"]
    held = lambda o: bool(analysis.review_reasons(o["f"], o["strict"]))
    for label, pred in (("strict: no third-party-only references", strict_drop), ("flag: inflation flags only", flag_drop),
                        (f"review hold ({analysis.REVIEW_RULES_VERSION})", held)):
        h, n = sum(map(pred, head)), sum(map(pred, near))
        L.append(f"| {label} | {h} of {len(head)} ({h / max(len(head), 1):.0%}) | {n} of {len(near)} "
                 f"({n / max(len(near), 1):.0%}) | {h + n} of {len(q)} ({(h + n) / max(len(q), 1):.0%}) |")
    c = Counter(f for o in q for f in o["f"]["flags"])
    L += ["\nFlags among qualifying deals (one deal can carry several):\n", "| flag | deals |", "|---|---|"]
    L += [f"| {f} | {c.get(f, 0)} |" for f in FLAG_ORDER]
    for a in watch:
        o = obs.get(a)
        if o:
            L.append(f"\n- **{a}**: {_pct(o['strict'])} off {_usd(o['ref'])}, flags {o['f']['flags']}, "
                     f"strict drops it: {strict_drop(o)}, flag drops it: {flag_drop(o)}")
    def table(title, rows):
        out = [f"\n### {title}\n", "| ASIN | title | Resale | ref | strict | list | refurb | used | reviews | new offers | flags |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        for o in sorted(rows, key=lambda o: -(o["strict"] or 0))[:15]:
            f = o["f"]
            out.append(f"| [{o['asin']}](https://www.amazon.com/dp/{o['asin']}?aod=1) | {o['title'][:60].replace('|', '/')} "
                       f"| {_usd(o['resale'])} | {_usd(o['ref'])} | {_pct(o['strict'])} | {_usd(f['list'])} "
                       f"| {_usd(f['refurb'])} | {_usd(f['used'])} | {f['reviews'] if f['reviews'] is not None else '—'} "
                       f"| {f['new_offers'] if f['new_offers'] is not None else '—'} | {', '.join(f['flags'])} |")
        return out
    L += table("Flag policy drops (suspect)", [o for o in q if flag_drop(o)])
    L += table("Strict-only drops: third-party-only reference, no inflation flag — real deals or not?",
               [o for o in q if strict_drop(o) and not flag_drop(o)])
    return L


def report(raw: Path, cfg: TrackerConfig, since_hours: float, watch: tuple[str, ...] = ()) -> tuple[str, list[dict]]:
    checks, census, newest = latest(raw, cfg, since_hours)
    when = datetime.fromtimestamp(newest, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"# Reference-trust replay ({analysis.REF_FLAGS_VERSION})\n",
         f"Raw archive up to {when}; newest observation per ASIN in the last {since_hours:g} h. "
         f"Thresholds: above_list > {analysis.REF_ABOVE_LIST:g}× list, vs_refurb > {analysis.REF_VS_REFURB:g}× "
         f"refurbished, thin = third-party-only and < {analysis.THIN_MAX_REVIEWS} reviews and no sales rank. "
         "used_cheaper is information only (it's in neither policy)."]
    L += flow_section(flow(raw, cfg))
    L += layer_section("Tracked feed (latest live check per watched ASIN)", checks, watch)
    L += layer_section("Explore layer (census deal rows)", census, watch)
    rows = [{"layer": "check", **o} for o in checks.values()] + [{"layer": "census", **o} for o in census.values()]
    return "\n".join(L) + "\n", rows
