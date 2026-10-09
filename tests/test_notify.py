"""Notifications v1: the rules, one pass over an in-memory store, the tracker's events, and the rule-7 guard."""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fiftyoff import notify
from fiftyoff.appeal import parse_lines
from fiftyoff.shelving import UNSORTED, resolve_shelf
from fiftyoff.tracker import MemoryStore, Tracker, TrackerConfig

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
SHELVES = {"headphones-earbuds": {"id": "headphones-earbuds", "name": "headphones & earbuds", "aisle": "audio-tv", "role": "front"},
           "auto-parts": {"id": "auto-parts", "name": "auto parts", "aisle": "auto", "role": "hidden"}}
KMAP = {"earbuds": "headphones-earbuds"}
CFG = notify.NotifyConfig(tiers={"free": {"delay_minutes": 10, "max_interests": 1},
                                 "plus": {"delay_minutes": 0, "max_interests": 5}})


def ev(**kw):
    e = {"id": 1, "at": NOW - timedelta(minutes=5), "kind": "new", "status": "new", "asin": "B000000001",
         "offer_id": 7, "state": "live", "strict": 0.55, "ref_cents": 20000, "cond": "Used - Like New",
         "resale_cents": 9000, "keepa_first_seen_at": NOW - timedelta(hours=1), "first_seen_at": NOW - timedelta(minutes=5),
         "appeared_after_at": None, "priced_at": NOW - timedelta(hours=1), "parent_asin": "P1", "title": "Sony WH-1000XM5",
         "unlisted": False}
    return {**e, **kw}


RATED = {"score": 8, "shelf": "headphones-earbuds", "kind": "headphones"}


def test_resolve_shelf_prefers_the_raters_shelf_then_kind():
    assert resolve_shelf({"shelf": "headphones-earbuds"}, KMAP, SHELVES) == "headphones-earbuds"
    assert resolve_shelf({"shelf": "no-such", "kind": "earbuds"}, KMAP, SHELVES) == "headphones-earbuds"
    assert resolve_shelf(None, KMAP, SHELVES) == UNSORTED


def test_decide_reasons():
    d = lambda e, a=RATED: notify.decide(e, a, KMAP, SHELVES, NOW, CFG)
    assert d(ev())[0] == "ready" and d(ev())[1]["product_key"] == "P1" and d(ev())[1]["aisle"] == "audio-tv"
    assert d(ev(strict=0.45)) == ("skip", {"why": "strict 0.45"})
    assert d(ev(ref_cents=3000))[1]["why"] == "reference"
    assert d(ev(cond="Used - Acceptable"))[1]["why"] == "acceptable"
    assert d(ev(state="gone"))[1]["why"] == "gone"
    assert d(ev(unlisted=True))[1]["why"] == "unlisted"
    old = ev(keepa_first_seen_at=NOW - timedelta(days=3), priced_at=NOW - timedelta(days=2))
    assert d(old)[1]["why"] == "not fresh"                       # a first check finds old listings too
    assert d({**old, "kind": "revived"})[0] == "ready"            # a revival is news whatever its age
    assert d(ev(), {**RATED, "score": 2})[1]["why"] == "appeal 2"
    assert d(ev(), None)[0] == "wait"
    assert d(ev(at=NOW - timedelta(hours=2)), None) == ("expire", {"why": "no rating"})


def test_watches_shelf_and_aisle_but_aisle_skips_hidden_shelves():
    assert notify.watches([("shelf", "auto-parts")], "auto-parts", "auto", "hidden")
    assert not notify.watches([("aisle", "auto")], "auto-parts", "auto", "hidden")
    assert notify.watches([("aisle", "audio-tv")], "headphones-earbuds", "audio-tv", "front")


def test_tiers_are_config():
    assert notify.perks(CFG, "plus")["delay_minutes"] == 0
    assert notify.perks(CFG, "nonsense") == notify.perks(CFG, "free")
    assert notify.deliver_at(NOW, "free", CFG) == NOW + timedelta(minutes=10)


def test_render_has_d19_fields_attribution_and_no_amazon_link():
    item = {"title": "Sony <b>", "strict": 0.55, "cond": "Used - Like New", "resale_cents": 9000,
            "shelf": "headphones-earbuds", "shelf_name": "headphones & earbuds"}
    subject, text, html = notify.render([item, {**item, "strict": 0.6}], CFG)
    assert subject.startswith("2 new deals") and "60%" in subject
    for body in (text, html):
        assert "Data by Keepa" in body and "amazon." not in body and "tag=" not in body
    assert "Sony &lt;b&gt;" in html and "$90.00" in text


class Mem:
    def __init__(self, events, ratings, audience):
        self.events, self.ratings, self.aud = events, ratings, audience
        self.status, self.deliveries, self.sent_marks = {}, [], {}

    def open_events(self): return [e for e in self.events if self.status.get(e["id"], "new") in ("new", "waiting")]
    def appeal(self, keys): return {k: v for k, v in self.ratings.items() if k in keys}
    def shelves(self): return SHELVES
    def kind_map(self): return KMAP
    def set_event(self, i, status, d): self.status[i] = status
    def audience(self): return self.aud
    def recent(self, since): return {(d["subscriber_id"], d["product_key"]) for d in self.deliveries if d["deliver_at"] > since}
    def add_deliveries(self, rows): self.deliveries += [{**r, "id": len(self.deliveries) + n, "status": "queued"} for n, r in enumerate(rows)]

    def due(self, now):
        e = {x["id"]: x for x in self.events}
        return [{**d, **e[d["event_id"]], "id": d["id"], "address": f"s{d['subscriber_id']}@x", "endpoint_kind": "email",
                 "shelf": "headphones-earbuds", "shelf_name": "headphones & earbuds"}
                for d in self.deliveries if d["status"] == "queued" and d["deliver_at"] <= now]

    def mark(self, ids, status, error=None):
        for d in self.deliveries:
            if d["id"] in ids:
                d["status"] = status

    def endpoint_result(self, eid, ok): pass


def test_one_pass_queues_by_tier_dedupes_and_sends_one_message_per_address():
    aud = [{"subscriber_id": 1, "tier": "free", "endpoint_id": 10, "interests": [("aisle", "audio-tv")]},
           {"subscriber_id": 2, "tier": "plus", "endpoint_id": 20, "interests": [("shelf", "headphones-earbuds")]},
           {"subscriber_id": 3, "tier": "plus", "endpoint_id": 30, "interests": [("aisle", "kitchen")]}]
    events = [ev(id=1), ev(id=2, asin="B000000002", offer_id=8),  # same parent: the second is a repeat
              ev(id=3, asin="B000000003", parent_asin=None)]       # unrated: waits
    m = Mem(events, {"P1": RATED}, aud)
    assert notify.advance(m, NOW, CFG) == {"queued": 1, "no_watchers": 1, "wait": 1}
    assert {(d["subscriber_id"], d["deliver_at"]) for d in m.deliveries} == {(1, events[0]["at"] + timedelta(minutes=10)),
                                                                             (2, events[0]["at"])}
    assert m.status == {1: "queued", 2: "no_watchers", 3: "waiting"}
    out = []
    assert notify.send_due(m, lambda e, s, t, h: out.append(e["address"]), NOW, CFG) == 1  # free tier still waits
    assert out == ["s2@x"]
    assert notify.send_due(m, lambda e, s, t, h: out.append(e["address"]), NOW + timedelta(minutes=10), CFG) == 1
    assert out == ["s2@x", "s1@x"]


def test_gone_before_the_delay_is_stale_not_sent():
    aud = [{"subscriber_id": 1, "tier": "free", "endpoint_id": 10, "interests": [("aisle", "audio-tv")]}]
    m = Mem([ev()], {"P1": RATED}, aud)
    notify.advance(m, NOW, CFG)
    m.events[0]["state"] = "gone"
    assert notify.send_due(m, lambda *a: 1 / 0, NOW + timedelta(hours=1), CFG) == 0
    assert m.deliveries[0]["status"] == "stale"


def test_tracker_records_new_and_revived_units():
    store = MemoryStore()
    tr = Tracker(TrackerConfig(), None, store, clock=lambda: 1000.0, log=lambda m: None)
    offers = [{"offer_id": 7, "price": 9000, "keepa_first": 0, "cond": "Used - Like New", "comment": None, "strict": 0.55}]
    tr._update_units("A", offers, 20000, 1000.0, None)
    tr._update_units("A", offers, 20000, 2000.0, 1000.0)             # still there: no event
    tr.units[("A", 7)].state = "gone"
    tr._update_units("A", offers, 20000, 3000.0, 2000.0)
    tr._update_units("A", [], 20000, 4000.0, 3000.0)                 # unconfirmed: no event
    assert [(k, a, o) for k, a, o, _ in store.events] == [("new", "A", 7), ("revived", "A", 7)]


def test_tracker_never_imports_a_model_client():
    root = Path(__file__).parent.parent
    for f in (root / "tracker.py", root / "fiftyoff" / "tracker.py", root / "fiftyoff" / "store_pg.py"):
        names = set()
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        assert not any(n.startswith(("anthropic", "claude")) or n.endswith(("rate_local", "rater")) for n in names), f


def test_parse_lines_checks_every_field():
    good = "P1\t8\taudio-tv\theadphones-earbuds\theadphones\tn\t-\tSony flagship headphones"
    rows, bad = parse_lines([good, "P2\t11\taudio-tv\theadphones-earbuds\tx\tn\t-\twhy",
                             "P3\t5\taudio-tv\tno-such-shelf\tx\tn\t-\twhy"], "a0.3")
    assert [r[0] for r in rows] == ["P1"] and rows[0][7] == "headphones-earbuds" and len(bad) == 2
