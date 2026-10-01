"""fiftyoff Keepa pre-flight. Manual use only — see CLAUDE.md and docs/PREFLIGHT.md.

    uv run preflight.py probe                  # free: token balance + refill rate
    uv run preflight.py census   [--dry-run]   # PF1–PF6: Warehouse deal census (asks [y/N])
    uv run preflight.py propose                # offline: stratified sample -> research/candidates.json
    uv run preflight.py history  [--dry-run]   # PF7–PF21 on the APPROVED sample (asks [y/N])
    uv run preflight.py report                 # offline: research/preflight-report.md

`--fixtures DIR` swaps Keepa for saved JSON (zero cost); output then goes to research/fixture-run/.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from fiftyoff import analysis, report, sampling
from fiftyoff.keepa import (
    DEAL_PAGE_COST,
    DEAL_PAGE_SIZE,
    DOMAIN_US,
    FixtureTransport,
    Keepa,
    KeepaError,
    Ledger,
    LiveTransport,
    history_offer_cost,
    load_api_key,
    unix_to_keepa,
)

PROBE_ASIN = "B000000000"  # absent from Keepa's DB -> documented 0-token request with update=-1


def load_config(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def confirm(prompt: str, input_fn=input) -> bool:
    return input_fn(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class Ctx:
    def __init__(self, args, input_fn=input):
        self.cfg = load_config(Path(args.config))
        self.fixtures = Path(args.fixtures) if args.fixtures else None
        self.root = Path(args.root or ("research/fixture-run" if self.fixtures else "research"))
        self.ledger = Ledger(self.root / "token-ledger.jsonl")
        self.input_fn = input_fn
        self.dry_run = getattr(args, "dry_run", False)

    def client(self, phase: str) -> Keepa:
        transport = FixtureTransport(self.fixtures) if self.fixtures else LiveTransport(load_api_key())
        return Keepa(transport, self.ledger, self.root / "raw" / phase / run_id(),
                     self.cfg["budget"]["token_cap"])

    def confirm(self, prompt: str) -> bool:
        return confirm(prompt, self.input_fn)


def probe(keepa: Keepa) -> None:
    # Keepa includes the token bucket even in error responses, so a rejected probe still tells
    # us the balance. It must never block the paid step behind it.
    try:
        keepa.call("product", label="probe", estimate=1,
                   params={"domain": DOMAIN_US, "asin": PROBE_ASIN, "update": -1, "history": 0})
    except KeepaError as e:
        print(f"  (probe returned an error, continuing: {e})")
    last = keepa.ledger.entries()[-1] if keepa.ledger.entries() else {}
    print(f"  Keepa balance: {keepa.tokens_left} tokens, refill {keepa.refill_rate}/min "
          f"(probe consumed {last.get('tokensConsumed')})")


def budget_line(ctx: Ctx) -> str:
    spent = ctx.ledger.spent()
    cap = ctx.cfg["budget"]["token_cap"]
    return f"pre-flight budget: {spent} spent of {cap} cap ({cap - spent} left)"


# ---------------------------------------------------------------- commands

def cmd_probe(ctx: Ctx) -> int:
    probe(ctx.client("probe"))
    print(" ", budget_line(ctx))
    return 0


# Root categories whose "new" references are dominated by textbook/collector pricing (page-0 evidence).
MEDIA_ROOTS = [283155, 5174, 2625373011]  # Books, CDs & Vinyl, Movies & TV
PRICE_CEILING = 100_000_00  # $100k: effectively open-ended


def deal_query(cfg: dict, q: dict, page: int) -> dict:
    c = cfg["census"]
    body = {
        "page": page,
        "domainId": DOMAIN_US,
        "priceTypes": [9],  # WAREHOUSE (= Amazon Resale)
        "dateRange": q.get("date_range", c["date_range"]),
        "isRangeEnabled": True,
        "deltaPercentRange": [q.get("min_delta", 25), 100],
        "isFilterEnabled": True,
        "filterErotic": True,
        "singleVariation": q.get("single_variation", False),
        "sortType": q.get("sort", 1),
    }
    if q.get("min_price"):
        body["currentRange"] = [q["min_price"], PRICE_CEILING]
    if q.get("exclude_media"):
        body["excludeCategories"] = MEDIA_ROOTS
    if q.get("warehouse_conditions"):
        body["warehouseConditions"] = q["warehouse_conditions"]
    return body


def cmd_census(ctx: Ctx, only: list[str] | None = None) -> int:
    """Runs the named queries in preflight.toml [[census.queries]].

    mode "counts": page 0 only — Keepa's categoryCount gives the query's total per root category.
    mode "sample": up to `pages` pages; these rows feed the discount/condition/variation stats.
    """
    c = ctx.cfg["census"]
    queries = [q for q in c["queries"] if not only or q["name"] in only]
    plan = [(q, 1 if q["mode"] == "counts" else q["pages"]) for q in queries]
    pages = sum(n for _, n in plan)
    cost = pages * DEAL_PAGE_COST
    print("CENSUS — Keepa /deal, priceType WAREHOUSE (Amazon Resale), amazon.com")
    for q, n in plan:
        extras = {k: v for k, v in q.items() if k not in ("name", "mode", "pages")}
        print(f"  {q['name']:<16} {q['mode']:<7} {n:>2} page(s)  {extras}")
    print(f"  worst case: {pages} pages = {cost} tokens (sample queries stop early on a short page)")
    print(" ", budget_line(ctx))
    if pages > c["max_pages"]:
        print(f"  refusing: {pages} pages exceeds census.max_pages ({c['max_pages']}).")
        return 1
    if ctx.dry_run:
        print("  --dry-run: no requests made.")
        return 0
    keepa = ctx.client("census")
    probe(keepa)
    if not ctx.confirm(f"Spend up to {cost} tokens on {pages} census pages?"):
        print("aborted.")
        return 1
    for q, n in plan:
        kind = "cnt" if q["mode"] == "counts" else "smp"
        for page in range(n):
            data = keepa.call("deal", label=f"{kind}-{q['name']}-p{page}", estimate=DEAL_PAGE_COST,
                              body=deal_query(ctx.cfg, q, page))
            deals = data.get("deals") or {}
            got = len(deals.get("dr") or [])
            if page == 0:
                print(f"  {q['name']:<16} total {sum(deals.get('categoryCount') or []):>7}  "
                      f"(page 0: {got} rows, {data.get('tokensConsumed')} tokens)")
            if got < DEAL_PAGE_SIZE:
                break
    print(" ", budget_line(ctx))
    return 0


def all_runs(root: Path, phase: str) -> list[Path]:
    d = root / "raw" / phase
    return sorted(d.glob("*/")) if d.exists() else []


def latest_run(root: Path, phase: str) -> Path | None:
    runs = all_runs(root, phase)
    return runs[-1] if runs else None


def raw_files(run: Path | None, endpoint: str) -> list[dict]:
    if run is None:
        return []
    out = []
    for f in sorted(run.glob("*.json")):
        rec = json.loads(f.read_text())
        if rec["request"]["endpoint"] == endpoint and rec["status"] == 200 and "probe" not in f.name:
            rec["label"] = f.stem.split("-", 1)[1]
            out.append(rec)
    return out


def parse_label(label: str) -> tuple[str, str, int] | None:
    if label == "deal-p0":  # first live run: identical to the n25 counts query
        return "cnt", "n25", 0
    if not label.startswith(("cnt-", "smp-")):
        return None
    kind, rest = label.split("-", 1)
    name, page = rest.rsplit("-p", 1)
    return kind, name, int(page)


def load_census(root: Path) -> tuple[list[analysis.DealRow], dict]:
    """Merges every census run; the latest page for each (query, page) wins."""
    latest: dict[tuple[str, str, int], dict] = {}
    for run in all_runs(root, "census"):
        for rec in raw_files(run, "deal"):
            key = parse_label(rec["label"])
            if key:
                latest[key] = rec
    rows: dict[str, analysis.DealRow] = {}
    meta = {"counts": {}, "samples": {}, "date_range": ctx_date_range(latest)}
    for (kind, name, page), rec in sorted(latest.items()):
        body = rec["request"]["body"]
        deals = rec["response"].get("deals") or {}
        names = dict(zip(deals.get("categoryIds") or [], deals.get("categoryNames") or []))
        dr = deals.get("dr") or []
        if page == 0:
            by_cat = {names[i]: n for i, n in zip(deals.get("categoryIds") or [], deals.get("categoryCount") or [])}
            info = {"total": sum(by_cat.values()), "by_cat": by_cat, "query": body}
            (meta["counts"] if kind == "cnt" else meta["samples"])[name] = info
        if kind == "smp":
            s = meta["samples"].setdefault(name, {})
            s["pages"] = s.get("pages", 0) + 1
            s["last_full"] = len(dr) >= DEAL_PAGE_SIZE
            for d in dr:
                row = analysis.deal_row(d, names, body["dateRange"], source=name)
                if row:
                    rows.setdefault(row.asin, row)
    return list(rows.values()), meta


def ctx_date_range(latest: dict) -> int | None:
    for rec in latest.values():
        return rec["request"]["body"]["dateRange"]
    return None


def cmd_propose(ctx: Ctx) -> int:
    rows, meta = load_census(ctx.root)
    if not rows:
        print("no census data yet — run `census` first.")
        return 1
    h = ctx.cfg["history"]
    picked = sampling.propose(rows, target=h["target_sample"], min_ref_cents=h["min_reference_cents"],
                              max_per_category=h["max_per_category"])
    out = {
        "approved": False,
        "instructions": "Review candidates.md. Delete/replace entries as you like (add an ASIN with "
                        "just {\"asin\": ...}), then set approved to true. `history` refuses to run "
                        "until you do.",
        "census_samples": sorted(meta["samples"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": picked,
    }
    (ctx.root / "candidates.json").write_text(json.dumps(out, indent=2))
    (ctx.root / "candidates.md").write_text(report.candidates_md(picked))
    print(f"proposed {len(picked)} of target {h['target_sample']} -> {ctx.root}/candidates.json")
    by = {}
    for p in picked:
        by[p["cohort"]] = by.get(p["cohort"], 0) + 1
    print("  by category:", by)
    return 0


def cmd_history(ctx: Ctx) -> int:
    h = ctx.cfg["history"]
    path = ctx.root / "candidates.json"
    if not path.exists():
        print("no candidates.json — run `propose` first.")
        return 1
    cand = json.loads(path.read_text())
    asins = [c["asin"] for c in cand["candidates"]]
    per = history_offer_cost(1, h["offers"])
    est = per * len(asins)
    print(f"HISTORY — {len(asins)} ASINs, /product offers={h['offers']} days={h['fetch_days']} "
          f"stats={h['days']} historical-variations=1, one ASIN per request")
    print(f"  worst case {per} tokens/ASIN -> {est} tokens total")
    print(" ", budget_line(ctx))
    if not cand.get("approved"):
        print(f"  {path} is not approved yet. Review it, then set \"approved\": true.")
        return 1
    if ctx.dry_run:
        print("  --dry-run: no requests made.")
        return 0
    keepa = ctx.client("history")
    probe(keepa)
    if not ctx.confirm(f"Spend up to {est} tokens on history for {len(asins)} ASINs?"):
        print("aborted.")
        return 1
    for asin in asins:
        data = keepa.call("product", label=f"product-{asin}", estimate=per, params={
            # Fetch a margin beyond the analysis window so episodes crossing its start keep context.
            "domain": DOMAIN_US, "asin": asin, "offers": h["offers"], "days": h["fetch_days"],
            "stats": h["days"], "historical-variations": 1,
        })
        print(f"  {asin}: {data.get('tokensConsumed')} tokens")
    print(" ", budget_line(ctx))
    return 0


def load_history(root: Path, cfg: dict, cohorts: dict[str, str],
                 run: Path | None = None) -> list[analysis.ProductResult]:
    results = []
    for rec in raw_files(run or latest_run(root, "history"), "product"):
        resp = rec["response"]
        ts = resp.get("timestamp")
        now = unix_to_keepa(ts / 1000) if ts else unix_to_keepa(
            datetime.fromisoformat(rec["request"]["sentAt"]).timestamp())
        for p in resp.get("products") or []:
            r = analysis.analyze_product(p, now, cfg["history"]["days"],
                                         tuple(cfg["analysis"]["thresholds"]),
                                         category=cohorts.get(p["asin"], "?"))
            r.tokens = resp.get("tokensConsumed")
            results.append(r)
    return results


def load_samples(root: Path) -> list[dict]:
    """Named samples from research/samples/*.json, each matched to the history run covering its ASINs."""
    samples = []
    files = sorted((root / "samples").glob("*.json")) if (root / "samples").exists() else []
    if not files and (root / "candidates.json").exists():
        files = [root / "candidates.json"]
    runs = all_runs(root, "history")
    for f in files:
        cand = json.loads(f.read_text())
        asins = {c["asin"] for c in cand["candidates"]}
        cohorts = {c["asin"]: c.get("cohort", "?") for c in cand["candidates"]}
        for run in reversed(runs):
            got = {rec["label"].removeprefix("product-") for rec in raw_files(run, "product")}
            if got and got <= asins:
                samples.append({"name": cand.get("sample", f.stem), "file": str(f), "run": str(run),
                                "results": None, "cohorts": cohorts})
                break
    return samples


def cmd_report(ctx: Ctx) -> int:
    rows, meta = load_census(ctx.root)
    samples = load_samples(ctx.root)
    for smp in samples:
        smp["results"] = load_history(ctx.root, ctx.cfg, smp["cohorts"], Path(smp["run"]))
    md = report.render(rows, meta, samples, ctx.ledger.entries(), ctx.cfg)
    out = ctx.root / "preflight-report.md"
    out.write_text(md)
    print(f"wrote {out}")
    for smp in samples:
        decision, why = analysis.suggest_decision(len(rows), smp["results"])
        print(f"  {smp['name']}: suggested (D5) {decision} — {why}")
    return 0


def main(argv=None, input_fn=input) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="preflight.toml")
    ap.add_argument("--fixtures", help="serve Keepa responses from this directory (zero cost)")
    ap.add_argument("--root", help="research output directory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe")
    census = sub.add_parser("census")
    census.add_argument("--dry-run", action="store_true")
    census.add_argument("--only", help="comma-separated query names from preflight.toml")
    sub.add_parser("history").add_argument("--dry-run", action="store_true")
    sub.add_parser("propose")
    sub.add_parser("report")
    args = ap.parse_args(argv)
    ctx = Ctx(args, input_fn)
    if args.cmd == "census":
        return cmd_census(ctx, args.only.split(",") if args.only else None)
    return {"probe": cmd_probe, "propose": cmd_propose,
            "history": cmd_history, "report": cmd_report}[args.cmd](ctx)


if __name__ == "__main__":
    sys.exit(main())
