"""Public API v1 and the beta site (docs/handoffs/api-v1.md) on a fixed fixture store and a fixed clock.

The responses are the canonical contract in tests/fixtures/api_v1/ (web/fixtures copies it). After a deliberate
contract change, regenerate them with: UPDATE_FIXTURES=1 uv run pytest tests/test_api_v1.py
"""

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fiftyoff import api_v1
from fiftyoff.api import create_app

NOW = datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "api_v1"
HOST = "beta.fiftyoff.app"
LIKE_NEW, VERY_GOOD, GOOD, ACCEPTABLE = "Used - Like New", "Used - Very Good", "Used - Good", "Used - Acceptable"


def _live(asin, title, image, cond, price, ref, priced_h, parent=None, seen_min=20, **kw):
    return {"asin": asin, "offer_id": hash((asin, cond, price)) % 10**6, "title": title, "category": "Electronics",
            "image": image, "cond": cond, "resale_cents": price, "ref_cents": ref, "strict": round(1 - price / ref, 4),
            "last_confirmed_at": NOW - timedelta(minutes=seen_min), "unconfirmed": False,
            "priced_at": NOW - timedelta(hours=priced_h), "parent_asin": parent, "brand": "Acme", "cat_path": None,
            "reviews": 4000, "rating": 4.5, "drops30": 30, "monthly_sold": 200, "amazon_sells": True, "rank": 3000,
            "keepa_first_seen_at": None, "first_seen_at": NOW - timedelta(hours=priced_h), "ref_flags": None,
            "resale_live": 1, **kw}


def live_rows():
    return [
        _live("B0C1234567", "Thrustmaster eSwap X Pro Controller for Xbox Series X|S", "61aBcDeFgHL.jpg", LIKE_NEW, 7134, 14599, 1),
        _live("B0GAME0002", "Logitech G Pro X Superlight 2 Wireless Gaming Mouse", "61GameMouse.jpg", VERY_GOOD, 7499, 15999, 30),
        _live("B0GAME0003", "SteelSeries Arctis Nova Pro Wireless Headset", "71NovaPro2.jpg", GOOD, 16999, 34999, 50),
        _live("B0HEAD0001", "Sony WH-1000XM5 Wireless Noise Canceling Headphones", "51SonyXM5a.jpg", LIKE_NEW, 15999, 39999, 3),
        _live("B0HEAD0002", "Bose QuietComfort Ultra Earbuds", "51BoseQCUe.jpg", VERY_GOOD, 13499, 29900, 80),
        # one product in two colours: a grouped card, priced "from"
        _live("B0ESPR0001", "Breville Barista Express Espresso Machine, Brushed Stainless", "81BrevBEs1.jpg", LIKE_NEW, 29999, 69995, 6,
              parent="B0ESPRPAR1"),
        _live("B0ESPR0002", "Breville Barista Express Espresso Machine, Black Truffle", "81BrevBEb2.jpg", VERY_GOOD, 27999, 69995, 6,
              parent="B0ESPRPAR1"),
        # an Acceptable unit beside a better one: the card quotes the better one, the Acceptable unit drops out
        _live("B0ROBO0001", "iRobot Roomba j7+ Self-Emptying Robot Vacuum", "61Roombaj7.jpg", VERY_GOOD, 26999, 59999, 10),
        _live("B0ROBO0001", "iRobot Roomba j7+ Self-Emptying Robot Vacuum", "61Roombaj7.jpg", ACCEPTABLE, 21999, 59999, 10),
        # Acceptable only: kept, flagged by its condition (the site hides it by default)
        _live("B0ROBO0002", "Shark AI Ultra Robot Vacuum with Self-Empty Base", "71SharkAIu.jpg", ACCEPTABLE, 18999, 49999, 20),
        # size-dependent (fit)
        _live("B0LUGG0001", "Samsonite Freeform Hardside Spinner, Large Checked", "71SamsoFF1.jpg", LIKE_NEW, 9999, 25999, 40),
        # rated junk: never public
        _live("B0JUNK0001", "Replacement Gasket Kit for Model 4410", "41JunkPart.jpg", LIKE_NEW, 2999, 9999, 2),
        # on a hidden shelf: never public
        _live("B0AUTO0001", "Brake Rotor Set for 2018-2022 Pickup", "61AutoPart.jpg", LIKE_NEW, 8999, 24999, 2),
        # an `aisle` shelf: in the feed and its aisle, not featured on the home page
        _live("B0FANS0001", "Noctua NF-A12x25 PWM Premium Fan, 3 Pack", "61NoctuaFn.jpg", LIKE_NEW, 4499, 9999, 12),
        # not yet rated: lands on "just in"
        _live("B0NEW00001", "Dyson Purifier Cool TP07 Air Purifier Fan", "61DysonTP7.jpg", LIKE_NEW, 26999, 56999, 0.5),
        # below 50%: not public
        _live("B0NEAR0001", "KitchenAid Artisan Stand Mixer", "81KAMixer1.jpg", LIKE_NEW, 26999, 44999, 4),
    ]


def gone_rows():
    def g(asin, title, image, cond, price, ref, gone_h, up_h, bracketed=True, parent=None):
        gone_at = NOW - timedelta(hours=gone_h)
        last_seen = gone_at - timedelta(hours=6)
        first_seen = last_seen - timedelta(hours=up_h)
        return {"asin": asin, "offer_id": 1, "title": title, "category": "Electronics", "image": image, "cond": cond,
                "resale_cents": price, "ref_cents": ref, "strict": round(1 - price / ref, 4), "last_seen_at": last_seen,
                "gone_at": gone_at, "brand": None, "cat_path": None, "reviews": 900, "rating": 4.4, "drops30": 10,
                "monthly_sold": 50, "amazon_sells": True, "rank": 9000, "first_seen_at": first_seen,
                "appeared_after_at": first_seen - timedelta(minutes=30) if bracketed else None,
                "keepa_first_seen_at": None, "absent_since_at": last_seen + timedelta(minutes=30), "revivals": 0,
                "priced_at": first_seen - timedelta(hours=1), "parent_asin": parent}
    return [g("B0GONE0001", "De'Longhi Dedica Espresso Machine", "71DeLongDd.jpg", LIKE_NEW, 11999, 29999, 3, 5),
            g("B0GONE0002", "Apple AirPods Max, Space Gray", "81AirPodsM.jpg", VERY_GOOD, 24999, 54900, 20, 2, bracketed=False),
            g("B0GONE0003", "Ninja Creami Ice Cream Maker", "71NinjaCrm.jpg", GOOD, 8999, 22999, 60, 30),
            g("B0GONE0004", "Thermos Stainless King Food Jar", "61Thermos1.jpg", LIKE_NEW, 1999, 4999, 4, 1),
            g("B0JUNK0002", "Replacement Filter Housing", "41JunkPar2.jpg", LIKE_NEW, 2999, 9999, 5, 3),         # junk
            g("B0HEAD0001", "Sony WH-1000XM5 Wireless Noise Canceling Headphones", "51SonyXM5a.jpg", GOOD, 14999, 39999, 2, 1)]  # live again


def appeal_rows():
    def a(key, score, aisle, shelf, fit=False, size=None):
        return {"key": key, "score": score, "tags": [], "why": "model note", "model": "sonnet", "prompt_v": "a0.3",
                "aisle": aisle, "kind": "k", "fit": fit, "shelf": shelf, "size": size}
    return [a("B0C1234567", 9, "gaming", "gaming-gear"), a("B0GAME0002", 8, "gaming", "gaming-gear"),
            a("B0GAME0003", 7, "gaming", "gaming-gear"), a("B0HEAD0001", 9, "audio-tv", "headphones-earbuds"),
            a("B0HEAD0002", 8, "audio-tv", "headphones-earbuds"), a("B0ESPRPAR1", 9, "kitchen", "espresso-coffee-makers"),
            a("B0ROBO0001", 8, "home-appliances", "robot-vacuums"), a("B0ROBO0002", 7, "home-appliances", "robot-vacuums"),
            a("B0LUGG0001", 7, "travel", "luggage", fit=True, size="Large"), a("B0JUNK0001", 2, "diy", "plumbing-parts-pumps"),
            a("B0AUTO0001", 6, "auto", "auto-parts"), a("B0FANS0001", 6, "tech", "pc-components"),
            a("B0GONE0001", 8, "kitchen", "espresso-coffee-makers"), a("B0GONE0002", 9, "audio-tv", "headphones-earbuds"),
            a("B0GONE0003", 7, "kitchen", "small-kitchen-appliances"), a("B0GONE0004", 5, "kitchen", "small-kitchen-appliances"),
            a("B0JUNK0002", 1, "diy", "plumbing-parts-pumps")]


def shelf_rows():
    def s(sid, name, aisle, role, description=None):
        return {"id": sid, "name": name, "aisle": aisle, "role": role, "proposed_role": role, "role_reason": "r",
                "version": "s0.1", "updated_by": None, "updated_at": None, "description": description}
    return [s("gaming-gear", "gaming gear", "gaming", "front", "Controllers, mice, headsets and the rest of the desk."),
            s("headphones-earbuds", "headphones & earbuds", "audio-tv", "front"),
            s("espresso-coffee-makers", "espresso & coffee makers", "kitchen", "front"),
            s("small-kitchen-appliances", "small kitchen appliances", "kitchen", "front"),
            s("robot-vacuums", "robot vacuums", "home-appliances", "front"),
            s("luggage", "luggage", "travel", "front"),
            s("pc-components", "pc components", "tech", "aisle"),
            s("plumbing-parts-pumps", "plumbing parts & pumps", "diy", "hidden"),
            s("auto-parts", "auto parts", "auto", "hidden")]


def arrivals():
    return [{"key": k} for k in ("B0C1234567", "B0GAME0002", "B0HEAD0001", "B0ESPRPAR1", "B0GONE0001", "B0GONE0002", "B0NEW00001")]


def make(tmp_path=None, clicks=None, site_open=False, **kw):
    clicks = clicks if clicks is not None else []
    kw.setdefault("log_click", clicks.append)
    kw.setdefault("fetch", live_rows)
    a = create_app(fetch_seen=lambda: [], fetch_gone=gone_rows, fetch_appeal=appeal_rows,
                   fetch_kind_map=lambda: [], fetch_shelves=shelf_rows, fetch_arrivals=arrivals, fetch_review=lambda: [],
                   fetch_watchers=lambda: [{"shelf_id": "gaming-gear", "watching": 4}], password="s3cret", admin_password="adm",
                   verifier=None, site_hosts=HOST, site_open=site_open, site_dir=tmp_path or Path("/nonexistent"),
                   snapshot_thread=False, **kw)
    a.state.snapshot.refresh(NOW)
    return a, TestClient(a, base_url=f"https://{HOST}", follow_redirects=False)


def auth(user="fiftyoff", pw="s3cret"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


ALL = "/api/v1/deals?cond=like-new,very-good,good,acceptable&limit=200"
ENDPOINTS = {"deals": "/api/v1/deals", "deals_filtered": "/api/v1/deals?aisle=gaming&sort=price-asc&since=2026-10-11T00:00:00Z&limit=2",
             "today": "/api/v1/today", "shelves": "/api/v1/shelves",
             "shelf": "/api/v1/shelves/gaming-gear", "gone": "/api/v1/gone?window=7d",
             "product": "/api/v1/product/B0ESPR0001", "product_gone": "/api/v1/product/B0GONE0001"}


def test_responses_match_the_canonical_fixtures():
    _, c = make()
    for name, path in ENDPOINTS.items():
        got = c.get(path, headers=auth()).json()
        f = FIXTURES / f"{name}.json"
        if os.environ.get("UPDATE_FIXTURES"):
            FIXTURES.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(got, indent=2) + "\n")
        assert got == json.loads(f.read_text()), name


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def test_no_forbidden_field_even_with_admin_auth():
    _, c = make()
    for path in ENDPOINTS.values():
        plain = c.get(path, headers=auth())
        admin = c.get(path, headers=auth("admin", "adm"))
        assert plain.content == admin.content, path  # every viewer gets the same bytes
        for d in _walk(plain.json()):
            assert not set(d) & api_v1.FORBIDDEN, (path, set(d) & api_v1.FORBIDDEN)
            if "slug" in d:
                assert set(d) in (set(api_v1.DEAL), set(api_v1.GONE)), (path, set(d))
            if "per_week" in d:
                assert set(d) - {"deals"} == set(api_v1.SHELF)


def test_selection_is_the_public_one():
    _, c = make()
    d = c.get(ALL, headers=auth()).json()
    ids = [x["id"] for x in d["deals"]]
    assert "B0JUNK0001" not in ids and "B0AUTO0001" not in ids and "B0NEAR0001" not in ids
    assert {"B0FANS0001", "B0NEW00001", "B0ROBO0002", "B0LUGG0001"} <= set(ids)
    assert d["total"] == d["count"] == len(ids) == len(set(ids)) == 11 and d["attribution"]["text"] == "Data by Keepa"
    by = {x["id"]: x for x in d["deals"]}
    espresso = next(x for x in d["deals"] if x["shelf"] == "espresso-coffee-makers")
    assert espresso["from"] and espresso["variants"] == 2 and espresso["price"] == 279.99
    assert espresso["usual_price"] == 699.95 and espresso["pct_off"] == 60
    assert espresso["id"] == "B0ESPR0002" and espresso["condition"] == "Very Good" and "Black Truffle" in espresso["title"]
    roomba = by["B0ROBO0001"]  # its Acceptable unit is cheaper, but a better unit exists: the card ignores it
    assert roomba["condition"] == "Very Good" and roomba["price"] == 269.99 and roomba["units"] == 1
    assert by["B0ROBO0002"]["condition"] == "Acceptable"
    assert by["B0LUGG0001"]["fit"] and not by["B0C1234567"]["fit"]
    assert by["B0NEW00001"]["shelf"] == "just-in" and by["B0NEW00001"]["is_new"]
    assert by["B0C1234567"]["url"] == "/d/b0c1234567-thrustmaster-eswap-x-pro-controller-for"
    assert by["B0C1234567"]["landed_at"] == "2026-10-11T14:00:00Z"
    t = c.get("/api/v1/today", headers=auth()).json()
    assert len(t["just_in"]) == 5 and t["just_in"][0]["id"] == "B0NEW00001" and t["last_landed_at"] == "2026-10-11T14:30:00Z"
    assert all(x["condition"] != "Acceptable" for x in t["just_in"] + [d for s in t["shelves"] for d in s["deals"]])
    assert "pc-components" not in [s["id"] for s in t["shelves"]] and "just-in" not in [s["id"] for s in t["shelves"]]
    assert [g["id"] for g in t["gone"]] == ["B0GONE0001", "B0GONE0004", "B0GONE0002", "B0GONE0003"]
    s = {x["id"]: x for x in c.get("/api/v1/shelves", headers=auth()).json()["shelves"]}
    assert "auto-parts" not in s and s["pc-components"]["live"] == 1 and s["gaming-gear"]["per_week"] == 2
    assert s["gaming-gear"]["aisle_name"] == "Gaming" and s["luggage"]["description"] is None
    assert c.get("/api/v1/shelves/auto-parts", headers=auth()).status_code == 404


def test_gone_windows_and_lifespan_bounds():
    _, c = make()
    w = {k: c.get(f"/api/v1/gone?window={k}", headers=auth()).json() for k in ("24h", "3d", "7d")}
    assert [g["id"] for g in w["24h"]["gone"]] == ["B0GONE0001", "B0GONE0004", "B0GONE0002"]
    assert w["3d"]["count"] == w["7d"]["count"] == 4  # junk and the live-again Sony never show
    first = w["24h"]["gone"][0]
    assert first["last_price"] == first["price"] == 119.99 and first["up_for_min"] == 300 and not first["up_for_is_lower_bound"]
    assert w["24h"]["gone"][2]["up_for_is_lower_bound"]  # already listed when we first saw it
    assert c.get("/api/v1/gone?window=1y", headers=auth()).status_code == 422
    p = c.get("/api/v1/product/B0GONE0001", headers=auth()).json()
    assert p["deal"] is None and p["gone"]["id"] == "B0GONE0001"
    assert [x["shelf"] for x in p["same_shelf"]] == ["espresso-coffee-makers"]
    assert c.get("/api/v1/product/B0NOTHING1", headers=auth()).json() == {
        "deal": None, "gone": None, "same_shelf": [], "attribution": api_v1.ATTRIBUTION}


def test_out_link_redirects_and_logs_a_click():
    clicks = []
    _, c = make(clicks=clicks)
    r = c.get("/d/b0c1234567-thrustmaster-eswap-x-pro?s=email",
              headers={**auth(), "Referer": f"https://{HOST}/shelf/gaming-gear/?x=secret"})
    assert r.status_code == 302 and r.headers["location"] == "https://www.amazon.com/dp/B0C1234567?aod=1"
    assert r.headers["cache-control"] == "no-store"
    assert clicks[-1] == {"asin": "B0C1234567", "slug": "b0c1234567-thrustmaster-eswap-x-pro", "surface": "email",
                          "live": True, "referer_path": "/shelf/gaming-gear/"}
    r = c.get("/d/b0espr0002", headers=auth())  # a variant under a grouped card is live too
    assert r.headers["location"] == "https://www.amazon.com/dp/B0ESPR0002?aod=1" and clicks[-1]["surface"] is None
    r = c.get("/d/b0gone0001-delonghi?s=bogus", headers=auth())
    assert r.headers["location"] == "/sold/?id=B0GONE0001" and clicks[-1]["live"] is False and clicks[-1]["surface"] is None
    r = c.get("/d/b0unknown1-x", headers=auth())
    assert r.headers["location"] == "/sold/?id=B0UNKNOWN1"
    r = c.get("/d/not-a-slug", headers=auth())
    assert r.headers["location"] == "/sold/" and clicks[-1]["asin"] is None
    assert len(clicks) == 5


def test_a_failing_click_insert_still_redirects():
    def boom(row):
        raise RuntimeError("db down")
    _, c = make(log_click=boom)
    r = c.get("/d/b0c1234567", headers=auth())
    assert r.status_code == 302 and r.headers["location"].startswith("https://www.amazon.com/dp/B0C1234567")


def test_endpoints_read_the_snapshot_and_never_run_the_selection():
    calls = []

    def counted():
        calls.append(1)
        return live_rows()
    a, c = make(fetch=counted)
    n = len(calls)
    for path in list(ENDPOINTS.values()) + ["/d/b0c1234567"]:
        assert c.get(path, headers=auth()).status_code in (200, 302)
    assert len(calls) == n
    a.state.snapshot.data = None  # before the first build: a short 503, never a build inside the request
    r = c.get("/api/v1/deals", headers=auth())
    assert r.status_code == 503 and r.headers["cache-control"] == "no-store" and len(calls) == n
    assert c.get("/d/b0c1234567", headers=auth()).headers["location"].startswith("https://www.amazon.com/")


def test_public_deals_matches_the_shelves_page(monkeypatch):
    """v1 keeps Acceptable-only cards; everything else is exactly what /api/shelves shows on its home view plus
    the aisle shelves (junk and hidden shelves dropped the same way). Both sides on the real clock."""
    monkeypatch.setitem(globals(), "NOW", datetime.now(timezone.utc))
    a, c = make()
    a.state.snapshot.refresh()
    page = c.get("/api/shelves?per=50", headers={**auth(), "host": "preview.fiftyoff.app"}).json()
    aisle = {p["asin"] for x in ("tech",) for s in c.get(f"/api/shelves?aisle={x}&per=50",
             headers={**auth(), "host": "preview.fiftyoff.app"}).json()["shelves"] for p in s["products"]}
    snap = a.state.snapshot.data
    shown = {snap["by_asin"][x]["id"] for x in {p["asin"] for s in page["shelves"] for p in s["products"]} | aisle}
    v1 = {d["id"] for d in snap["deals"] if d["condition"] != "Acceptable"}
    assert v1 == shown and len(v1) == 10


def test_host_routing_gate_and_cache_headers(tmp_path):
    (tmp_path / "shelf" / "_").mkdir(parents=True)
    (tmp_path / "shelf" / "_" / "index.html").write_text("<p>shelf page</p>")
    (tmp_path / "sold").mkdir()
    (tmp_path / "sold" / "index.html").write_text("<p>sold page</p>")
    (tmp_path / "index.html").write_text("<p>Today</p>")
    (tmp_path / "_next" / "static").mkdir(parents=True)
    (tmp_path / "_next" / "static" / "app.js").write_text("1")
    _, c = make(tmp_path)
    assert c.get("/").status_code == 401                         # closed: the preview password still applies
    r = c.get("/", headers=auth())
    assert r.text == "<p>Today</p>" and r.headers["cache-control"] == "private, max-age=0"
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert c.get("/shelf/gaming-gear/", headers=auth()).text == "<p>shelf page</p>"
    assert c.get("/sold/", headers=auth()).text == "<p>sold page</p>"
    assert c.get("/api/v1/deals", headers=auth()).headers["cache-control"] == "private, max-age=30"
    assert c.get("/api/feed", headers=auth()).status_code == 404     # the preview's API isn't on the site host
    assert c.get("/admin/", headers=auth("admin", "adm")).status_code == 404
    preview = TestClient(c.app, base_url="https://preview.fiftyoff.app")
    assert "Data by Keepa" in preview.get("/", headers=auth()).text     # the preview page, unchanged
    assert preview.get("/api/v1/deals", headers=auth()).status_code == 404

    _, c = make(tmp_path, site_open=True)                         # step 7: one flag opens the host and the edge cache
    r = c.get("/api/v1/deals")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=30, s-maxage=60, stale-while-revalidate=300"
    assert c.get("/").headers["cache-control"] == "public, max-age=0, s-maxage=60"
    assert c.get("/_next/static/app.js").headers["cache-control"] == "public, max-age=31536000, immutable"
    assert c.get("/d/b0c1234567").headers["cache-control"] == "no-store"
    assert c.get("/admin/").status_code == 401                    # admin still needs its own login on every host
    assert TestClient(c.app, base_url="https://preview.fiftyoff.app").get("/").status_code == 401


def test_all_deals_filters_sorts_and_pages():
    """The design's All deals sidebar: condition (default without Acceptable), price band, aisle, hide size-dependent;
    sorts newest / discount / price; `since` puts what landed after the last look first."""
    _, c = make()
    get = lambda q="": c.get(f"/api/v1/deals{q}", headers=auth()).json()  # noqa: E731
    d = get()
    assert d["count"] == 10 and d["total"] == 11 and d["new_count"] is None  # B0ROBO0002 (Acceptable) hidden by default
    assert [x["landed_at"] for x in d["deals"]] == sorted((x["landed_at"] for x in d["deals"]), reverse=True)
    assert {a["id"]: a["count"] for a in d["aisles"]}["gaming"] == 3
    assert [x["id"] for x in get("?cond=acceptable")["deals"]] == ["B0ROBO0002"]
    assert get("?cond=mint")["error"] and c.get("/api/v1/deals?cond=mint", headers=auth()).status_code == 422
    assert {x["id"] for x in get("?price=under-100")["deals"]} == {"B0C1234567", "B0GAME0002", "B0FANS0001", "B0LUGG0001"}
    assert all(x["price"] >= 300 for x in get("?price=300-plus")["deals"])
    assert "B0LUGG0001" not in [x["id"] for x in get("?nofit=true")["deals"]]
    g = get("?aisle=gaming&sort=discount")
    assert [x["pct_off"] for x in g["deals"]] == [53, 51, 51] and g["count"] == 3
    assert {a["id"] for a in g["aisles"]} > {"gaming"}  # the chips still count the other aisles
    p = [x["price"] for x in get("?sort=price-asc")["deals"]]
    assert p == sorted(p) and [x["price"] for x in get("?sort=price-desc")["deals"]] == sorted(p, reverse=True)
    n = get("?sort=price-asc&since=2026-10-11T08:00:00")  # naive = UTC; 4 cards landed after 08:00
    assert n["new_count"] == 4 and all(x["landed_at"] > "2026-10-11T08:00:00Z" for x in n["deals"][:4])
    assert [x["price"] for x in n["deals"][:4]] == sorted(x["price"] for x in n["deals"][:4])
    pages = [get(f"?limit=4&offset={o}") for o in (0, 4, 8)]
    assert [len(x["deals"]) for x in pages] == [4, 4, 2] and len({x["id"] for pg in pages for x in pg["deals"]}) == 10
    assert c.head("/api/v1/deals", headers=auth()).status_code == 200 and c.head("/d/b0c1234567", headers=auth()).status_code == 302


@pytest.mark.parametrize("title,expected", [("Sony WH-1000XM5 Wireless, Black!", "b0x-sony-wh-1000xm5-wireless-black"),
                                            ("", "b0x"), (None, "b0x")])
def test_slug(title, expected):
    assert api_v1.slug("B0X", title) == expected
