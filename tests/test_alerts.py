"""Keyword alerts on the site (alerts-beta.md): signed links, sign-up, confirm, My alerts, stop, caching."""

from datetime import datetime, timedelta, timezone

from fiftyoff import alerts, mail, notify, tokens
from tests.test_api_v1 import HOST, make

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
KEY = "test-key"
CFG = notify.NotifyConfig(tiers={"free": {"delay_minutes": 30, "max_interests": 1, "one_shot": True, "lifetime_days": 30}})


def test_tokens_sign_verify_expiry_purpose_and_tampering():
    t = tokens.sign(KEY, "confirm", 7, 3, now=1000)
    assert tokens.verify(KEY, t, "confirm", now=1001) == {"p": "confirm", "s": 7, "i": 3, "e": 1000 + 24 * 3600}
    assert tokens.verify(KEY, t, "confirm", now=1000 + 24 * 3600 + 1) is None    # expired
    assert tokens.verify(KEY, t, "manage", now=1001) is None                     # wrong purpose
    assert tokens.verify("other", t, "confirm", now=1001) is None                # wrong key
    payload, sig = t.split(".")
    forged = tokens.sign(KEY, "confirm", 8, 3, now=1000).split(".")[0] + "." + sig
    assert tokens.verify(KEY, forged, "confirm", now=1001) is None               # someone else's id
    assert tokens.verify(KEY, "junk", "confirm") is None and tokens.verify(KEY, None, "confirm") is None


class Store:
    def __init__(self):
        self.subs, self.ints, self.caught_rows = {}, {}, []

    def by_email(self, email):
        return next((s for s in self.subs.values() if s["email"] == email), None)

    def subscriber(self, sid):
        return self.subs.get(sid)

    def create(self, email):
        sid = len(self.subs) + 1
        self.subs[sid] = {"id": sid, "email": email, "tier": "free", "paused": False, "verified_at": None}
        return self.subs[sid]

    def verify(self, sid, email):
        self.subs[sid]["verified_at"] = self.subs[sid]["verified_at"] or NOW

    def interests(self, sid):
        return sorted((i for i in self.ints.values() if i["sid"] == sid), key=lambda i: i["id"])

    def _row(self, sid, kw):
        return next((i for i in self.ints.values() if i["sid"] == sid and i["value"] == kw), None)

    def ask(self, sid, kw, source):
        i = self._row(sid, kw)
        if not i:
            iid = len(self.ints) + 1
            i = self.ints[iid] = {"id": iid, "sid": sid, "value": kw, "state": "pending", "armed_at": None, "ended_at": None,
                                  "source": source, "created_at": NOW}
        elif i["state"] != "watching":
            i["state"] = "pending"
        return i

    def put(self, sid, kw, source, now):
        i = self.ask(sid, kw, source)
        i.update(state="watching", armed_at=now, ended_at=None)
        return i

    def update(self, sid, iid, **f):
        if self.ints[iid]["sid"] == sid:
            self.ints[iid].update(f)

    def set_paused(self, sid, paused):
        self.subs[sid]["paused"] = paused

    def caught(self, sid, since):
        return [c for c in self.caught_rows if c["sid"] == sid]


def setup(**kw):
    store, sent = Store(), []
    a = alerts.Alerts(store, lambda address, m: sent.append((address, m)), KEY, f"https://{HOST}", CFG,
                      clock=lambda: NOW, **kw)
    _, client = make(alerts=a, site_open=True)
    return a, store, sent, client


def link_path(m: mail.Mail, prefix: str) -> str:
    import re
    return re.search(rf"https://{HOST}(/{prefix}/[^\s\"]+)", m.text).group(1)


def test_watch_confirm_then_my_alerts():
    a, store, sent, c = setup()
    r = c.post("/api/v1/watch", json={"email": "Me@Example.com", "keyword": " Dyson ", "source": "search"})
    assert r.status_code == 202 and r.headers["cache-control"] == "no-store"
    assert store.subs[1]["verified_at"] is None and store.ints[1]["state"] == "pending"
    (to, m), = sent
    assert to == "me@example.com" and m.subject == "Confirm alerts for 'dyson'"
    assert c.get("/api/v1/me").status_code == 401
    r = c.get(link_path(m, "c"))
    assert r.status_code == 303 and r.headers["location"] == "/watching/?q=dyson"
    assert store.subs[1]["verified_at"] == NOW and store.ints[1]["state"] == "watching" and store.ints[1]["armed_at"] == NOW
    me = c.get("/api/v1/me")
    assert me.status_code == 200 and me.headers["cache-control"] == "no-store"
    j = me.json()
    assert j["email"] == "me@example.com" and j["max"] == 1
    assert j["alerts"] == [{"id": 1, "keyword": "dyson", "state": "watching", "armed_at": "2026-10-15T12:00:00Z",
                            "ends_at": "2026-11-14T12:00:00Z", "ended_at": None}]
    assert c.get(link_path(m, "c")).headers["location"] == "/watching/?q=dyson"   # confirm is idempotent
    assert store.ints[1]["armed_at"] == NOW and store.ints[1]["source"] == "search"


def test_watch_answers_the_same_for_a_new_and_a_known_address():
    a, store, sent, c = setup()
    first = c.post("/api/v1/watch", json={"email": "a@x.io", "keyword": "dyson"})
    store.subs[1]["verified_at"] = NOW
    again = c.post("/api/v1/watch", json={"email": "a@x.io", "keyword": "dyson"})
    assert (first.status_code, first.json()) == (again.status_code, again.json())
    assert c.post("/api/v1/watch", json={"email": "nope", "keyword": "dyson"}).status_code == 422
    assert c.post("/api/v1/watch", json={"email": "a@x.io", "keyword": "x"}).status_code == 422


def test_signin_mails_only_verified_addresses_with_the_same_answer():
    a, store, sent, c = setup()
    store.create("known@x.io")
    store.verify(1, "known@x.io")
    store.create("pending@x.io")
    answers = {e: c.post("/api/v1/signin", json={"email": e}) for e in ("known@x.io", "pending@x.io", "stranger@x.io")}
    assert len({(r.status_code, r.json()["ok"]) for r in answers.values()}) == 1
    assert [to for to, _ in sent] == ["known@x.io"]
    r = c.get(link_path(sent[0][1], "m"))
    assert r.headers["location"] == "/my-alerts/" and c.get("/api/v1/me").json()["email"] == "known@x.io"


def signed_in(c, store, kw="dyson"):
    c.post("/api/v1/watch", json={"email": "me@x.io", "keyword": kw})
    sid = store.by_email("me@x.io")["id"]
    iid = next(i["id"] for i in store.interests(sid) if i["value"] == kw)
    c.get(f"/c/{tokens.sign(KEY, 'confirm', sid, iid)}")
    return sid


def test_free_tier_holds_one_keyword_and_a_second_gets_the_swap():
    a, store, sent, c = setup()
    sid = signed_in(c, store)
    r = c.post("/api/v1/me/alerts", json={"keyword": "kate spade", "source": "deal"})
    assert r.status_code == 409 and r.json() == {"error": "full", "keyword": "kate spade", "current": [{"id": 1, "keyword": "dyson"}]}
    # the anonymous form for a second keyword: confirm sends them to the swap sheet instead of arming it
    c.post("/api/v1/watch", json={"email": "me@x.io", "keyword": "kate spade"})
    m = sent[-1][1]
    assert c.get(link_path(m, "c")).headers["location"] == "/my-alerts/?swap=2"
    assert store.ints[2]["state"] == "pending"
    assert [(x["keyword"], x["state"]) for x in c.get("/api/v1/me").json()["alerts"]] == [("kate spade", "pending"), ("dyson", "watching")]
    j = c.post("/api/v1/me/alerts/2", json={"action": "swap"}).json()
    assert {x["keyword"]: x["state"] for x in j["alerts"]} == {"kate spade": "watching", "dyson": "stopped"}


def test_stop_undo_edit_rearm_and_pause():
    a, store, sent, c = setup()
    signed_in(c, store)
    post = lambda body: c.post("/api/v1/me/alerts/1", json=body)  # noqa: E731
    assert post({"action": "stop"}).json()["alerts"][0]["state"] == "stopped"
    assert post({"action": "undo"}).json()["alerts"][0]["state"] == "watching"
    j = post({"action": "edit", "keyword": "Dyson V15"}).json()
    assert j["alerts"][0]["keyword"] == "dyson v15"
    store.ints[1]["state"] = "fired"
    assert post({"action": "rearm"}).json()["alerts"][0]["state"] == "watching"
    assert post({"action": "nonsense"}).status_code == 422
    assert c.post("/api/v1/me/alerts/99", json={"action": "stop"}).status_code == 404
    assert c.post("/api/v1/me/pause", json={"paused": True}).json()["paused"] is True


def test_someone_elses_alert_is_out_of_reach():
    a, store, sent, c = setup()
    signed_in(c, store)
    other = store.create("other@x.io")
    store.put(other["id"], "shark", None, NOW)
    assert c.post("/api/v1/me/alerts/2", json={"action": "stop"}).status_code == 404
    assert store.ints[2]["state"] == "watching"


def test_one_click_stop_and_the_stop_page():
    a, store, sent, c = setup()
    sid = signed_in(c, store)
    t = tokens.sign(KEY, "stop", sid)
    assert c.get(f"/u/{t}").headers["location"] == "/my-alerts/?stop=all"
    assert store.ints[1]["state"] == "watching"            # a GET (a link scanner) doesn't stop anything
    r = c.post(f"/u/{t}", data={"List-Unsubscribe": "One-Click"})
    assert r.status_code == 200 and store.ints[1]["state"] == "stopped"
    assert c.get("/u/forged.token").headers["location"] == "/my-alerts/?link=expired"


def test_rate_limits():
    a, store, sent, c = setup(per_ip=alerts.RateLimit(3, 3600), per_email=alerts.RateLimit(1, 3600))
    codes = [c.post("/api/v1/watch", json={"email": "a@x.io", "keyword": "dyson"}).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]
    assert len(sent) == 1                                    # the address limit: same answer, no more email


def test_config_and_nothing_cacheable():
    a, store, sent, c = setup(is_open=lambda: True)
    r = c.get("/api/v1/alerts/config")
    assert r.json() == {"open": True, "delay_minutes": 30, "lifetime_days": 30, "max_free": 1}
    for path in ("/api/v1/alerts/config", "/api/v1/me", "/m/x", "/c/x", "/u/x"):
        assert c.get(path).headers["cache-control"] == "no-store", path


def test_without_a_secret_key_there_are_no_alert_routes(tmp_path):
    _, client = make(tmp_path, alerts=None, site_open=True)
    assert client.post("/api/v1/watch", json={"email": "a@x.io", "keyword": "dyson"}).status_code in (404, 405)
