"""Read-only deal API + closed preview page.

Public fields: the Keepa-consented ones (D19: title, Amazon link, our % off, condition, current Resale
price), our own derived fields (deal score, "last confirmed", unit counts), the last price of gone deals
(D27: beyond D19, the user accepts the risk) and the product image (preview only; not in D19, see
DAILY_LOG). Reference price, reviews, rank and other signals feed the score but are never emitted.
Every response carries the "Data by Keepa" attribution. Connects as a role that can read the feed
views and the admin views, and write curation decisions and their log (D36), and nothing else.

Admin (D36): /admin/ and /admin/api/* sit behind their own gate (`is_admin`; Phase 1 = Basic Auth with
ADMIN_PASSWORD, Phase 2 = Cloudflare Access). They show reference, list and Amazon prices; D36 allows
those prices publicly for now, but the admin side itself is never public.

    uvicorn fiftyoff.api:app      # FEED_DATABASE_URL points at the read-only role
"""

from __future__ import annotations

import base64
import tomllib
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import curation
from .confidence import CONFIDENCE_VERSION, RANK, live_confidence
from .score import SCORE_VERSION, breakdown, image_url, score
from .tracker import Unit, lifespan

ATTRIBUTION = {"text": "Data by Keepa", "url": "https://keepa.com"}
PREVIEW = Path(__file__).parent / "preview.html"
GONE_PAGE = Path(__file__).parent / "gone.html"
STATUS_PAGE = Path(__file__).parent / "status.html"
ADMIN_PAGE = Path(__file__).parent / "admin.html"
CONFIG = Path(__file__).parent.parent / "preflight.toml"
NEW_HOURS = 24             # a deal is "new" when Keepa saw its current price set within this window
HEADLINE = 0.50            # D22: the default view is strict 50%+; below it is a labelled "near miss"
ACCEPTABLE = "Used - Acceptable"
SORTS = {
    "best": lambda p: -p["score"],
    "discount": lambda p: -p["pct_off"],
    "newest": lambda p: (p["minutes_since_priced"] is None, p["minutes_since_priced"] or 0),
    "confirmed": lambda p: p["minutes_since_confirmed"],
    "price": lambda p: p["price"],
}


def _query(view: str) -> list[dict]:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(os.environ["FEED_DATABASE_URL"], row_factory=dict_row) as conn:
        return conn.execute(f"SELECT * FROM {view}").fetchall()


def pg_live() -> list[dict]:
    return _query("deal_internal")


def pg_census() -> list[dict]:
    return [{**r, "source": "census"} for r in _query("census_deal")]


def pg_gone() -> list[dict]:
    return _query("gone_internal")


def pg_status() -> dict:
    return {"funnel": _query("status_funnel")[0], "hourly": _query("status_hourly"),
            "state": {r["key"]: r["value"] for r in _query("status_state")}, "census": _query("census_summary")}


def pg_review() -> list[dict]:
    return _query("review_queue")


def pg_curated() -> list[dict]:
    return _query("curation_admin")


def pg_curate(asin: str, change: dict, allowed_tags, by: str) -> dict:
    """One admin change, in one transaction: the curation row and a log row per changed field (D36).
    Approving stamps the current reference as the baseline (review queue first, else the live or census deal)."""
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(os.environ["FEED_DATABASE_URL"], row_factory=dict_row) as conn:
        cur = conn.execute("SELECT visibility, tags, note, decided_ref_cents FROM curation WHERE asin = %s "
                           "FOR UPDATE", (asin,)).fetchone()
        ref = None
        if change.get("visibility") == "approved":
            for sql in ("SELECT ref_cents FROM review WHERE asin = %s",
                        "SELECT max(ref_cents) AS ref_cents FROM deal_internal WHERE asin = %s",
                        "SELECT max(ref_cents) AS ref_cents FROM census_deal WHERE asin = %s"):
                row = conn.execute(sql, (asin,)).fetchone()
                if row and row["ref_cents"]:
                    ref = row["ref_cents"]
                    break
        new, log = curation.apply(cur, change, allowed_tags, ref)
        if log:
            conn.execute(
                "INSERT INTO curation (asin, visibility, tags, note, decided_ref_cents, updated_at, updated_by) "
                "VALUES (%s, %s, %s, %s, %s, now(), %s) ON CONFLICT (asin) DO UPDATE SET visibility = EXCLUDED.visibility, "
                "tags = EXCLUDED.tags, note = EXCLUDED.note, decided_ref_cents = EXCLUDED.decided_ref_cents, "
                "updated_at = EXCLUDED.updated_at, updated_by = EXCLUDED.updated_by",
                (asin, new["visibility"], new["tags"], new["note"], new["decided_ref_cents"], by))
            with conn.cursor() as c:
                c.executemany("INSERT INTO curation_log (asin, field, old, new, by, at) VALUES (%s, %s, %s, %s, %s, now())",
                              [(asin, f, o, n, by) for f, o, n in log])
        return {**new, "changed": [f for f, _, _ in log]}


def admin_tags(path: Path = CONFIG) -> tuple[str, ...]:
    """Allowed curation tags (preflight.toml [admin] tags). The module builds its app at import, so a
    missing file or section falls back to the defaults rather than failing."""
    try:
        return tuple(tomllib.loads(path.read_text()).get("admin", {}).get("tags") or curation.DEFAULT_TAGS)
    except (OSError, tomllib.TOMLDecodeError):
        return curation.DEFAULT_TAGS


CACHE_SECONDS = 30  # however much traffic arrives, the database sees at most one query per view per 30 s


def _minutes(now: datetime, t: datetime) -> int:
    return int((now - t).total_seconds() // 60)


VERIFIED_CATEGORIES = {"Electronics", "Home & Kitchen", "Appliances", "Tools & Home Improvement", "Sports & Outdoors"}
CONF_MIN = {"all": 0, "likely": 1, "high": 2}  # D30: the feed holds back LOW-confidence units by default


def matches(title: str | None, q: str | None) -> bool:
    """Every query word must start a word in the title: "rug" finds "Rug" and "Rugs", not "drug"."""
    if not q:
        return True
    return all(re.search(rf"(?<![a-z0-9]){re.escape(w)}", (title or "").lower()) for w in q.lower().split())


def _priced_min(now: datetime, r: dict) -> int | None:
    return _minutes(now, r["priced_at"]) if r.get("priced_at") else None


def _keep(r: dict, tier: str, acceptable: bool, category: str | None, q: str | None) -> bool:
    return ((tier == "all" or (r["strict"] or 0) >= HEADLINE)
            and (acceptable or r["cond"] != ACCEPTABLE)
            and (category is None or r["category"] == category)
            and matches(r["title"], q))


def group_products(rows: list[dict], now: datetime) -> list[dict]:
    """One entry per ASIN (D22, rule 9: ASIN, not parent), its units best-first."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["asin"], []).append(r)
    out = []
    for asin, us in by.items():
        us.sort(key=score, reverse=True)
        best = us[0]
        units = [{"condition": u["cond"], "price": u["resale_cents"] / 100, "pct_off": round(u["strict"] * 100),
                  "score": score(u), "minutes_since_confirmed": _minutes(now, u["last_confirmed_at"]),
                  "unconfirmed": u["unconfirmed"], "confidence": live_confidence(u, now)} for u in us]
        out.append({
            "asin": asin, "title": best["title"], "category": best["category"], "image": image_url(best["image"]),
            "url": f"https://www.amazon.com/dp/{asin}?aod=1",
            "score": units[0]["score"], "score_parts": breakdown(best), "pct_off": max(u["pct_off"] for u in units),
            "price": min(u["price"] for u in units), "near_miss": best["strict"] < HEADLINE,
            "unit_count": len(units), "minutes_since_confirmed": min(u["minutes_since_confirmed"] for u in units),
            "minutes_since_priced": _priced_min(now, best),
            "is_new": (_priced_min(now, best) is not None and _priced_min(now, best) < NEW_HOURS * 60),
            "confidence": max((u["confidence"] for u in units), key=lambda c: c["p"]),
            # D33: census deals were seen in Keepa's deal feed but never live-checked by us
            "verified": best.get("source") != "census",
            "units": units,
        })
    return out


def _ts(d: datetime | None) -> float | None:
    return d.timestamp() if d else None


def gone_lifespan(r: dict) -> dict | None:
    """How long a gone unit was listed: bounds in minutes + the rule-9 confidence label (tracker.lifespan)."""
    if r.get("first_seen_at") is None:
        return None
    u = Unit(asin=r["asin"], offer_id=r["offer_id"], first_seen=_ts(r["first_seen_at"]),
             appeared_after=_ts(r.get("appeared_after_at")), last_seen=_ts(r["last_seen_at"]),
             first_price=r["resale_cents"], last_price=r["resale_cents"], cond=r["cond"], comment=None,
             strict_first=r["strict"], strict_last=r["strict"], ref_last=r.get("ref_cents"),
             keepa_first_seen=_ts(r.get("keepa_first_seen_at")), state="gone",
             absent_since=_ts(r.get("absent_since_at")), gone_at=_ts(r.get("gone_at")))
    ls = lifespan(u)
    if not ls:
        return None
    return {"lower_min": round(ls["lower_min"]), "upper_min": None if ls["upper_min"] is None else round(ls["upper_min"]),
            "confidence": ls["confidence"], "algo": ls["algo"]}


def create_app(fetch: Callable[[], list[dict]] = pg_live, fetch_gone: Callable[[], list[dict]] = pg_gone,
               fetch_status: Callable[[], dict] = pg_status, fetch_census: Callable[[], list[dict]] = pg_census,
               fetch_review: Callable[[], list[dict]] = pg_review,
               fetch_curated: Callable[[], list[dict]] = pg_curated,
               curate: Callable[[str, dict, tuple, str], dict] = pg_curate,
               password: str | None = None, user: str = "fiftyoff",
               admin_password: str | None = None, tags: tuple[str, ...] | None = None) -> FastAPI:
    """`password` (default: PREVIEW_PASSWORD env) turns on a browser login popup (HTTP Basic Auth) for
    everything except /api/health. `admin_password` (default: ADMIN_PASSWORD env) opens /admin/ and
    /admin/api/* to user "admin"; without it they stay closed. Only safe behind HTTPS (the Cloudflare tunnel)."""
    app = FastAPI(title="fiftyoff", docs_url=None, redoc_url=None)
    password = password if password is not None else os.environ.get("PREVIEW_PASSWORD") or None
    admin_password = admin_password if admin_password is not None else os.environ.get("ADMIN_PASSWORD") or None
    allowed_tags = tags if tags is not None else admin_tags()
    expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode() if password else None
    expected_admin = "Basic " + base64.b64encode(f"admin:{admin_password}".encode()).decode() if admin_password else None
    cache: dict[str, tuple[float, list[dict]]] = {}

    def is_admin(request: Request) -> str | None:
        """The admin identity, or None. Phase 1: Basic Auth; Phase 2 swaps in a verified Cloudflare Access
        identity with the admin role. Routes only depend on this hook."""
        if expected_admin and secrets.compare_digest(request.headers.get("authorization", ""), expected_admin):
            return "admin"
        return None

    def login(realm: str) -> Response:
        return Response("Login required", status_code=401, headers={"WWW-Authenticate": f'Basic realm="{realm}"'})

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if path == "/admin" or path.startswith("/admin/"):
            if not is_admin(request):
                return login("fiftyoff admin")
        elif expected and path != "/api/health" and not is_admin(request) \
                and not secrets.compare_digest(request.headers.get("authorization", ""), expected):
            return login("fiftyoff preview")
        resp = await call_next(request)
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp

    def cached(key: str, fn: Callable[[], list[dict]]) -> list[dict]:
        hit = cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        rows = fn()
        cache[key] = (time.monotonic(), rows)
        return rows

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/feed")
    def feed(category: str | None = None,
             sort: str = Query("best", pattern="^(best|discount|newest|confirmed|price)$"), fresh: bool = False,
             explore: bool = False,
             tier: str = Query("50", pattern="^(50|all)$"), acceptable: bool = False,
             q: str | None = Query(None, max_length=80), conf: str = Query("likely", pattern="^(all|likely|high)$"),
             limit: int = Query(100, ge=1, le=500)):
        now = datetime.now(timezone.utc)
        pool = cached("live", fetch) + (cached("census", fetch_census) if explore else [])
        cats: dict[str, int] = {}
        for r in pool:  # category counts under every filter except the category itself (for the dropdown)
            if _keep(r, tier, acceptable, None, q):
                cats[r["category"]] = cats.get(r["category"], 0) + 1
        rows = [r for r in pool if _keep(r, tier, acceptable, category, q)
                and (not fresh or (_priced_min(now, r) is not None and _priced_min(now, r) < NEW_HOURS * 60))]
        held = sum(RANK[live_confidence(r, now)["label"]] < CONF_MIN[conf] for r in rows)
        rows = [r for r in rows if RANK[live_confidence(r, now)["label"]] >= CONF_MIN[conf]]
        products = sorted(group_products(rows, now), key=SORTS[sort])
        return {"products": products[:limit], "count": len(products), "units": len(rows), "held_back": held,
                "categories": [{"name": k, "units": v, "verified": k in VERIFIED_CATEGORIES}
                               for k, v in sorted(cats.items(), key=lambda kv: -kv[1])],
                "score_version": SCORE_VERSION, "confidence_version": CONFIDENCE_VERSION, "attribution": ATTRIBUTION, "generated_at": now.isoformat()}

    @app.get("/api/gone")
    def gone(category: str | None = None, tier: str = Query("50", pattern="^(50|all)$"),
             q: str | None = Query(None, max_length=80),
             hours: int = Query(72, ge=1, le=168),
             limit: int = Query(30, ge=1, le=500)):
        """Just missed (D27): qualifying units gone recently, best first. "Gone" = absent from our checks
        for 6 h (D20); we can't tell a sale from a withdrawal, so the copy says "gone", never "sold"."""
        now = datetime.now(timezone.utc)
        rows = [r for r in cached("gone", fetch_gone)
                if _keep(r, tier, True, category, q) and _minutes(now, r["last_seen_at"]) <= hours * 60]
        rows.sort(key=score, reverse=True)
        items = [{"asin": r["asin"], "title": r["title"], "category": r["category"], "image": image_url(r["image"]),
                  "url": f"https://www.amazon.com/dp/{r['asin']}?aod=1", "condition": r["cond"],
                  "price": r["resale_cents"] / 100, "pct_off": round(r["strict"] * 100), "score": score(r),
                  "score_parts": breakdown(r), "lifespan": gone_lifespan(r), "near_miss": r["strict"] < HEADLINE, "minutes_since_seen": _minutes(now, r["last_seen_at"])}
                 for r in rows[:limit]]
        return {"gone": items, "count": len(rows), "score_version": SCORE_VERSION,
                "attribution": ATTRIBUTION, "generated_at": now.isoformat()}

    @app.get("/api/status")
    def status():
        """Admin status: the tracking funnel (same filters as the feed), arrivals and checks per hour,
        and the tracker's own heartbeat, spend and fast-lane size."""
        now = datetime.now(timezone.utc)
        st = cached("status", lambda: [fetch_status()])[0]
        live = cached("live", fetch)
        q50 = [r for r in live if (r["strict"] or 0) >= HEADLINE]
        q50na = [r for r in q50 if r["cond"] != ACCEPTABLE]
        shown = [r for r in q50na if RANK[live_confidence(r, now)["label"]] >= CONF_MIN["likely"]]
        new = [r for r in q50 if _priced_min(now, r) is not None and _priced_min(now, r) < NEW_HOURS * 60]
        f = st["funnel"]
        hb = st["state"].get("heartbeat")
        return {
            "funnel": {**{k: v for k, v in f.items() if k != "tracking_since"},
                       "tracking_since": f["tracking_since"].isoformat() if f.get("tracking_since") else None,
                       "qualifying_units": len(live), "qualifying_products": len({r["asin"] for r in live}),
                       "products_50": len({r["asin"] for r in q50}), "products_50_no_acceptable": len({r["asin"] for r in q50na}),
                       "products_shown_default": len({r["asin"] for r in shown}),
                       "units_held_back_default": len(q50na) - len(shown),
                       "new_50_products_24h": len({r["asin"] for r in new}),
                       "held_for_review": sum(not r["listed"] for r in cached("review", fetch_review))},
            "hourly": [{**h, "hour": h["hour"].isoformat()} for h in st["hourly"]],
            "tracker": {**(st["state"].get("status") or {}),
                        "heartbeat_minutes_ago": round((now.timestamp() - hb) / 60, 1) if hb else None,
                        "last_sweep_minutes_ago": round((now.timestamp() - st["state"]["last_sweep"]) / 60, 1)
                        if st["state"].get("last_sweep") else None},
            "census": sorted(({**c, "swept_at": c["swept_at"].isoformat(),
                               **{k: float(c[k]) if c.get(k) is not None else None
                                  for k in ("median_strict", "share_popular", "median_ref_usd")}}
                              for c in st.get("census") or []), key=lambda c: -(c["products_50_100"] or 0)),
            "versions": {"score": SCORE_VERSION, "confidence": CONFIDENCE_VERSION},
            "attribution": ATTRIBUTION, "generated_at": now.isoformat(),
        }

    def _review_item(r: dict, now: datetime) -> dict:
        return {"asin": r["asin"], "status": r["status"], "layer": r["layer"], "reasons": r["reasons"],
                "rules": r["rules"], "title": r["title"], "image": image_url(r["image"]), "condition": r["cond"],
                "url": f"https://www.amazon.com/dp/{r['asin']}?aod=1",
                "keepa": f"https://keepa.com/#!product/1-{r['asin']}",
                "price": (r["resale_cents"] or 0) / 100, "ref": (r["ref_cents"] or 0) / 100,
                "pct_off": round((r["strict"] or 0) * 100), "flags": r["ref_flags"], "ref_parts": r["ref_parts"],
                "minutes_since_seen": _minutes(now, r["updated_at"]),
                "first_held_at": r["first_held_at"].isoformat(),
                "minutes_since_held": _minutes(now, r["first_held_at"]), "listed": r["listed"], "why": r["unlisted_why"],
                "visibility": r["visibility"], "tags": r["tags"], "note": r["note"],
                "decided_ref": r["decided_ref_cents"] / 100 if r["decided_ref_cents"] else None,
                "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None}

    @app.get("/admin/api/review")
    def admin_review(status: str = Query("held", pattern="^(held|listed|all)$"), days: int = Query(3, ge=1, le=60),
                     sort: str = Query("newest", pattern="^(newest|reasons)$")):
        """D35 review queue + D36 decisions. held = out of the feed now (pending, or an approval that lapsed);
        listed = in the feed (cleared, or approved within 20%). Seen in the last `days`. newest = most recently
        held first (a deal that clears and is held again counts as new), so new holds are always on top."""
        now = datetime.now(timezone.utc)
        allr = fetch_review()
        rows = [r for r in allr if (status == "all" or r["listed"] == (status == "listed"))
                and _minutes(now, r["updated_at"]) <= days * 1440]
        if sort == "newest":
            rows.sort(key=lambda r: r["first_held_at"], reverse=True)
        else:
            rows.sort(key=lambda r: (-len(r["reasons"]), -(r["strict"] or 0)))
        counts = {"held": sum(not r["listed"] for r in allr), "listed": sum(r["listed"] for r in allr),
                  "approved": sum(r["visibility"] == "approved" for r in allr),
                  "lapsed": sum(r["unlisted_why"] == "approval_lapsed" for r in allr)}
        return {"items": [_review_item(r, now) for r in rows], "count": len(rows), "counts": counts,
                "tags": list(allowed_tags), "generated_at": now.isoformat()}

    @app.get("/admin/api/curation")
    def admin_curation():
        """Every ASIN with a human decision, most recent first."""
        now = datetime.now(timezone.utc)
        rows = sorted(fetch_curated(), key=lambda r: r["updated_at"], reverse=True)
        items = [{"asin": r["asin"], "visibility": r["visibility"], "tags": r["tags"], "note": r["note"],
                  "title": r["title"], "image": image_url(r["image"]), "url": f"https://www.amazon.com/dp/{r['asin']}?aod=1",
                  "review_status": r["review_status"], "reasons": r["reasons"] or [],
                  "ref": r["ref_cents"] / 100 if r["ref_cents"] else None,
                  "decided_ref": r["decided_ref_cents"] / 100 if r["decided_ref_cents"] else None,
                  "price": r["resale_cents"] / 100 if r["resale_cents"] else None,
                  "pct_off": round(r["strict"] * 100) if r["strict"] is not None else None,
                  "listed": r["listed"], "why": r["unlisted_why"],
                  "updated_at": r["updated_at"].isoformat(), "updated_by": r["updated_by"],
                  "minutes_since_update": _minutes(now, r["updated_at"])} for r in rows]
        return {"items": items, "count": len(items), "tags": list(allowed_tags), "generated_at": now.isoformat()}

    @app.post("/admin/api/curation/{asin}")
    def admin_curate(asin: str, body: dict, request: Request):
        """{visibility?, tags_add?, tags_remove?, note?}. Validation lives in curation.apply."""
        if not re.fullmatch(r"[A-Z0-9]{10}", asin):
            return Response("bad asin", status_code=400)
        try:
            out = curate(asin, body, allowed_tags, is_admin(request))
        except ValueError as e:
            return Response(str(e), status_code=400)
        cache.clear()  # the feed must reflect the decision right away
        return {"asin": asin, **out}

    # The page sits at /admin/ and its API under /admin/api/: one path prefix, so a browser treats the
    # admin Basic Auth login as one protection space and never sends the preview login there.
    @app.get("/admin/", response_class=HTMLResponse)
    def admin_page():
        return ADMIN_PAGE.read_text()

    @app.get("/admin")
    @app.get("/closed-preview/review")
    def admin_moved():
        return RedirectResponse("/admin/", status_code=307)

    @app.get("/closed-preview/status", response_class=HTMLResponse)
    def status_page():
        return STATUS_PAGE.read_text()

    @app.get("/closed-preview/gone", response_class=HTMLResponse)
    def gone_page():
        return GONE_PAGE.read_text()

    @app.get("/", response_class=HTMLResponse)
    @app.get("/closed-preview", response_class=HTMLResponse)
    def preview():
        return PREVIEW.read_text()

    return app


app = create_app()
