"""Tracker logic on scripted Keepa responses and a fake clock. No network (conftest guard)."""

import gzip
import json

import pytest

from fiftyoff.keepa import Keepa, Ledger, unix_to_keepa
from fiftyoff.tracker import (GONE_AFTER, HOUR, MemoryStore, Tracker, TrackerConfig, lifespan, qualifies,
                              strict_ref_from_stats)

T0 = 1_790_000_000.0
N = 36


def arr(**v):
    a = [-1] * N
    for k, x in v.items():
        a[int(k[1:])] = x
    return a


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class Script:
    """Keepa transport serving scripted responses: deal pages by page number, product checks per ASIN
    in call order (the last one repeats)."""

    def __init__(self):
        self.pages: list[list[dict]] = []
        self.products: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, dict, dict | None]] = []

    def request(self, endpoint, params, body):
        self.calls.append((endpoint, params, body))
        env = {"tokensLeft": 1000, "refillRate": 20}
        if endpoint == "deal":
            dr = self.pages[body["page"]] if body["page"] < len(self.pages) else []
            return 200, {**env, "tokensConsumed": 5,
                         "deals": {"dr": dr, "categoryIds": [228013], "categoryNames": ["Tools"]}}
        seq = self.products[params["asin"]]
        p = seq.pop(0) if len(seq) > 1 else seq[0]
        return 200, {**env, "tokensConsumed": 7, "products": [p]}


def deal(asin, wh, new, creation, rank=1000):
    avg = [arr(i1=new) for _ in range(4)]
    return {"asin": asin, "parentAsin": asin, "title": asin, "rootCat": 228013, "categories": [228013],
            "current": arr(i1=new, i3=rank, i9=wh), "avg": avg, "deltaPercent": [arr(i9=50)] * 4,
            "creationDate": creation, "lastUpdate": creation, "warehouseCondition": 2,
            "warehouseConditionComment": "box damaged", "image": "x.jpg"}


def product(offers, new=20000, ok=True):
    """offers: list of (offerId, price) Resale units, all live."""
    return {"asin": "A", "offersSuccessful": ok, "liveOffersOrder": list(range(len(offers))),
            "stats": {"current": arr(i1=new), "avg": arr(i1=new), "avg30": arr(i1=new), "avg90": arr(i1=new)},
            "offers": [{"offerId": oid, "isWarehouseDeal": True, "condition": 2, "conditionComment": "ok",
                        "offerCSV": [1, price, 0]} for oid, price in offers]}


@pytest.fixture
def rig(tmp_path):
    clock, script, store = Clock(), Script(), MemoryStore()
    keepa = Keepa(script, Ledger(tmp_path / "ledger.jsonl"), tmp_path / "raw", token_cap=10_000,
                  sleep=lambda s: None, raw_gzip=True)
    tr = Tracker(TrackerConfig(), keepa, store, clock=clock, sleep=lambda s: None, log=lambda m: None)
    return clock, script, store, tr, tmp_path


def test_tiers():
    c = TrackerConfig()
    assert qualifies(0.45, 10000, 1000, c)          # 40% tier, $100 ref
    assert not qualifies(0.35, 15000, 1000, c)      # 35% needs a $200 ref
    assert qualifies(0.35, 25000, 1000, c)
    assert not qualifies(0.55, 9000, 1000, c)       # reference under $100
    assert not qualifies(0.55, 30000, 60000, c)     # not popular enough
    assert not qualifies(None, 30000, 1000, c)


def test_strict_ref_takes_lowest_of_now_and_averages():
    ref, parts = strict_ref_from_stats({"current": arr(i0=30000, i1=25000), "avg": arr(i1=24000),
                                        "avg30": arr(i0=-1, i1=26000), "avg90": arr(i1=22000)})
    assert ref == 22000 and parts["new_avg90"] == 22000 and "amazon_avg30" not in parts


def test_sweep_watches_qualifying_and_stops_incrementally(rig):
    clock, script, store, tr, _ = rig
    now_k = unix_to_keepa(T0)
    full = [deal(f"A{i}", 9000, 20000, now_k - i) for i in range(150)]   # 55% off a $200 ref
    script.pages = [full, full, [deal("OLD", 9000, 20000, now_k - 5000)]]
    assert tr.sweep() == 3                       # first sweep is full: pages until a short page
    assert len(tr.watch) == 151 and store.state["last_full_sweep"] == T0
    clock.t += 1800
    script.pages = [[deal(f"N{i}", 9000, 20000, unix_to_keepa(clock.t) - 2000) for i in range(150)]] * 5
    assert tr.sweep() == 1                       # incremental: page 0 already older than last sweep - 1 h


def test_unit_lifecycle_unconfirmed_return_gone_revive(rig):
    clock, script, store, tr, _ = rig
    script.pages = [[deal("A", 9000, 20000, unix_to_keepa(T0))]]
    tr.sweep()
    script.products["A"] = [product([(7, 9000)]), product([]), product([(7, 9000)]), product([]),
                            product([]), product([(7, 8500)])]
    tr.check("A")
    u = tr.units[("A", 7)]
    assert u.state == "live" and u.appeared_after is None and u.strict_first == pytest.approx(0.55)
    clock.t += 900; tr.check("A")
    assert u.state == "unconfirmed" and u.absent_since == clock.t      # one miss is not a sale
    clock.t += 900; tr.check("A")
    assert u.state == "live" and u.absent_since is None and u.checks_seen == 2
    last_seen = clock.t
    clock.t += 900; tr.check("A")
    absent_since = clock.t
    clock.t = last_seen + GONE_AFTER; tr.check("A")
    assert u.state == "gone" and u.absent_since == absent_since
    ls = lifespan(u)
    assert ls["lower_min"] == pytest.approx(30)
    assert ls["upper_min"] is None and ls["confidence"] == "LOW"   # already there on the first check
    clock.t += HOUR; tr.check("A")
    assert u.state == "live" and u.revivals == 1 and u.last_price == 8500


def test_failed_offer_fetch_is_not_a_miss(rig):
    clock, script, store, tr, _ = rig
    script.pages = [[deal("A", 9000, 20000, unix_to_keepa(T0))]]
    tr.sweep()
    script.products["A"] = [product([(7, 9000)]), product([], ok=False)]
    tr.check("A")
    clock.t += 7 * HOUR; tr.check("A")
    assert tr.units[("A", 7)].state == "live"


def test_new_unit_on_later_check_brackets_appearance(rig):
    clock, script, store, tr, _ = rig
    script.pages = [[deal("A", 9000, 20000, unix_to_keepa(T0))]]
    tr.sweep()
    script.products["A"] = [product([(7, 9000)]), product([(7, 9000), (8, 9500)])]
    tr.check("A")
    first_check = clock.t
    clock.t += 900; tr.check("A")
    u = tr.units[("A", 8)]
    assert u.appeared_after == first_check
    script.products["A"] = [product([(7, 9000)])]
    clock.t += 900; tr.check("A")                 # unit 8 sold: absent from here on
    absent_since = clock.t
    clock.t += 24 * HOUR; tr.check("A")
    ls = lifespan(u)
    assert u.state == "gone" and ls["lower_min"] == pytest.approx(0)
    assert ls["upper_min"] == pytest.approx((absent_since - first_check) / 60) and ls["confidence"] == "HIGH"


def test_scheduler_prefers_overdue_new_items_and_idles_when_nothing_due(rig):
    clock, script, store, tr, _ = rig
    old = unix_to_keepa(T0)
    script.pages = [[deal("A", 9000, 20000, old), deal("B", 9000, 20000, old)]]
    tr.sweep()
    script.products = {"A": [product([(1, 9000)])], "B": [product([(2, 9000)])]}
    assert tr.step() == "check" and tr.step() == "check"   # both never checked
    assert tr.step() == "idle"                             # nothing due yet
    clock.t += 15 * 60
    assert tr.next_check(clock.t) in ("A", "B")            # 15 min cadence while new
    clock.t = T0 + 7 * HOUR
    tr.last_sweep = clock.t                                # keep sweeps out of this test
    assert tr.interval(tr.watch["A"], clock.t) == 3600     # past the new window: hourly


def test_retire_when_checks_never_find_a_unit(rig):
    clock, script, store, tr, _ = rig
    script.pages = [[deal("A", 9000, 20000, unix_to_keepa(T0))]]
    tr.sweep()
    script.products["A"] = [product([])]
    tr.check("A")
    assert tr.watch["A"].retired is None
    clock.t += 6 * HOUR; tr.check("A")
    assert tr.watch["A"].retired == clock.t and tr.active_count() == 0


def test_raw_saved_gzipped_and_ledger_records_tokens(rig):
    clock, script, store, tr, tmp = rig
    script.pages = [[deal("A", 9000, 20000, unix_to_keepa(T0))]]
    tr.sweep()
    raws = list((tmp / "raw").glob("*.json.gz"))
    assert len(raws) == 1
    saved = json.loads(gzip.open(raws[0], "rt").read())
    assert saved["request"]["endpoint"] == "deal" and saved["response"]["deals"]["dr"][0]["asin"] == "A"
    assert Ledger(tmp / "ledger.jsonl").spent() == 5


def test_ledger_reads_incrementally_and_counts_since(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.record({"at": "2026-10-01T00:00:00", "tokensConsumed": 5})
    assert led.spent() == 5
    led.record({"at": "2026-10-02T00:00:00", "tokensConsumed": 7})
    other = Ledger(tmp_path / "l.jsonl")          # a second reader sees the same file
    assert other.spent() == 12 and led.spent("2026-10-02") == 7


def test_baseline_deals_are_not_new_but_fresh_deals_are(rig):
    clock, script, store, tr, _ = rig
    script.pages = [[deal("OLD", 9000, 20000, unix_to_keepa(T0 - 3 * 24 * HOUR)),
                     deal("NEW", 9000, 20000, unix_to_keepa(T0 - 600))]]
    tr.sweep()
    assert tr.interval(tr.watch["NEW"], T0) == 15 * 60
    assert tr.interval(tr.watch["OLD"], T0) == 60 * 60   # a fresh DB's baseline must not flood the fast queue


def test_first_check_brackets_existing_units_with_keepa_offer_looks(rig):
    clock, script, store, tr, _ = rig
    script.pages = [[deal("A", 9000, 20000, unix_to_keepa(T0 - 3 * HOUR))]]
    tr.sweep()
    k_first = unix_to_keepa(T0 - 3 * HOUR)
    looks = [unix_to_keepa(T0 - 5 * HOUR), 0, unix_to_keepa(T0 - 3.5 * HOUR), 0, k_first, 0]
    p = product([(7, 9000)])
    p["offers"][0]["offerCSV"] = [k_first, 9000, 0]
    p["csv"] = [None] * 15 + [looks]
    script.products["A"] = [p, product([])]
    tr.check("A")
    assert script.calls[-1][1]["history"] == 1           # history only on the first look
    u = tr.units[("A", 7)]
    assert u.keepa_first_seen == pytest.approx(T0 - 3 * HOUR, abs=60)      # Keepa time is whole minutes
    assert u.appeared_after == pytest.approx(T0 - 3.5 * HOUR, abs=60)
    clock.t += 900; tr.check("A")
    assert script.calls[-1][1]["history"] == 0
    clock.t += 24 * HOUR; tr.check("A")
    ls = lifespan(u)
    assert ls["lower_min"] == pytest.approx(180, abs=1)  # Keepa saw it 3 h before our first check
    assert ls["upper_min"] == pytest.approx(225, abs=1)  # first absence (+15 min) - Keepa's last look before (-3.5 h)
    assert ls["confidence"] == "HIGH"                    # 30 + 15 min of slack, and absent 24 h+


def test_full_sweep_reaches_further_than_incremental(rig):
    clock, script, store, tr, _ = rig
    page = [deal(f"A{i}", 9000, 20000, unix_to_keepa(T0) - i) for i in range(150)]
    script.pages = [page] * 40
    assert tr.sweep() == 41                              # full: past max_pages (20) until the empty page 40
    clock.t += 1800
    script.calls.clear()
    assert tr.sweep() == 1                               # incremental: stops at the previous sweep


def test_unlock_works_with_a_spent_ledger(tmp_path, monkeypatch):
    import tracker as cli
    from tests.fixtures import build
    fx = tmp_path / "fx"
    build.write(fx)
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "root"
    Ledger(root / "token-ledger.jsonl").record({"at": "2026-10-01T00:00:00", "tokensConsumed": 400_000})
    args = cli.main.__globals__["argparse"].Namespace(fixtures=str(fx), root=str(root), days=14, token_cap=None)
    cfg = {"tracker": {}}
    assert cli.cmd_unlock(args, cfg, input_fn=lambda _: "y") == 0
    a = json.loads((tmp_path / ".fiftyoff/tracker-approval.json").read_text())
    assert a["approvedByUser"] and a["tokenCap"] == 14 * 28_800
