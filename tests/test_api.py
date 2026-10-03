"""API on a stubbed feed query: no database, no network (in-process ASGI client)."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from fiftyoff.api import create_app


def _row(asin, title, strict, cond, price, ref, minutes=12, **sig):
    now = datetime.now(timezone.utc)
    return {"asin": asin, "offer_id": hash((asin, cond, price)) % 10**6, "title": title,
            "category": "Tools & Home Improvement", "image": "{52,49,82,103,46,106,112,103}", "cond": cond,
            "resale_cents": price, "ref_cents": ref, "strict": strict,
            "last_confirmed_at": now - timedelta(minutes=minutes), "last_seen_at": now - timedelta(minutes=minutes),
            "unconfirmed": False, "priced_at": now - timedelta(days=3), "brand": "Acme", "cat_path": ["Tools"], "rating": 4.6, "rank": 1200,
            **{"reviews": 5000, "drops30": 40, "monthly_sold": 300, "amazon_sells": True, **sig}}


def rows():
    return [_row("B0TEST0001", "Cordless Drill", 0.52, "Used - Like New", 5999, 12500),
            _row("B0TEST0001", "Cordless Drill", 0.55, "Used - Acceptable", 5600, 12500),
            _row("B0TEST0002", "Shop Vac", 0.42, "Used - Very Good", 11000, 19000, minutes=3),
            _row("B0TEST0003", "Obscure Widget", 0.60, "Used - Like New", 8000, 20000,
                 reviews=2, drops30=1, monthly_sold=None, amazon_sells=False)]


def gone_rows():
    now = datetime.now(timezone.utc)
    r = _row("B0GONE0001", "Espresso Machine", 0.61, "Used - Like New", 21000, 54000, minutes=540)
    # appeared after a check 13 h ago, seen from 12 h to 9 h ago, missed 8.5 h ago, declared gone 2.5 h ago
    return [{**r, "first_seen_at": now - timedelta(hours=12), "appeared_after_at": now - timedelta(hours=13),
             "keepa_first_seen_at": None, "absent_since_at": now - timedelta(hours=8.5),
             "gone_at": now - timedelta(hours=2.5), "revivals": 0}]


PUBLIC_PRODUCT = {"asin", "title", "category", "image", "url", "score", "score_parts", "pct_off", "price", "near_miss",
                  "unit_count", "minutes_since_confirmed", "confidence", "units"}
PUBLIC_UNIT = {"condition", "price", "pct_off", "score", "minutes_since_confirmed", "unconfirmed", "confidence"}


def app(**kw):
    return TestClient(create_app(fetch=rows, fetch_gone=gone_rows, password="", **kw))


def test_feed_emits_public_fields_only_and_attribution():
    r = app().get("/api/feed?tier=all&acceptable=true").json()
    for p in r["products"]:
        # D19 guardrail: the score is ours; its inputs (reference price, reviews, rank, brand...) never leave
        assert set(p) == PUBLIC_PRODUCT and all(set(u) == PUBLIC_UNIT for u in p["units"])
    assert r["attribution"] == {"text": "Data by Keepa", "url": "https://keepa.com"}
    assert r["score_version"] == "s0.2"
    gone = app().get("/api/gone").json()["gone"][0]
    assert set(gone) == {"asin", "title", "category", "image", "url", "condition", "price", "pct_off", "score",
                         "score_parts", "lifespan", "near_miss", "minutes_since_seen"}
    assert set(r["products"][0]["score_parts"]) == {"discount", "demand", "savings", "rating", "condition_factor"}
    parts = r["products"][0]["score_parts"]
    assert abs(sum(parts[k] for k in ("discount", "demand", "savings", "rating")) - r["products"][0]["score"]) < 1
    assert gone["lifespan"]["confidence"] == "MEDIUM" and gone["lifespan"]["lower_min"] == 180 and gone["lifespan"]["upper_min"] == 270
    assert gone["price"] == 210.0 and gone["minutes_since_seen"] in (539, 540)   # D27: the price that was missed


def test_feed_groups_by_asin_and_defaults_to_headline_deals():
    c = app()
    default = c.get("/api/feed").json()["products"]          # 50%+, no Acceptable, best first
    assert [p["asin"] for p in default] == ["B0TEST0001", "B0TEST0003"]
    assert default[0]["unit_count"] == 1 and default[0]["image"].endswith("/41Rg.jpg")
    drill = c.get("/api/feed?acceptable=true").json()["products"][0]
    assert drill["unit_count"] == 2 and drill["price"] == 56.0 and drill["pct_off"] == 55
    assert drill["units"][0]["condition"] == "Used - Like New"  # the better unit leads despite the lower % off
    near = {p["asin"]: p["near_miss"] for p in c.get("/api/feed?tier=all").json()["products"]}
    assert near == {"B0TEST0001": False, "B0TEST0002": True, "B0TEST0003": False}
    assert [p["asin"] for p in c.get("/api/feed?q=drill").json()["products"]] == ["B0TEST0001"]


def test_bad_sort_is_rejected_and_preview_serves():
    c = app()
    assert c.get("/api/feed?sort=drop table").status_code == 422
    page = c.get("/closed-preview")
    assert page.status_code == 200 and "Data by Keepa" in page.text
    assert "Data by Keepa" in c.get("/closed-preview/gone").text


def test_login_popup_guards_everything_but_health():
    import base64
    c = TestClient(create_app(fetch=rows, fetch_gone=gone_rows, password="s3cret"))
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
    c = TestClient(create_app(fetch=counting, fetch_gone=gone_rows, password=""))
    for _ in range(5):
        c.get("/api/feed")
    assert len(calls) == 1


def test_low_confidence_units_are_held_back_by_default():
    now = datetime.now(timezone.utc)
    fresh_drop = {**_row("B0HOT00001", "Area Rug", 0.63, "Used - Like New", 30907, 83787, minutes=150),
                  "priced_at": now - timedelta(hours=3)}           # the 2026-10-02 rug: hot, unconfirmed 2.5 h
    settled = _row("B0OLD00001", "Old Drill", 0.55, "Used - Like New", 9000, 20000, minutes=150)
    missed = {**_row("B0MISS0001", "Missed Vac", 0.55, "Used - Like New", 9000, 20000, minutes=30),
              "unconfirmed": True}
    c = TestClient(create_app(fetch=lambda: [fresh_drop, settled, missed], fetch_gone=gone_rows, password=""))
    r = c.get("/api/feed").json()
    assert [p["asin"] for p in r["products"]] == ["B0OLD00001"] and r["held_back"] == 2
    assert r["products"][0]["confidence"]["label"] == "HIGH"            # 2.5 h on a settled listing: still likely
    every = {p["asin"]: p["confidence"] for p in c.get("/api/feed?conf=all").json()["products"]}
    assert every["B0HOT00001"]["label"] == "LOW" and every["B0HOT00001"]["hot"]
    assert every["B0MISS0001"]["label"] == "LOW"                         # our last check didn't find it
