"""Keyword alerts k0.1: the rules, one pass over an in-memory store, one-shot windows, expiry, the tracker's
events, and the rule-7 guard."""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fiftyoff import mail, notify
from fiftyoff.appeal import parse_lines
from fiftyoff.tracker import MemoryStore, Tracker, TrackerConfig

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
CFG = notify.NotifyConfig(tiers={"free": {"delay_minutes": 30, "max_interests": 1, "one_shot": True, "lifetime_days": 30},
                                 "plus": {"delay_minutes": 0, "max_interests": 10, "one_shot": False, "lifetime_days": 0}})
LINKS = mail.Links("https://beta.fiftyoff.app", "k")


def ev(**kw):
    e = {"id": 1, "at": NOW - timedelta(minutes=5), "kind": "new", "status": "new", "asin": "B000000001",
         "offer_id": 7, "state": "live", "strict": 0.55, "ref_cents": 20000, "cond": "Used - Like New",
         "resale_cents": 9000, "keepa_first_seen_at": NOW - timedelta(hours=1), "first_seen_at": NOW - timedelta(minutes=5),
         "appeared_after_at": None, "priced_at": NOW - timedelta(hours=1), "parent_asin": "P1",
         "title": "Dyson V15 Detect Cordless Vacuum", "brand": "Dyson", "unlisted": False, "image": None}
    return {**e, **kw}


RATED = {"score": 8}


def test_keyword_is_normalised_and_bounded():
    assert notify.keyword("  Kate   SPADE ") == "kate spade"
    assert notify.keyword("WH-1000XM5") == "wh-1000xm5"
    assert notify.keyword("<script>") == "script"
    assert notify.keyword("a") is None and notify.keyword("x" * 41) is None and notify.keyword("--") is None


def test_keyword_matching_is_searchs():
    hit = lambda k, title, brand=None: notify.hits(k, {"title": title, "brand": brand})  # noqa: E731
    assert hit("rug", "Washable Rugs 5x7") and not hit("rug", "Drug test kit")
    assert hit("dyson v15", "Dyson V15 Detect") and not hit("dyson v12", "Dyson V15 Detect")  # every word must match
    assert hit("dyson", "V15 Detect Cordless", brand="Dyson")                                # the brand counts
    from fiftyoff.api_v1 import matches, words
    for k, t in (("sony wh", "Sony WH-1000XM5"), ("galaxy ring", "Samsung Galaxy Watch")):
        assert hit(k, t) == matches(k, words(t))


def test_decide_reasons():
    d = lambda e, a=RATED: notify.decide(e, a, NOW, CFG)  # noqa: E731
    assert d(ev()) == ("ready", {"product_key": "P1", "score": 8})
    assert d(ev(strict=0.45)) == ("skip", {"why": "strict 0.45"})
    assert d(ev(ref_cents=3000))[1]["why"] == "reference"
    assert d(ev(cond="Used - Acceptable"))[1]["why"] == "acceptable"
    assert d(ev(state="gone"))[1]["why"] == "gone"
    assert d(ev(unlisted=True))[1]["why"] == "unlisted"
    old = ev(keepa_first_seen_at=NOW - timedelta(days=3), priced_at=NOW - timedelta(days=2))
    assert d(old)[1]["why"] == "not fresh"                       # a first check finds old listings too
    assert d({**old, "kind": "revived"})[0] == "ready"            # a revival is news whatever its age
    assert d(ev(), {"score": 2})[1]["why"] == "appeal 2"          # an existing low rating still skips
    assert d(ev(), None)[0] == "ready"                            # ...but nobody waits for the rater


def test_tiers_are_config():
    assert notify.perks(CFG, "plus")["delay_minutes"] == 0
    assert notify.perks(CFG, "nonsense") == notify.perks(CFG, "free")
    assert notify.deliver_at(NOW, "free", CFG) == NOW + timedelta(minutes=30)


class Mem:
    """An in-memory NotifyStore: alerts are rows {interest_id, subscriber_id, tier, keyword, armed_at, state}."""

    def __init__(self, events, ratings, alerts):
        self.events, self.ratings, self.alerts = events, ratings, {a["interest_id"]: a for a in alerts}
        self.status, self.deliveries, self.paused = {}, [], set()

    def open_events(self): return [e for e in self.events if self.status.get(e["id"], "new") in ("new", "waiting")]
    def appeal(self, keys): return {k: v for k, v in self.ratings.items() if k in keys}
    def set_event(self, i, status, d): self.status[i] = status

    def audience(self):
        return [{**a, "endpoint_id": a["subscriber_id"] * 10} for a in self.alerts.values() if a["state"] == "watching"]

    def windows(self):
        w = {}
        for d in self.deliveries:
            if d["status"] == "queued":
                w[d["interest_id"]] = min(w.get(d["interest_id"], d["deliver_at"]), d["deliver_at"])
        return w

    def recent(self, since): return {(d["subscriber_id"], d["product_key"]) for d in self.deliveries
                                     if d["deliver_at"] > since and d["status"] in ("queued", "sent")}
    def add_deliveries(self, rows): self.deliveries += [{**r, "id": len(self.deliveries) + n, "status": "queued"} for n, r in enumerate(rows)]

    def due(self, now):
        e = {x["id"]: x for x in self.events}
        out = []
        for d in self.deliveries:
            if d["status"] == "queued" and d["deliver_at"] <= now:
                a = self.alerts[d["interest_id"]]
                x = e[d["event_id"]]
                out.append({**x, **d, "address": f"s{d['subscriber_id']}@x", "tier": a["tier"], "keyword": a["keyword"],
                            "interest_state": a["state"], "paused": d["subscriber_id"] in self.paused,
                            "slug": x["asin"].lower(), "id": d["id"]})
        return out

    def mark(self, ids, status, error=None):
        for d in self.deliveries:
            if d["id"] in ids:
                d["status"] = status

    def end_interest(self, iid, state, now):
        if self.alerts[iid]["state"] == "watching":
            self.alerts[iid].update(state=state, ended_at=now)
        self.mark([d["id"] for d in self.deliveries if d["interest_id"] == iid and d["status"] == "queued"], "dropped")

    def armed_before(self, t):
        return [{**a, "address": f"s{a['subscriber_id']}@x", "paused": False} for a in self.alerts.values()
                if a["state"] == "watching" and a["armed_at"] < t]

    def endpoint_result(self, eid, ok): pass


def alert(iid, sid, keyword, tier="free", armed=NOW - timedelta(days=1)):
    return {"interest_id": iid, "subscriber_id": sid, "tier": tier, "keyword": keyword, "armed_at": armed, "state": "watching"}


def outbox():
    sent = []
    return sent, lambda address, m: sent.append((address, m))


def test_a_match_opens_a_window_later_matches_join_it_and_a_free_alert_fires_once():
    m = Mem([ev(id=1), ev(id=2, asin="B000000002", parent_asin="P2", title="Dyson Airwrap", at=NOW - timedelta(minutes=1)),
             ev(id=3, asin="B000000003", parent_asin="P3", title="Shark Navigator", brand="Shark")],
            {}, [alert(1, 1, "dyson"), alert(2, 2, "dyson", tier="plus"), alert(3, 3, "shark")])
    assert notify.advance(m, NOW, CFG) == {"queued": 3}
    free = [d for d in m.deliveries if d["interest_id"] == 1]
    assert [d["deliver_at"] for d in free] == [NOW + timedelta(minutes=25)] * 2   # the second joined the first's window
    sent, send = outbox()
    assert notify.send_due(m, send, NOW, CFG, LINKS) == 1                        # plus: no delay; free waits
    assert sent[0][0] == "s2@x" and m.alerts[2]["state"] == "watching"         # paid keeps firing
    assert notify.send_due(m, send, NOW + timedelta(minutes=25), CFG, LINKS) == 2  # one email per alert
    one = next(x for a, x in sent if a == "s1@x")
    assert one.subject == "2 dyson deals at half off or better" and "free alert" in one.text
    assert m.alerts[1]["state"] == "fired"
    m.events.append(ev(id=4, asin="B000000004", parent_asin="P4", title="Dyson V8"))
    notify.advance(m, NOW + timedelta(minutes=30), CFG)
    assert not [d for d in m.deliveries if d["event_id"] == 4 and d["interest_id"] == 1]  # fired: no more


def test_no_backfill_an_alert_armed_after_the_deal_landed_doesnt_fire():
    m = Mem([ev()], {}, [alert(1, 1, "dyson", armed=NOW)])
    assert notify.advance(m, NOW, CFG) == {"no_watchers": 1}


def test_missed_units_keep_the_alert_armed():
    m = Mem([ev()], {}, [alert(1, 1, "dyson")])
    notify.advance(m, NOW, CFG)
    m.events[0]["state"] = "gone"
    sent, send = outbox()
    assert notify.send_due(m, send, NOW + timedelta(hours=1), CFG, LINKS) == 0 and not sent
    assert m.deliveries[0]["status"] == "stale" and m.alerts[1]["state"] == "watching"


def test_stop_inside_the_window_drops_the_delivery():
    m = Mem([ev()], {}, [alert(1, 1, "dyson")])
    notify.advance(m, NOW, CFG)
    m.alerts[1]["state"] = "stopped"
    sent, send = outbox()
    assert notify.send_due(m, send, NOW + timedelta(hours=1), CFG, LINKS) == 0 and not sent
    assert m.deliveries[0]["status"] == "dropped"


def test_one_message_per_product_per_subscriber():
    m = Mem([ev(id=1), ev(id=2, offer_id=8)], {}, [alert(1, 1, "dyson", tier="plus")])  # same parent P1
    assert notify.advance(m, NOW, CFG) == {"queued": 1, "no_watchers": 1}


def test_expiry_ends_old_free_alerts_and_emails_them_once():
    m = Mem([], {}, [alert(1, 1, "dyson", armed=NOW - timedelta(days=31)), alert(2, 2, "shark", armed=NOW - timedelta(days=3)),
                     alert(3, 3, "sony", tier="plus", armed=NOW - timedelta(days=90))])
    sent, send = outbox()
    assert notify.expire(m, send, NOW, CFG, LINKS) == 1
    assert m.alerts[1]["state"] == "expired" and m.alerts[2]["state"] == "watching" and m.alerts[3]["state"] == "watching"
    assert sent[0][0] == "s1@x" and "30 days" in sent[0][1].subject
    assert notify.expire(m, send, NOW, CFG, LINKS) == 0 and len(sent) == 1


def test_deal_email_links_our_site_and_carries_the_footer_and_unsubscribe_headers():
    item = {**ev(title="Dyson <b>"), "slug": "b000000001-dyson-b", "image": "https://m.media-amazon.com/images/I/x.jpg"}
    m = mail.deals_mail("dyson", [item], LINKS, 5, 9, True, NOW)
    assert m.subject == "dyson: Dyson <b>, 55% off"
    for body in (m.text, m.html):
        assert "Data by Keepa" in body and "amazon.com/dp" not in body and "tag=" not in body
        assert "https://beta.fiftyoff.app/d/b000000001-dyson-b?s=email" in body
        assert "/m/" in body and "/u/" in body                        # Change alerts, Stop these emails
    assert "Dyson &lt;b&gt;" in m.html and "$90.00 (usually $200.00)" in m.text
    assert m.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert m.headers["List-Unsubscribe"].startswith("<https://beta.fiftyoff.app/u/")


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


def test_only_deals_the_site_shows_are_queued_and_sent():
    """User, 10-16: a faucet alert emailed deals on a hidden shelf, and the link opened 'deal not found'."""
    hidden = {"B000000001": False}
    m = Mem([ev()], {}, [alert(1, 1, "dyson", tier="plus")])
    assert notify.advance(m, NOW, CFG, lambda a: {x: hidden.get(x, True) for x in a}) == {"waiting": 1}
    assert not m.deliveries and m.status[1] == "waiting"                 # the snapshot may just be behind
    late = NOW + timedelta(minutes=CFG.visible_wait_minutes)
    assert notify.advance(m, late, CFG, lambda a: {x: False for x in a}) == {"skip": 1}
    assert not m.deliveries                                              # never listed: no email names it


def test_a_deal_that_left_the_site_before_sending_is_missed_and_an_unreachable_site_waits():
    m = Mem([ev()], {}, [alert(1, 1, "dyson")])
    notify.advance(m, NOW, CFG, lambda a: {x: True for x in a})
    sent, send = outbox()
    later = NOW + timedelta(hours=1)
    assert notify.send_due(m, send, later, CFG, LINKS, visible=lambda a: {x: None for x in a}) == 0
    assert m.deliveries[0]["status"] == "queued"                         # couldn't ask: try next pass
    assert notify.send_due(m, send, later, CFG, LINKS, visible=lambda a: {x: False for x in a}) == 0
    assert m.deliveries[0]["status"] == "stale" and m.alerts[1]["state"] == "watching" and not sent


def test_site_visible_asks_the_product_endpoint_with_the_site_host(monkeypatch):
    from fiftyoff import notifier
    seen = []

    class R:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *a): return self.body

    def fake(req, timeout):
        seen.append((req.full_url, req.get_header("Host")))
        if req.full_url.endswith("B0DOWN0001"):
            raise OSError("down")
        return R(b'{"deal": {"id": "B0LIVE0001"}}' if req.full_url.endswith("B0LIVE0001") else b'{"deal": null}')

    monkeypatch.setattr(notifier.urllib.request, "urlopen", fake)
    check = notifier.site_visible(notify.NotifyConfig(site="https://beta.fiftyoff.app", site_api="http://api:8000"))
    assert check(["B0LIVE0001", "B0HIDE0001", "B0DOWN0001"]) == {"B0LIVE0001": True, "B0HIDE0001": False, "B0DOWN0001": None}
    assert seen[0][0] == "http://api:8000/api/v1/product/B0LIVE0001" and seen[0][1].lower() == "beta.fiftyoff.app"
