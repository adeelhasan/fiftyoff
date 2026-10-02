"""API on a stubbed feed query: no database, no network (in-process ASGI client)."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from fiftyoff.api import create_app


def rows(category, sort, limit):
    now = datetime.now(timezone.utc)
    return [{"asin": "B0TEST0001", "title": "Drill", "category": "Tools & Home Improvement", "cond": "Used - Like New",
             "resale_cents": 5999, "pct_off": 52, "last_confirmed_at": now - timedelta(minutes=12),
             "unconfirmed": False, "url": "https://www.amazon.com/dp/B0TEST0001?aod=1"}][:limit]


def test_feed_has_only_consented_fields_and_attribution():
    c = TestClient(create_app(fetch=rows, password=""))
    r = c.get("/api/feed?sort=discount").json()
    d = r["deals"][0]
    assert set(d) == {"asin", "title", "category", "condition", "price", "pct_off", "url", "last_confirmed_at",
                      "minutes_since_confirmed", "unconfirmed"}       # no reference price, rank or image (D19)
    assert d["price"] == 59.99 and d["minutes_since_confirmed"] in (11, 12)   # floor of elapsed minutes
    assert r["attribution"] == {"text": "Data by Keepa", "url": "https://keepa.com"}


def test_bad_sort_is_rejected_and_preview_serves():
    c = TestClient(create_app(fetch=rows, password=""))
    assert c.get("/api/feed?sort=drop table").status_code == 422
    page = c.get("/closed-preview")
    assert page.status_code == 200 and "Data by Keepa" in page.text


def test_login_popup_guards_everything_but_health():
    import base64
    c = TestClient(create_app(fetch=rows, password="s3cret"))
    r = c.get("/closed-preview")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert c.get("/api/health").status_code == 200
    ok = {"Authorization": "Basic " + base64.b64encode(b"fiftyoff:s3cret").decode()}
    assert c.get("/api/feed", headers=ok).status_code == 200
    bad = {"Authorization": "Basic " + base64.b64encode(b"fiftyoff:nope").decode()}
    assert c.get("/api/feed", headers=bad).status_code == 401
    assert c.get("/api/feed", headers=ok).headers["x-robots-tag"] == "noindex, nofollow"


def test_feed_query_is_cached():
    calls = []
    def counting(*a):
        calls.append(a)
        return rows(*a)
    c = TestClient(create_app(fetch=counting, password=""))
    for _ in range(5):
        c.get("/api/feed")
    assert len(calls) == 1
