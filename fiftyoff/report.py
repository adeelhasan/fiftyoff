"""Renders research/preflight-report.md (plan §5) from census rows, history results and the ledger."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from . import analysis
from .keepa import keepa_to_iso


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


def _usd(cents: int | None) -> str:
    return "—" if not cents or cents < 0 else f"${cents / 100:,.2f}"


def _hours(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    return f"{minutes:.0f}m" if minutes < 60 else f"{minutes / 60:.1f}h"


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _counter_table(title: str, c: Counter, order: list[str] | None = None) -> str:
    keys = order or [k for k, _ in c.most_common()]
    total = sum(c.values()) or 1
    return _table([title, "count", "share"], [[k, c.get(k, 0), _pct(c.get(k, 0) / total)] for k in keys if c.get(k)])


def candidates_md(picked: list[dict]) -> str:
    rows = [[c["asin"], c["cohort"], c["bucket"], _pct(c.get("strict")), c.get("strict_key"),
             _usd(c.get("strict_ref_cents")), _usd(c.get("warehouse_cents")), c.get("condition"),
             c.get("title", "")[:70]] for c in picked]
    return ("# Proposed history sample\n\nApprove by setting `\"approved\": true` in candidates.json.\n\n"
            + _table(["ASIN", "cohort", "bucket", "strict disc.", "ref used", "ref price", "warehouse",
                      "condition", "title"], rows) + "\n")


SAMPLE_BIAS = {
    "A-best-deals": "Selected as the steepest strict discounts now. These skew to obscure, slow-selling SKUs, "
                    "which Keepa refreshes rarely, so this sample *understates* history quality for desirable products.",
    "B-popular (D14)": "Selected as the best-selling items among strict-50%+ deals in plan categories. Keepa refreshes "
                       "these most often, so this is close to the *best case* for history. Every item was discounted "
                       "when selected, so recurrence is overstated relative to a random product.",
}


def render(rows, meta, samples, ledger, cfg) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    s = analysis.census_summary(rows) if rows else None
    L = [f"# fiftyoff pre-flight report\n",
         f"Generated {now}. Discount formula `{analysis.DISCOUNT_FORMULA_VERSION}`, "
         f"episode algorithm `{analysis.EPISODE_ALGO_VERSION}`. Regenerate with `uv run preflight.py report`.\n",
         "## Suggested decision (pre-registered rule D5, per sample)\n"]
    if not samples:
        L.append(f"**{analysis.suggest_decision(len(rows), [])[0]}**: no history sample analysed yet.\n")
    for smp in samples:
        decision, why = analysis.suggest_decision(len(rows), smp["results"])
        L.append(f"- **{smp['name']}: {decision}**: {why}. {SAMPLE_BIAS.get(smp['name'], '')}")
    L.append("\nThese are mechanical results of docs/DECISIONS.md D5. The final call, and `research:unlock`, "
             "are yours. With n=15 per sample, read the counts, not just the percentages.\n")

    # ---- token usage
    L.append("## Token usage (exact, from ledger)\n")
    by = defaultdict(lambda: [0, 0])
    for e in ledger:
        k = "probe" if e["label"] == "probe" else e["endpoint"]
        by[k][0] += 1
        by[k][1] += e.get("tokensConsumed") or 0
    L.append(_table(["call type", "requests", "tokens"], [[k, n, t] for k, (n, t) in by.items()]
                    + [["**total**", sum(v[0] for v in by.values()), sum(v[1] for v in by.values())]]))
    deal_costs = sorted({e.get("tokensConsumed") for e in ledger if e["endpoint"] == "deal"} - {None})
    L.append(f"\nPF5 — observed cost of one /deal page: {deal_costs or '—'} tokens.\n")

    # ---- census
    L.append("## A. Current-market discovery (census)\n")
    L.append(_census_section(rows, meta, s))

    # ---- history
    if not samples:
        L.append("## B/C. Historical feasibility\n\n_No history sample analysed yet._\n")
    for smp in samples:
        L.append(f"## B/C. Historical feasibility — sample {smp['name']}\n")
        L.append(f"Candidates: `{smp['file']}`. Raw: `{smp['run']}`.\n")
        L.append(_history_section(smp["results"], cfg))

    L.append("## Unresolved data-quality concerns\n")
    L.append(_concerns([r for smp in samples for r in smp["results"]]))
    return "\n".join(L)


def _census_section(rows, meta, s) -> str:
    L = []
    counts = meta.get("counts") or {}
    if counts:
        L.append("All counts are Keepa's **nominal** discount (Resale price vs the 48h marketplace-New average), "
                 "for Resale listings **whose price changed in the last day**. It's a change feed, not a snapshot "
                 "of live supply (RQ1), and not a real discount (see the deflation table).\n")
        L.append("### Supply curve — nominal matches per query (PF3/PF6)\n")
        names = list(counts)
        L.append(_table(["query", "matches", "pages to fetch all"],
                        [[n, f"{counts[n]['total']:,}", f"{-(-counts[n]['total'] // 150):,}"] for n in names]))
        cats = sorted(counts.get("n50", counts[names[0]])["by_cat"].items(), key=lambda kv: -kv[1])
        cols = [n for n in ("n25", "n50", "n70", "n50-min20", "n50-min125", "n50-min20-lnvg",
                            "n50-min20-single", "n50-min20-week") if n in counts]
        L.append("\n### By root category\n")
        L.append(_table(["category"] + cols, [[c] + [f"{counts[q]['by_cat'].get(c, 0):,}" for q in cols]
                                               for c, _ in cats]))
    if not s:
        L.append("\n_No sample rows yet._\n")
        return "\n".join(L)

    L.append(f"\n### Sample: {s['asins']} Resale listings re-priced strictly ({s['parents']} parent families)\n")
    for name, info in (meta.get("samples") or {}).items():
        trunc = " — more pages exist" if info.get("last_full") else ""
        L.append(f"- `{name}`: {info.get('pages')} pages of {info.get('total', '?'):,} matches{trunc}; "
                 f"query `{info.get('query')}`")
    L.append("\n### PF22/PF23 — deflation: nominal 50%+ that survive the strict reference, by category\n")
    L.append("Strict = the lowest of: Amazon now, New now, and the 48h/30d/90d averages of each. "
             "Est. strict supply = the `n50-min20` count × survival rate (same filters, media excluded in the sample).\n")
    by_cat = {}
    for r in rows:
        if (r.keepa_reported or 0) >= 50:
            d = by_cat.setdefault(r.root_cat, [0, 0, 0])
            d[0] += 1
            d[1] += (r.strict or 0) >= 0.5
            d[2] += r.condition in ("Used - Like New", "Used - Very Good")
    n20 = (counts.get("n50-min20") or {}).get("by_cat", {})
    dt = []
    for cat, (n, ok, lnvg) in sorted(by_cat.items(), key=lambda kv: -kv[1][1]):
        est = round(n20.get(cat, 0) * ok / n) if n else 0
        dt.append([cat, n, ok, _pct(ok / n), f"{n20.get(cat, 0):,}", f"~{est:,}", _pct(lnvg / n)])
    tot_n = sum(v[0] for v in by_cat.values()) or 1
    tot_ok = sum(v[1] for v in by_cat.values())
    dt.append(["**all**", tot_n, tot_ok, _pct(tot_ok / tot_n), "", "", ""])
    L.append(_table(["category", "sampled nominal 50%+", "strict 50%+", "survival", "nominal count (n50-min20)",
                     "est. strict supply", "Like New/VG"], dt))
    L.append("\n### PF22 — which reference Keepa's number matches\n")
    L.append(_counter_table("Keepa matches", s["keepa_ref_match"]))
    L.append("\n### Strict discount distribution (sample)\n")
    order = [analysis.bucket_label(b) for b in analysis.CENSUS_BUCKETS] + ["<25%", "no reference"]
    L.append(_counter_table("strict discount", s["strict_buckets"], order))
    L.append("\n### PF2 — condition (cheapest Resale offer)\n")
    L.append(_counter_table("condition", s["conditions"]))
    L.append("\n### RQ4 preview — normal-price bands of strict-50%+ deals\n")
    L.append(_counter_table("reference price", s["price_bands_50"], ["<$40", "$40+", "$100+", "$250+", "$500+"]))
    L.append(f"\n### PF25–27 — variation inflation (sample)\n\n{s['asins']} ASINs → {s['parents']} parent families "
             f"({_pct(1 - s['parents'] / s['asins'])} inflation). Largest families:\n")
    fam_rows = []
    for parent, members in s["families"][:10]:
        prices = [m["warehouse_cents"] for m in members]
        fam_rows.append([parent, len(members), f"{_usd(min(prices))}–{_usd(max(prices))}", members[0]["title"][:60]])
    L.append(_table(["parent", "ASINs", "Resale price range", "example title"], fam_rows))
    best = sorted((r for r in rows if r.strict is not None and (r.strict_ref_cents or 0) >= 4000),
                  key=lambda r: -r.strict)[:30]
    L.append("\n### Best deals right now (strict, reference ≥ $40)\n")
    L.append(_table(["ASIN", "category", "strict", "Keepa says", "strict ref", "Resale price", "you save",
                     "condition", "title"],
                    [[r.asin, r.root_cat, _pct(r.strict), f"{r.keepa_reported}%", f"{_usd(r.strict_ref_cents)} ({r.strict_key})",
                      _usd(r.warehouse_cents), _usd((r.strict_ref_cents or 0) - r.warehouse_cents), r.condition,
                      r.title[:60]] for r in best]))
    return "\n".join(L) + "\n"


def _history_section(results, cfg) -> str:
    ths = cfg["analysis"]["thresholds"]
    n = len(results)
    L = []
    rows = []
    for r in results:
        eps50 = r.aggregate_episodes.get(0.5, [])
        rows.append([r.asin, r.category, _pct(r.current_discount), "✓" if r.aggregate_found else "✗",
                     r.offers_found, f"{r.offers_with_condition}/{r.offers_found}",
                     len(eps50), "✓" if r.recurrence_usable else "✗",
                     "✓" if r.lifespan_usable else "✗", r.confidence, r.tokens])
    L.append("### Per-product summary (plan §5)\n")
    L.append(_table(["ASIN", "cohort", "current disc.", "agg. WAREHOUSE", "hist. WH offers",
                     "condition known", "50%+ episodes", "recurrence usable", "lifespan usable",
                     "confidence", "tokens"], rows))

    L.append("\n### Observation density (the gate for lifespan)\n\nWhen Keepa actually re-fetched offers "
             "(csv EXTRA_INFO_UPDATES). A change can only be timed to within one gap.\n")
    L.append(_table(["ASIN", "observations", "median gap", "p90 gap", "max gap", "csv9 on obs time",
                     "ref coverage", "offers retrieved/total", "live WH offer", "not recurrence-usable because"],
                    [[r.asin, r.gaps["n_obs"], _hours(r.gaps["median_gap_min"]), _hours(r.gaps["p90_gap_min"]),
                      _hours(r.gaps["max_gap_min"]), _pct(r.csv9_aligned_with_obs), _pct(r.ref_coverage),
                      f"{r.retrieved_offer_count}/{r.total_offer_count}", "✓" if r.live_warehouse_offer else "✗",
                      "; ".join(r.recurrence_reasons) or "—"] for r in results]))
    meds = [r.gaps["median_gap_min"] for r in results if r.gaps["median_gap_min"] is not None]
    if meds:
        meds.sort()
        L.append(f"\nMedian of per-product median gaps: **{_hours(meds[len(meds) // 2])}**. If this is "
                 f"hours or more, the <10 min / 10–30 min bands (PF16) cannot be answered from history.\n")

    L.append("### PF15/PF19 — recurrence: aggregate (Method A) vs offer-level (Method B)\n")
    rec_rows = []
    for r in results:
        rec_rows.append([r.asin] + [f"{len(r.aggregate_episodes.get(t, []))} / {r.offer_episodes.get(t, 0)}"
                                    for t in ths]
                        + [keepa_to_iso(max((e.start for e in r.aggregate_episodes.get(0.5, [])), default=None))])
    L.append(_table(["ASIN"] + [f"{int(t * 100)}%+ (A / B)" for t in ths] + ["last 50%+ start"], rec_rows))
    L.append("\nMethod B counts episodes per individual Warehouse offer, so several units listed at once "
             "count separately. A ≪ B suggests aggregate history merges overlapping units; A ≫ B suggests "
             "offer histories are incomplete (Keepa only keeps the offers it fetched).\n")

    L.append("### PF9/PF20 — condition in offer-level episodes\n")
    L.append(_table(["ASIN"] + [f"{int(t * 100)}%+" for t in ths],
                    [[r.asin] + [", ".join(f"{k}: {v}" for k, v in r.offer_conditions_in_episodes.get(t, {}).items()) or "—"
                                 for t in ths] for r in results]))

    L.append("\n### PF12–PF16 — reconstructed example timelines (aggregate, 50%+)\n")
    ex = []
    for r in results:
        for e in r.aggregate_episodes.get(0.5, [])[:4]:
            ex.append([r.asin, keepa_to_iso(e.start) + (" (≤ window start)" if e.left_censored else ""),
                       keepa_to_iso(e.end) if e.end else "still active", e.end_reason or "—",
                       _pct(e.best_discount), _hours(e.start_uncertainty), _hours(e.end_uncertainty),
                       f"{_hours(e.lifespan_min)}–{_hours(e.lifespan_max)}" if e.lifespan_min is not None else "—",
                       e.lifespan_band or "—", e.confidence])
    L.append(_table(["ASIN", "start", "end", "end reason (PF14)", "best disc.", "start ±", "end ±",
                     "lifespan range", "PF16 band", "confidence"], ex[:40]) if ex else "_No 50%+ episodes._")

    bands = Counter()
    conf = Counter()
    for r in results:
        for eps in r.aggregate_episodes.values():
            for e in eps:
                conf[e.confidence] += 1
                if e.end is not None:
                    bands[e.lifespan_band or "spans bands (indeterminate)"] += 1
    L.append("\n### PF16 — lifespan bands across all thresholds (closed episodes)\n")
    L.append(_counter_table("band", bands, [b[0] for b in analysis.LIFESPAN_BANDS] + ["spans bands (indeterminate)"]))
    L.append("\n### Episode confidence (§12)\n")
    L.append(_counter_table("confidence", conf, ["HIGH", "MEDIUM", "LOW", "OPEN"]))

    rec = sum(r.recurrence_usable for r in results)
    life = sum(r.lifespan_usable for r in results)
    L.append(f"\n### PF17/PF18\n\n- Recurrence-usable: **{rec}/{n}** ({_pct(rec / n)})\n"
             f"- Lifespan-usable: **{life}/{n}** ({_pct(life / n)})\n"
             "- Definitions: docs/DECISIONS.md D11.\n")
    return "\n".join(L)


def _concerns(results) -> str:
    items = [
        "Warehouse `deltaPercent` is computed against \"the Amazon or New price\"; the PF22 table shows which one in practice.",
        "Deal-query `warehouseConditions` documents Good as 24, while the deal object uses 4. The census does not filter by condition.",
        "NEW/USED csv series switched from listing price to landing price (incl. shipping) on 2026-02-23. Runs after 2026-08-22 have a 180-day window entirely after that date.",
    ]
    missing = [r.asin for r in results if not r.live_warehouse_offer]
    if missing:
        items.append(f"No live `isWarehouseDeal` offer returned for {len(missing)} sampled ASIN(s) ({', '.join(missing)}). "
                     "Either the unit sold, or it fell outside the offers=N cutoff (see retrieved/total).")
    return "\n".join(f"- {i}" for i in items) + "\n"
