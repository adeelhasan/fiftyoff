"""Track 2 (D17): forward collector — our own timestamped record of Resale deals.

    uv run collector.py unlock            # §7 manual ungating; writes .fiftyoff/approval.json
    uv run collector.py run --hours 48    # sweep the target slice + re-check a watchlist, until stopped
    uv run collector.py run --dry-run     # show the plan and token rate, no requests
    uv run collector.py report            # offline -> research/collector/report.md

Each loop: every `sweep_minutes`, page through the deal feed for the target slice (new 50%+ Resale
listings). In between, force fresh offer checks on a watchlist of popular strict-50%+ items, stalest
first, so we time how long deals and units last. Refuses to run without the approval file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import preflight
from fiftyoff import analysis
from fiftyoff.keepa import (
    AMAZON, CONDITIONS, DEAL_PAGE_COST, DEAL_PAGE_SIZE, DOMAIN_US, NEW, Keepa, KeepaError, Ledger,
    LiveTransport, load_api_key,
)

APPROVAL = Path(".fiftyoff/approval.json")
ROOT = Path("research/collector")
TARGET_CATS = [172282, 1055398, 2619525011, 228013, 3375251]  # Electronics, H&K, Appliances, Tools, Sports


def now_s() -> float:
    return time.time()


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat(timespec="seconds")


def append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def cmd_unlock(args, cfg) -> int:
    print("UNLOCK — §7 manual ungating for the forward collector.")
    print("  Recommended decision from the pre-flight: PARTIAL GO (docs/DECISIONS.md D15).")
    if input("Approve continuous Keepa polling by the collector? [y/N] ").strip().lower() not in ("y", "yes"):
        print("not approved.")
        return 1
    APPROVAL.parent.mkdir(exist_ok=True)
    APPROVAL.write_text(json.dumps({
        "preflightCompleted": True, "decision": "PARTIAL GO", "approvedByUser": True,
        "approvedAt": iso(now_s()), "scope": args.scope,
    }, indent=2))
    print(f"wrote {APPROVAL}")
    return 0


def sweep_query(c: dict, page: int) -> dict:
    return {
        "page": page, "domainId": DOMAIN_US, "priceTypes": [9], "dateRange": 0,
        "isRangeEnabled": True, "deltaPercentRange": [c["min_delta"], 100],
        "currentRange": [c["min_resale_cents"], 100_000_00],
        "isFilterEnabled": True, "filterErotic": True, "singleVariation": False, "sortType": 1,
        "includeCategories": TARGET_CATS,
    }


class Collector:
    def __init__(self, cfg: dict, keepa: Keepa):
        self.c = cfg["collector"]
        self.keepa = keepa
        self.watch_path = ROOT / "watchlist.json"
        self.watch: dict[str, dict] = json.loads(self.watch_path.read_text()) if self.watch_path.exists() else {}
        self.last_sweep = 0.0

    def save_watch(self) -> None:
        self.watch_path.write_text(json.dumps(self.watch, indent=2))

    def spent_today(self) -> int:
        day = iso(now_s())[:10]
        return sum(e.get("tokensConsumed") or 0 for e in self.keepa.ledger.entries() if e["at"][:10] == day)

    def sweep(self) -> None:
        t0 = now_s()
        seen = 0
        for page in range(self.c["max_pages"]):
            data = self.keepa.call("deal", label=f"sweep-p{page}", estimate=DEAL_PAGE_COST, body=sweep_query(self.c, page))
            deals = data.get("deals") or {}
            names = dict(zip(deals.get("categoryIds") or [], deals.get("categoryNames") or []))
            dr = deals.get("dr") or []
            for d in dr:
                r = analysis.deal_row(d, names, 0, source="sweep")
                if not r:
                    continue
                rank = d["current"][3] if len(d["current"]) > 3 and d["current"][3] > 0 else None
                append(ROOT / "sweeps.jsonl", {
                    "t": t0, "asin": r.asin, "parent": r.parent, "cat": r.root_cat, "title": r.title,
                    "resale": r.warehouse_cents, "ref": r.strict_ref_cents, "strict": r.strict,
                    "keepa": r.keepa_reported, "cond": r.condition, "comment": r.condition_comment,
                    "rank": rank, "keepa_last_update": d.get("lastUpdate"),
                })
                self.maybe_watch(r, rank, t0)
            seen += len(dr)
            if len(dr) < DEAL_PAGE_SIZE:
                break
        self.last_sweep = t0
        print(f"[{iso(t0)}] sweep: {seen} listings, watchlist {len(self.watch)}, today {self.spent_today()} tokens")

    def maybe_watch(self, r, rank, t) -> None:
        good = (r.strict or 0) >= 0.5 and (r.strict_ref_cents or 0) >= self.c["watch_min_ref_cents"] \
            and rank is not None and rank <= self.c["watch_max_rank"]
        if not good or r.asin in self.watch:
            return
        if len(self.watch) >= self.c["watch_size"]:
            # Evict the entry that has gone longest without a qualifying Resale offer (6h+).
            stale = [(w.get("last_qualifying") or w["added"], a) for a, w in self.watch.items()
                     if t - (w.get("last_qualifying") or w["added"]) > 6 * 3600]
            if not stale:
                return
            del self.watch[min(stale)[1]]
        self.watch[r.asin] = {"added": t, "title": r.title, "cat": r.root_cat, "rank": rank,
                              "last_check": 0, "last_qualifying": t}
        self.save_watch()

    def check_one(self) -> None:
        if not self.watch:
            time.sleep(60)
            return
        asin = min(self.watch, key=lambda a: self.watch[a]["last_check"])
        t0 = now_s()
        try:
            data = self.keepa.call("product", label=f"check-{asin}", estimate=self.c["check_estimate"], params={
                "domain": DOMAIN_US, "asin": asin, "offers": 20, "update": 0, "only-live-offers": 1, "history": 0,
                "stats": 1,
            })
        except KeepaError as e:
            print(f"  {asin}: {e}")
            self.watch[asin]["last_check"] = t0
            return
        p = (data.get("products") or [{}])[0]
        stats = p.get("stats") or {}
        cur = stats.get("current") or []
        refs = [v for v in (cur[AMAZON] if len(cur) > AMAZON else -1, cur[NEW] if len(cur) > NEW else -1) if v and v > 0]
        ref = min(refs) if refs else None
        live = set(p.get("liveOffersOrder") or [])
        offers = [{"id": o.get("offerId"), "price": o["offerCSV"][-2] if o.get("offerCSV") else None,
                   "cond": CONDITIONS.get(o.get("condition", 0)), "comment": o.get("conditionComment")}
                  for i, o in enumerate(p.get("offers") or []) if o.get("isWarehouseDeal") and i in live]
        best = max((analysis.discount(o["price"], ref) or 0 for o in offers), default=None)
        append(ROOT / "checks.jsonl", {"t": t0, "asin": asin, "ref": ref, "offers": offers, "best": best,
                                       "offers_ok": p.get("offersSuccessful"), "tokens": data.get("tokensConsumed")})
        w = self.watch[asin]
        w["last_check"] = t0
        if best is not None and best >= 0.5:
            w["last_qualifying"] = t0
        self.save_watch()

    def run(self, hours: float) -> None:
        end = now_s() + hours * 3600
        while now_s() < end:
            if self.spent_today() >= self.c["daily_token_cap"]:
                print(f"[{iso(now_s())}] daily cap {self.c['daily_token_cap']} reached; sleeping 15 min")
                time.sleep(900)
                continue
            try:
                if now_s() - self.last_sweep >= self.c["sweep_minutes"] * 60:
                    self.sweep()
                else:
                    self.check_one()
            except Exception as e:  # a 48h run must survive outages and laptop sleep
                print(f"[{iso(now_s())}] error: {type(e).__name__}: {e}; pausing 2 min")
                time.sleep(120)


def cmd_run(args, cfg) -> int:
    c = cfg["collector"]
    rate = 20
    sweep_rate = c["max_pages"] * DEAL_PAGE_COST / c["sweep_minutes"]
    check_rate = max(0.1, (rate - sweep_rate) / c["check_estimate"])
    print(f"COLLECTOR — sweep every {c['sweep_minutes']} min (≤{c['max_pages']} pages, ≤{sweep_rate:.1f} tokens/min); "
          f"watchlist ≤{c['watch_size']} items, ~{check_rate:.1f} checks/min -> each item every "
          f"~{c['watch_size'] / check_rate:.0f} min when full; daily cap {c['daily_token_cap']:,} tokens; {args.hours} h")
    if args.dry_run:
        print("  --dry-run: no requests made.")
        return 0
    if not APPROVAL.exists() or not json.loads(APPROVAL.read_text()).get("approvedByUser"):
        print(f"refusing: {APPROVAL} missing. Run `uv run collector.py unlock` first (plan §7).")
        return 1
    keepa = Keepa(LiveTransport(load_api_key()), Ledger(ROOT / "token-ledger.jsonl"),
                  ROOT / "raw" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                  token_cap=c["run_token_cap"])
    Collector(cfg, keepa).run(args.hours)
    return 0


def cmd_report(args, cfg) -> int:
    sweeps = read_jsonl(ROOT / "sweeps.jsonl")
    checks = read_jsonl(ROOT / "checks.jsonl")
    if not sweeps:
        print("no data yet")
        return 1
    times = sorted({s["t"] for s in sweeps})
    first = {}
    for s in sweeps:
        if (s["strict"] or 0) >= 0.5:
            first.setdefault(s["asin"], s["t"])
    hours = (times[-1] - times[0]) / 3600 if len(times) > 1 else 0
    new_after_baseline = [a for a, t in first.items() if t > times[0]]
    L = ["# Forward collector report\n",
         f"{len(times)} sweeps over {hours:.1f} h; {len(checks)} watchlist checks.\n",
         f"- Strict-50%+ ASINs in the first sweep (baseline): {sum(1 for t in first.values() if t == times[0])}",
         f"- New strict-50%+ ASINs after the baseline: {len(new_after_baseline)}"
         + (f" (~{len(new_after_baseline) / hours * 24:.0f}/day)" if hours else ""),
         ]
    # Unit lifespans from our own checks: first and last time each Resale offer was seen live.
    seen: dict[tuple, list] = {}
    per_asin: dict[str, list] = {}
    for ch in sorted(checks, key=lambda x: x["t"]):
        per_asin.setdefault(ch["asin"], []).append(ch["t"])
        for o in ch["offers"]:
            seen.setdefault((ch["asin"], o["id"]), []).append(ch["t"])
    gone = []
    for (asin, oid), ts in seen.items():
        later = [t for t in per_asin[asin] if t > ts[-1]]
        if later:
            gone.append(((ts[-1] - ts[0]) / 60, (later[0] - ts[0]) / 60))
    L.append(f"- Resale units tracked: {len(seen)}; seen to disappear: {len(gone)}")
    if gone:
        L.append("\n| unit lifespan (min) lower | upper |\n|---|---|")
        L += [f"| {lo:.0f} | {hi:.0f} |" for lo, hi in sorted(gone)[:60]]
    (ROOT / "report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:6]))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="preflight.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unlock")
    u.add_argument("--scope", default="Track 2 forward collector")
    r = sub.add_parser("run")
    r.add_argument("--hours", type=float, default=48)
    r.add_argument("--dry-run", action="store_true")
    sub.add_parser("report")
    args = ap.parse_args(argv)
    cfg = preflight.load_config(Path(args.config))
    return {"unlock": cmd_unlock, "run": cmd_run, "report": cmd_report}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
