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


PUBLIC_PRODUCT = {"appeal", "delight", "asin", "title", "category", "image", "url", "score", "score_parts", "pct_off", "price", "near_miss",
                  "unit_count", "minutes_since_confirmed", "minutes_since_priced", "is_new", "confidence", "verified", "units",
                  "subcategory", "variants", "check_reference", "source", "inverted"}
PUBLIC_UNIT = {"condition", "price", "pct_off", "score", "minutes_since_confirmed", "unconfirmed", "confidence"}


def status_stub():
    now = datetime.now(timezone.utc)
    return {"funnel": {"watching": 10, "watched_ever": 12, "units_live": 9, "units_unconfirmed": 1, "units_gone": 2,
                       "units_revived": 0, "products_with_signals": 10, "tracking_since": now - timedelta(days=2)},
            "hourly": [{"hour": now, "new_watches": 3, "new_50": 1, "checks": 160, "failed": 2, "check_tokens": 1100,
                        "gone": 1}],
            "state": {"heartbeat": now.timestamp() - 30, "last_sweep": now.timestamp() - 600,
                      "status": {"tokens_spent": 5000, "token_cap": 403200, "fast_lane": 17}},
            "census": [{"cat_id": 165793011, "category": "Toys & Games", "swept_at": now, "listings": 900, "products": 800,
                        "qualifying_products": 120, "products_50": 60, "products_50_100": 25, "median_strict": 0.41,
                        "share_popular": 0.3, "median_ref_usd": 64}]}


def app(**kw):
    kw.setdefault("fetch_review", lambda: [])
    kw.setdefault("fetch_seen", lambda: [])
    kw.setdefault("fetch", rows)
    kw.setdefault("fetch_appeal", lambda: [])
    kw.setdefault("fetch_kind_map", lambda: [])
    kw.setdefault("fetch_shelves", lambda: [])
    return TestClient(create_app(fetch_gone=gone_rows, fetch_status=status_stub, password="", **kw))


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
    assert c.get("/api/feed?q=rill").json()["products"] == []          # word starts only
    assert [p["asin"] for p in c.get("/api/feed?q=drills").json()["products"]] == ["B0TEST0001"]   # plural finds singular
    assert [g["asin"] for g in c.get("/api/gone?q=espresso").json()["gone"]] == ["B0GONE0001"]
    assert c.get("/api/gone?q=drill").json()["gone"] == []


def test_bad_sort_is_rejected_and_preview_serves():
    c = app()
    assert c.get("/api/feed?sort=drop table").status_code == 422
    page = c.get("/closed-preview")
    assert page.status_code == 200 and "Data by Keepa" in page.text
    assert "Data by Keepa" in c.get("/closed-preview/gone").text
    assert "Data by Keepa" in c.get("/closed-preview/status").text


def test_login_popup_guards_everything_but_health():
    import base64
    c = TestClient(create_app(fetch_seen=lambda: [], fetch=rows, fetch_gone=gone_rows, password="s3cret"))
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
    c = TestClient(create_app(fetch_seen=lambda: [], fetch=counting, fetch_gone=gone_rows, password=""))
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
    c = TestClient(create_app(fetch_seen=lambda: [], fetch=lambda: [fresh_drop, settled, missed], fetch_gone=gone_rows,
                              fetch_status=status_stub, fetch_review=lambda: [], password=""))
    r = c.get("/api/feed").json()
    assert [p["asin"] for p in r["products"]] == ["B0OLD00001"] and r["held_back"] == 2
    assert r["products"][0]["confidence"]["label"] == "HIGH"            # 2.5 h on a settled listing: still likely
    every = {p["asin"]: p["confidence"] for p in c.get("/api/feed?conf=all").json()["products"]}
    assert every["B0HOT00001"]["label"] == "LOW" and every["B0HOT00001"]["hot"]
    assert every["B0MISS0001"]["label"] == "LOW"                         # our last check didn't find it


def test_new_deals_sort_first_and_fresh_filter():
    now = datetime.now(timezone.utc)
    fresh = {**_row("B0NEW00001", "New Lamp", 0.51, "Used - Like New", 4900, 10000), "priced_at": now - timedelta(hours=2)}
    c = TestClient(create_app(fetch_seen=lambda: [], fetch=lambda: rows() + [fresh], fetch_gone=gone_rows, fetch_status=status_stub, fetch_review=lambda: [], password=""))
    ps = c.get("/api/feed?sort=newest").json()["products"]
    assert ps[0]["asin"] == "B0NEW00001" and ps[0]["is_new"] and ps[0]["minutes_since_priced"] in (119, 120)
    assert [p["asin"] for p in c.get("/api/feed?fresh=true").json()["products"]] == ["B0NEW00001"]


def test_status_reports_funnel_hourly_and_tracker():
    r = app().get("/api/status").json()
    f = r["funnel"]
    assert f["watching"] == 10 and f["qualifying_units"] == 4 and f["qualifying_products"] == 3
    assert f["products_50"] == 2 and f["products_50_no_acceptable"] == 2 and f["products_shown_default"] == 2
    assert r["hourly"][0]["checks"] == 160 and r["tracker"]["fast_lane"] == 17
    assert r["census"][0]["category"] == "Toys & Games" and r["census"][0]["median_strict"] == 0.41
    assert 0.4 <= r["tracker"]["heartbeat_minutes_ago"] <= 0.6 and r["tracker"]["last_sweep_minutes_ago"] == 10.0


def _seen(asin, title, strict, price, ref, minutes, source="feed", **kw):
    r = {**_row(asin, title, strict, "Used - Like New", price, ref, minutes=minutes),
         "source": source, "offer_id": None, "reviews": None, "monthly_sold": None, "amazon_sells": None,
         "rating": None, "cat_path": None, "parent_asin": None, "cats": [11], "ref_flags": None, "drops30": 8}
    return {**r, **kw}


NODES = [{"id": 1, "name": "Tools & Home Improvement", "parent_id": None}, {"id": 5, "name": "Categories", "parent_id": 1},
         {"id": 9, "name": "Kitchen & Bath Fixtures", "parent_id": 5}, {"id": 11, "name": "Kitchen Faucets", "parent_id": 9},
         {"id": 12, "name": "Ice Makers", "parent_id": 9}]


def test_seen_only_layer_windows_labels_and_filters():
    """D39: seen-in-feed cards (sweeps beyond the rank limit, census) show by default for 36 h, 7 days in "Seen only";
    they're dashed (verified False), never held back on confidence, carry reference warnings, and an ASIN we
    live-check never shows twice."""
    seen = [_seen("B0SEEN0001", "Kitchen Faucet", 0.58, 9000, 25000, minutes=20 * 60),
            _seen("B0SEEN0002", "Old Faucet", 0.58, 9000, 25000, minutes=3 * 24 * 60),
            _seen("B0SEEN0003", "Odd Faucet", 0.80, 5000, 25000, minutes=60,
                  ref_flags={"flags": ["above_list"]}),
            _seen("B0TEST0001", "Cordless Drill", 0.70, 3000, 12500, minutes=60),          # also live: dropped
            _seen("B0CENS0001", "Car Jump Starter", 0.58, 8400, 20000, minutes=90, source="census",
                  category="Toys & Games", cats=None)]
    c = app(fetch_seen=lambda: seen, fetch_nodes=lambda: NODES)
    r = c.get("/api/feed").json()
    by = {p["asin"]: p for p in r["products"]}
    assert {"B0SEEN0001", "B0SEEN0003", "B0CENS0001"} <= set(by) and "B0SEEN0002" not in by
    assert by["B0SEEN0001"]["verified"] is False and by["B0SEEN0001"]["source"] == "feed"
    assert by["B0SEEN0001"]["subcategory"] == "Kitchen & Bath Fixtures › Kitchen Faucets"   # structural node skipped
    assert by["B0SEEN0003"]["check_reference"] == ["above_list"] and by["B0SEEN0001"]["check_reference"] == []
    assert by["B0TEST0001"]["verified"] is True and by["B0TEST0001"]["subcategory"] is None
    only = {p["asin"] for p in c.get("/api/feed?show=seen").json()["products"]}
    assert only == {"B0SEEN0001", "B0SEEN0002", "B0SEEN0003", "B0CENS0001"}
    assert all(p["verified"] for p in c.get("/api/feed?show=live").json()["products"])
    sub = c.get("/api/feed?sub=Kitchen %26 Bath Fixtures › Kitchen Faucets").json()["products"]
    assert {p["asin"] for p in sub} == {"B0SEEN0001", "B0SEEN0003"}
    assert c.get("/api/feed?show=bogus").status_code == 422
    order = [p["asin"] for p in c.get("/api/feed?show=seen").json()["products"]]
    assert order.index("B0SEEN0003") > order.index("B0SEEN0001")   # flagged ranks lower despite 80% off


def test_cards_group_by_parent_and_best_sort_caps_each_subcategory():
    """D39: sizes/colours under one parent are one card; "best" lets 2 per subcategory through before the rest."""
    rings = [_seen(f"B0RING000{i}", f"Smart Ring size {i}", 0.60 + i / 100, 12000, 35000, 60, parent_asin="B0RINGPAR0")
             for i in range(3)]
    ice = [_seen(f"B0ICE0000{i}", f"Ice Maker {i}", 0.70 - i / 100, 9000, 30000, 60, cats=[12]) for i in range(4)]
    c = app(fetch=lambda: [], fetch_seen=lambda: rings + ice + [_seen("B0FAUC0001", "Faucet", 0.55, 9000, 20000, 60)],
            fetch_nodes=lambda: NODES)
    r = c.get("/api/feed").json()
    ring = next(p for p in r["products"] if p["title"].startswith("Smart Ring"))
    assert ring["variants"] == 3 and ring["unit_count"] == 3 and r["asins"] == 8 and r["count"] == 6
    subs = [p["subcategory"].split(" › ")[-1] for p in r["products"]]
    assert subs[:3].count("Ice Makers") <= 2 and subs.count("Ice Makers") == 4      # capped, not dropped
    by_score = c.get("/api/feed?sort=discount").json()["products"]
    assert [p["subcategory"].split(" › ")[-1] for p in by_score][:3] == ["Ice Makers"] * 3   # other sorts: no cap


def _queue_row(asin, listed, **kw):
    now = datetime.now(timezone.utc)
    return {"asin": asin, "status": "pending", "layer": "check", "reasons": ["thin", "too_good"], "rules": "r0.1",
            "title": "Jabra", "image": None, "cond": "Used - Like New", "resale_cents": 4790, "ref_cents": 21350,
            "strict": 0.776, "ref_flags": {"flags": ["third_party_only", "thin"]}, "ref_parts": {"new_now": 21499},
            "updated_at": now, "first_held_at": now, "visibility": "auto", "tags": [], "note": None,
            "decided_ref_cents": None, "decided_at": None, "decided_by": None,
            "unlisted_why": None if listed else "held", "listed": listed, **kw}


def basic(user, pw):
    import base64
    return {"authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


ADMIN = basic("admin", "adm1n")


def admin_app(**kw):
    kw.setdefault("fetch_review", lambda: [])
    kw.setdefault("fetch_curated", lambda: [])
    return TestClient(create_app(fetch_seen=lambda: [], fetch=rows, fetch_gone=gone_rows, fetch_status=status_stub, password="s3cret",
                                 admin_password="adm1n", tags=("featured", "newsletter"), **kw))


def test_admin_review_queue_lists_held_deals():
    now = datetime.now(timezone.utc)
    queue = [_queue_row("B0HELD0001", False, first_held_at=now - timedelta(hours=5)),
             _queue_row("B000000OLD", True, status="cleared", reasons=[]),
             _queue_row("B000000APR", True, visibility="approved", decided_ref_cents=22000, decided_at=now),
             _queue_row("B000000LAP", False, visibility="approved", decided_ref_cents=10000, unlisted_why="approval_lapsed",
                        reasons=["thin"])]
    c = admin_app(fetch_review=lambda: queue)
    body = c.get("/admin/api/review?sort=reasons", headers=ADMIN).json()
    assert [i["asin"] for i in body["items"]] == ["B0HELD0001", "B000000LAP"]
    newest = c.get("/admin/api/review", headers=ADMIN).json()["items"]           # default: newest hold on top
    assert [i["asin"] for i in newest] == ["B000000LAP", "B0HELD0001"] and newest[1]["minutes_since_held"] == 300
    assert body["counts"] == {"held": 2, "listed": 2, "approved": 2, "lapsed": 1}
    assert body["items"][0]["ref"] == 213.50 and body["items"][0]["pct_off"] == 78 and body["tags"] == ["featured", "newsletter"]
    assert body["items"][1]["why"] == "approval_lapsed" and body["items"][1]["decided_ref"] == 100.0
    assert [i["asin"] for i in c.get("/admin/api/review?status=listed&sort=reasons", headers=ADMIN).json()["items"]] == \
        ["B000000APR", "B000000OLD"]  # most reasons first
    assert c.get("/admin/", headers=ADMIN).status_code == 200
    # the status page counts what is out of the feed, not raw pending rows
    assert c.get("/api/status", headers=ADMIN).json()["funnel"]["held_for_review"] == 2


def test_admin_curate_validates_and_records_identity():
    calls = []

    def curate(asin, change, tags, by):
        from fiftyoff import curation
        new, log = curation.apply(None, change, tags, 21350)
        calls.append((asin, by, log))
        return {**new, "changed": [f for f, _, _ in log]}

    c = admin_app(curate=curate)
    r = c.post("/admin/api/curation/B0HELD0001", json={"visibility": "approved", "tags_add": ["featured"]}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["visibility"] == "approved" and r.json()["decided_ref_cents"] == 21350
    assert calls[0][:2] == ("B0HELD0001", "admin")
    assert c.post("/admin/api/curation/B0HELD0001", json={"tags_add": ["spam"]}, headers=ADMIN).status_code == 400
    assert c.post("/admin/api/curation/B0HELD0001", json={"visibility": "delete"}, headers=ADMIN).status_code == 400
    assert c.post("/admin/api/curation/not-an-asin", json={"visibility": "hidden"}, headers=ADMIN).status_code == 400


def test_admin_routes_need_the_admin_password():
    c = admin_app()
    preview = basic("fiftyoff", "s3cret")
    for path in ("/admin/", "/admin/api/review", "/admin/api/curation"):
        assert c.get(path).status_code == 401
        assert c.get(path, headers=preview).status_code == 401              # the preview login is not enough
        assert c.get(path, headers=ADMIN).status_code == 200
    assert c.post("/admin/api/curation/B0HELD0001", json={"visibility": "hidden"}, headers=preview).status_code == 401
    assert 'realm="fiftyoff admin"' in c.get("/admin").headers["www-authenticate"]
    assert c.get("/api/feed", headers=preview).status_code == 200            # preview login still opens the feed
    assert c.get("/api/feed", headers=ADMIN).status_code == 200              # and so does the admin one
    assert c.get("/api/health").status_code == 200
    r = c.get("/closed-preview/review", headers=preview, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/admin/"
    assert c.get("/admin", headers=ADMIN, follow_redirects=False).headers["location"] == "/admin/"
    assert c.get("/api/review", headers=ADMIN).status_code == 404            # the D35 routes are gone


def test_rank_reaches_admins_only():
    """D24: the sales rank in the score tooltip goes to admins; the preview login never gets it."""
    c = admin_app()
    preview = basic("fiftyoff", "s3cret")
    for path, key in (("/api/feed?tier=all&acceptable=true", "products"), ("/api/gone", "gone")):
        assert all("rank" not in p for p in c.get(path, headers=preview).json()[key])
        items = c.get(path, headers=ADMIN).json()[key]
        assert items and all("rank" in p for p in items)
    assert c.get("/api/feed?tier=all&acceptable=true", headers=ADMIN).json()["products"][0]["rank"] is not None


def test_admin_is_closed_without_an_admin_password():
    c = TestClient(create_app(fetch_seen=lambda: [], fetch=rows, fetch_gone=gone_rows, fetch_review=lambda: [], password="", admin_password=""))
    assert c.get("/api/feed").status_code == 200
    assert c.get("/admin/").status_code == 401
    assert c.get("/admin/api/review", headers=basic("admin", "")).status_code == 401


def test_admin_tags_fall_back_when_the_config_is_missing(tmp_path):
    from fiftyoff.api import admin_tags
    assert admin_tags(tmp_path / "nope.toml") == ("featured", "newsletter")
    (tmp_path / "p.toml").write_text('[admin]\ntags = ["featured", "deals-of-the-week"]\n')
    assert admin_tags(tmp_path / "p.toml") == ("featured", "deals-of-the-week")


def test_inverted_deals_filter_and_list_price_cap():
    """10-06 A/B test: a third-party-only reference above the list price is "inverted"; the filter shows only those,
    and the cap measures them against the list price (a shoe: 60% -> ~24%, so it leaves the feed)."""
    flags = {"list": 8500, "flags": ["third_party_only", "above_list"]}
    shoe = _seen("B0INVERT01", "Running Shoe", 0.60, 6500, 16000, 60, ref_flags=flags)
    near = _seen("B0NEARLIST", "Leviton Box", 0.75, 5200, 21200, 60,
                 ref_flags={"list": 20300, "flags": ["above_list"]})        # Amazon-priced: not inverted
    c = app(fetch_seen=lambda: [shoe, near], fetch_nodes=lambda: NODES)
    r = c.get("/api/feed").json()
    by = {p["asin"]: p for p in r["products"]}
    assert by["B0INVERT01"]["inverted"] == {"list": 85.0, "pct_off_vs_list": 24} and by["B0NEARLIST"]["inverted"] is None
    assert r["inverted_count"] == 1
    assert [p["asin"] for p in c.get("/api/feed?inverted=true").json()["products"]] == ["B0INVERT01"]
    capped = {p["asin"] for p in c.get("/api/feed?cap=true&tier=all").json()["products"]}
    assert "B0INVERT01" not in capped and "B0NEARLIST" in capped


def test_delight_ranks_appealing_products_first_and_appeal_min_filters():
    """D42: the model's appeal judgement (per parent, else ASIN) feeds delight; unrated products count as 4."""
    keys = [r.get("parent_asin") or r["asin"] for r in rows()]
    judged = [{"key": keys[-1], "score": 9, "tags": ["travel"], "why": "Samsonite luggage set", "model": "sonnet", "prompt_v": "a0.1"}]
    c = app(fetch_appeal=lambda: judged)
    r = c.get("/api/feed?tier=all&acceptable=true&sort=delight").json()
    top = r["products"][0]
    assert (top.get("appeal") or {}).get("score") == 9 and r["delight_version"] == "l0.2"
    assert top["delight"] == round(9 * top["pct_off"] / 10 * top["score_parts"]["condition_factor"], 1)
    assert all(p["appeal"] is None for p in r["products"][1:])
    only = c.get("/api/feed?tier=all&acceptable=true&appeal_min=7").json()["products"]
    assert [p["appeal"]["score"] for p in only] == [9]


SHELVES = [{"id": "luggage", "name": "luggage", "aisle": "travel", "role": "front", "proposed_role": "front",
            "role_reason": "Fun to browse", "version": "s0.1"},
           {"id": "pc-components", "name": "pc components", "aisle": "tech", "role": "aisle", "proposed_role": "aisle",
            "role_reason": "Enthusiasts only", "version": "s0.1"},
           {"id": "auto-parts", "name": "auto parts", "aisle": "auto", "role": "hidden", "proposed_role": "hidden",
            "role_reason": "Parts", "version": "s0.1"}]


def _judged(**over):
    base = [{"key": "B0TEST0001", "score": 9, "tags": [], "why": "Coveted", "model": "sonnet", "prompt_v": "a0.3",
             "aisle": "travel", "kind": "hardside luggage", "fit": False, "shelf": "luggage", "size": "-"},
            {"key": "B0TEST0003", "score": 6, "tags": [], "why": "Enthusiast part", "model": "sonnet", "prompt_v": "a0.3",
             "aisle": "tech", "kind": "pc fans", "fit": False, "shelf": None, "size": None}]
    for k, v in over.items():
        base[0][k] = v
    return base


def test_shelves_show_front_on_home_and_aisle_shelves_inside_their_aisle():
    """D46: roles decide where a shelf shows; a0.3's shelf id wins, kind_map places older ratings."""
    kmap = [{"kind": "pc fans", "shelf": "pc-components", "aisle": "tech", "version": "k0.2"}]
    c = app(fetch_appeal=lambda: _judged(), fetch_kind_map=lambda: kmap, fetch_shelves=lambda: SHELVES)
    home = c.get("/api/shelves").json()
    assert [x["id"] for x in home["shelves"]] == ["luggage"] and home["shelves"][0]["shelf"] == "luggage"
    assert {a["aisle"]: a["count"] for a in home["aisles"]} == {"travel": 1, "tech": 1}  # chips count the aisle view
    tech = c.get("/api/shelves?aisle=tech").json()
    assert [x["id"] for x in tech["shelves"]] == ["pc-components"]
    assert "proposed_role" not in tech["shelves"][0] and "held_for_price" not in tech  # admin-only fields
    one = c.get("/api/shelves?shelf=luggage").json()["shelves"]
    assert len(one) == 1 and one[0]["products"][0]["appeal"]["why"] == "Coveted"


def test_shelves_hide_junk_size_dependent_and_hidden_shelves_unless_everything():
    c = app(fetch_appeal=lambda: _judged(shelf="auto-parts", score=1), fetch_shelves=lambda: SHELVES)
    assert "auto-parts" not in [x["id"] for x in c.get("/api/shelves?aisle=auto").json()["shelves"]]
    assert "auto-parts" in [x["id"] for x in c.get("/api/shelves?everything=true").json()["shelves"]]
    c = app(fetch_appeal=lambda: _judged(fit=True, size="9.5"), fetch_shelves=lambda: SHELVES)
    p = c.get("/api/shelves").json()["shelves"][0]["products"][0]
    assert p["size"] == "9.5"
    assert "luggage" not in [x["id"] for x in c.get("/api/shelves?nofit=true").json()["shelves"]]


def test_shelves_hold_placeholder_reference_prices():
    """D46: a reference over 50x its shelf's median (5+ products) is a seller's placeholder: held from the shelves."""
    base = rows()[0]
    many = [{**base, "asin": f"B0SHELF{i:03d}", "parent_asin": None, "ref_cents": 12000} for i in range(6)]
    fake = {**base, "asin": "B0SHELF999", "parent_asin": None, "ref_cents": 12000 * 100}
    judged = [{"key": r["asin"], "score": 8, "tags": [], "why": "x", "model": "sonnet", "prompt_v": "a0.3",
               "aisle": "travel", "kind": "k", "fit": False, "shelf": "luggage", "size": None} for r in many + [fake]]
    c = app(fetch=lambda: many + [fake], fetch_appeal=lambda: judged, fetch_shelves=lambda: SHELVES)
    asins = [p["asin"] for p in c.get("/api/shelves?shelf=luggage").json()["shelves"][0]["products"]]
    assert len(asins) == 6 and "B0SHELF999" not in asins


def test_freshness_lifts_deals_keepa_priced_recently_and_fades_by_three_days():
    """l0.2: x1.3 within 24 h of Keepa pricing the deal, linear to x1 at 3 days, so shelves change between visits."""
    from fiftyoff.api import freshness
    assert freshness(None) == freshness(72 * 60) == freshness(10 * 24 * 60) == 1.0
    assert freshness(0) == freshness(24 * 60) == 1.3
    assert abs(freshness(48 * 60) - 1.15) < 1e-9
    now = datetime.now(timezone.utc)
    old = {**rows()[0], "asin": "B0OLD00001", "parent_asin": None}
    new = {**old, "asin": "B0NEW00001", "priced_at": now - timedelta(hours=2)}
    judged = [{"key": r["asin"], "score": 8, "tags": [], "why": "x", "model": "sonnet", "prompt_v": "a0.3",
               "aisle": "travel", "kind": "k", "fit": False, "shelf": "luggage", "size": None} for r in (old, new)]
    c = app(fetch=lambda: [old, new], fetch_appeal=lambda: judged, fetch_shelves=lambda: SHELVES)
    r = c.get("/api/shelves").json()
    ps = r["shelves"][0]["products"]
    assert [p["asin"] for p in ps] == ["B0NEW00001", "B0OLD00001"] and r["delight_version"] == "l0.2"
    assert ps[0]["delight"] == round(ps[1]["delight"] * 1.3, 1)


def test_feed_keeps_the_tiers_while_shelves_take_the_40_dollar_band():
    """D46: seen-only rows outside the tiers (50%+ from a $40-99 reference) reach the shelves, never the main feed."""
    cheap = {**rows()[0], "asin": "B0CHEAP001", "parent_asin": None, "ref_cents": 6000, "resale_cents": 2500,
             "strict": 0.58, "source": "feed", "in_tiers": False}
    c = app(fetch_seen=lambda: [cheap])
    assert "B0CHEAP001" not in [p["asin"] for p in c.get("/api/feed?tier=all&acceptable=true").json()["products"]]
    shelves = c.get("/api/shelves?everything=true").json()["shelves"]
    assert "B0CHEAP001" in [p["asin"] for s in shelves for p in s["products"]]


def test_shelf_roles_are_set_by_admins_only():
    calls = []
    c = admin_app(fetch_shelves=lambda: SHELVES, set_shelf_role=lambda i, r, by: calls.append((i, r, by)) or {"id": i, "role": r})
    preview = basic("fiftyoff", "s3cret")
    assert c.post("/admin/api/shelf/luggage", json={"role": "aisle"}, headers=preview).status_code == 401
    assert c.post("/admin/api/shelf/luggage", json={"role": "sideways"}, headers=ADMIN).status_code == 400
    assert c.post("/admin/api/shelf/luggage", json={"role": "aisle"}, headers=ADMIN).json()["role"] == "aisle"
    assert calls == [("luggage", "aisle", "admin")]
    d = c.get("/api/shelves?review=true", headers=ADMIN).json()
    assert d["admin"] and {x["id"] for x in d["shelves"]} >= {"luggage", "pc-components", "auto-parts"}  # empty ones too
    assert "held_for_price" in d and d["shelves"][0]["proposed_role"]
