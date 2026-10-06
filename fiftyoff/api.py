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
from starlette.concurrency import run_in_threadpool

from . import access, curation
from .analysis import review_reasons
from .confidence import CONFIDENCE_VERSION, RANK, live_confidence
from .score import SCORE_VERSION, breakdown, image_url, score
from .tracker import CENSUS_CATS, Unit, lifespan

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


def pg_seen() -> list[dict]:
    """D39: the seen-in-feed layer: tracked roots' sweeps (no rank limit) and the census (current categories)."""
    return [{**r, "source": "feed"} for r in _query("sweep_deal")] + \
           [{**r, "source": "census"} for r in _query("census_deal") if r["cat_id"] in CENSUS_CATS]


def pg_nodes() -> list[dict]:
    return _query("cat_node")


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


def pg_users() -> list[dict]:
    return _query("app_user")


def pg_touch_user(email: str, owner: bool) -> None:
    """D37: record a verified sign-in. New people start as viewers; owners (ADMIN_EMAILS) as admins."""
    import psycopg
    with psycopg.connect(os.environ["FEED_DATABASE_URL"]) as conn:
        conn.execute("INSERT INTO app_user (email, role, first_seen, last_seen) VALUES (%s, %s, now(), now()) "
                     "ON CONFLICT (email) DO UPDATE SET last_seen = now()", (email, "admin" if owner else "viewer"))


def pg_set_user(email: str, change: dict, owner: bool, by: str) -> dict:
    """One People-tab change, in one transaction, with a log row per changed field (D37)."""
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(os.environ["FEED_DATABASE_URL"], row_factory=dict_row) as conn:
        cur = conn.execute("SELECT role, active, note FROM app_user WHERE email = %s FOR UPDATE", (email,)).fetchone()
        new, log = access.user_change(cur, change, owner)
        if log:
            conn.execute("INSERT INTO app_user (email, role, active, note, updated_at, updated_by) "
                         "VALUES (%s, %s, %s, %s, now(), %s) ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role, "
                         "active = EXCLUDED.active, note = EXCLUDED.note, updated_at = EXCLUDED.updated_at, "
                         "updated_by = EXCLUDED.updated_by", (email, new["role"], new["active"], new["note"], by))
            with conn.cursor() as c:
                c.executemany("INSERT INTO app_user_log (email, field, old, new, by, at) VALUES (%s, %s, %s, %s, %s, now())",
                              [(email, f, o, n, by) for f, o, n in log])
        return {**new, "changed": [f for f, _, _ in log]}


def default_verifier() -> access.AccessVerifier | None:
    team, aud = os.environ.get("CF_ACCESS_TEAM"), os.environ.get("CF_ACCESS_AUD")
    return access.AccessVerifier(team, aud) if team and aud else None


TOUCH_SECONDS = 600  # a signed-in person's last_seen is written at most every 10 min


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
SEEN_HOURS = {"all": 36, "seen": 7 * 24}  # D39: a seen-only card stays 36 h after its last sighting (7 days in "Seen only")
INVERTED_OVER_LIST = 1.1  # same margin as the D35 above_list hold: a reference a few % over list isn't an inversion
FLAGGED_RANK = 0.75  # D39: "best" sort weight for seen-only cards with a reference warning
PER_SUBCATEGORY = 2  # D39: "best" sort shows at most this many per subcategory before the rest (ten ice makers -> two)
# Amazon's structural nodes, skipped when naming a subcategory (cat_node parent chains run through them)
STRUCTURAL = {"Categories", "Departments", "Featured Categories", "Custom Stores", "Specialty Stores", "Shops", "Stores"}


def subcategory(r: dict, nodes: dict) -> str | None:
    """The card's subcategory: up to two levels under the root ("Kitchen & Bath Fixtures › Kitchen Fixtures").
    Live rows carry the product's category path; feed rows a leaf id named through cat_node."""
    path = [n for n in (r.get("cat_path") or []) if n and n not in STRUCTURAL]
    if not path and r.get("cats"):
        cur, seen = r["cats"][0], set()
        while cur in nodes and cur not in seen:
            seen.add(cur)
            name, cur = nodes[cur]
            if name and name not in STRUCTURAL:
                path.append(name)
        path.reverse()
    return " › ".join(path[1:3]) or None


def inversion(r: dict) -> dict | None:
    """An "inverted" deal (user, 2026-10-06): only third-party sellers set the New reference, and it sits above
    Amazon's list price (e.g. one seller's price for an odd shoe size at ~2x list, so "60% off" is ~25% vs list).
    Returns the list price and the % off measured against it."""
    f = r.get("ref_flags") or {}
    lst = f.get("list")
    if lst and lst > 0 and (r.get("ref_cents") or 0) > INVERTED_OVER_LIST * lst \
            and "third_party_only" in (f.get("flags") or []):
        return {"list": lst / 100, "pct_off_vs_list": round((1 - r["resale_cents"] / lst) * 100)}
    return None


def cap_at_list(r: dict) -> dict:
    """The A/B test's other arm: an inverted deal measured against the list price."""
    inv = r.get("_inv")
    if not inv:
        return r
    lst = round(inv["list"] * 100)
    return {**r, "ref_cents": lst, "strict": 1 - r["resale_cents"] / lst}


def diversify(products: list[dict], cap: int = PER_SUBCATEGORY) -> list[dict]:
    """Keep the order, but let at most `cap` cards per subcategory through before the rest follow."""
    first, rest, n = [], [], {}
    for p in products:
        k = p.get("subcategory")
        n[k] = n.get(k, 0) + 1
        (first if k is None or n[k] <= cap else rest).append(p)
    return first + rest


def _stems(w: str) -> list[str]:
    """A query word and its singular: "shoes" -> shoe, "rugs" -> rug, "glasses" -> glass. Dropping "es" needs a
    4+ letter stem, so "shoes" never becomes "sho" (Shower)."""
    out = [w]
    for cut, keep in (("es", 4), ("s", 3)):
        if w.endswith(cut) and len(w) - len(cut) >= keep:
            out.append(w[: -len(cut)])
    return out


def matches(title: str | None, q: str | None) -> bool:
    """Every query word must start a word in the title: "rug" finds "Rug" and "Rugs", not "drug";
    a plural also finds the singular ("shoes" finds "Running Shoe")."""
    if not q:
        return True
    t = (title or "").lower()
    return all(any(re.search(rf"(?<![a-z0-9]){re.escape(x)}", t) for x in _stems(w)) for w in q.lower().split())


def _priced_min(now: datetime, r: dict) -> int | None:
    return _minutes(now, r["priced_at"]) if r.get("priced_at") else None


def _keep(r: dict, tier: str, acceptable: bool, category: str | None, q: str | None, sub: str | None = None) -> bool:
    return ((tier == "all" or (r["strict"] or 0) >= HEADLINE)
            and (acceptable or r["cond"] != ACCEPTABLE)
            and (category is None or r["category"] == category)
            and (sub is None or r.get("_sub") == sub)
            and matches(r["title"], q))


def group_products(rows: list[dict], now: datetime) -> list[dict]:
    """One card per parent product (D39: sizes and colours together), live-checked and seen-only kept apart.
    Units best-first; `variants` counts the ASINs under the card (rule 9: ASIN and parent counts stay separate)."""
    by: dict[tuple, list[dict]] = {}
    for r in rows:
        by.setdefault((r.get("parent_asin") or r["asin"], r.get("source") is None), []).append(r)
    out = []
    for _, us in by.items():
        us.sort(key=score, reverse=True)
        best = us[0]
        asin = best["asin"]
        units = [{"condition": u["cond"], "price": u["resale_cents"] / 100, "pct_off": round(u["strict"] * 100),
                  "score": score(u), "minutes_since_confirmed": _minutes(now, u["last_confirmed_at"]),
                  "unconfirmed": u["unconfirmed"], "confidence": live_confidence(u, now)} for u in us]
        seen_only = best.get("source") is not None
        out.append({
            "asin": asin, "title": best["title"], "category": best["category"], "image": image_url(best["image"]),
            "url": f"https://www.amazon.com/dp/{asin}?aod=1",
            "subcategory": best.get("_sub"), "variants": len({u["asin"] for u in us}),
            "inverted": best.get("_inv"),
            # D39: seen-only cards show why a reference may be off instead of being held for review
            "check_reference": review_reasons(best.get("ref_flags"), best.get("strict")) if seen_only else [],
            "score": units[0]["score"], "score_parts": breakdown(best), "pct_off": max(u["pct_off"] for u in units),
            "price": min(u["price"] for u in units), "near_miss": best["strict"] < HEADLINE,
            "unit_count": len(units), "minutes_since_confirmed": min(u["minutes_since_confirmed"] for u in units),
            "minutes_since_priced": _priced_min(now, best),
            "is_new": (_priced_min(now, best) is not None and _priced_min(now, best) < NEW_HOURS * 60),
            "confidence": max((u["confidence"] for u in units), key=lambda c: c["p"]),
            # D33/D39: seen in Keepa's deal feed (sweeps beyond the rank limit, census) but never live-checked by us
            "verified": not seen_only, "source": best.get("source") or "live",
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
               fetch_status: Callable[[], dict] = pg_status, fetch_seen: Callable[[], list[dict]] = pg_seen,
               fetch_nodes: Callable[[], list[dict]] = pg_nodes,
               fetch_review: Callable[[], list[dict]] = pg_review,
               fetch_curated: Callable[[], list[dict]] = pg_curated,
               curate: Callable[[str, dict, tuple, str], dict] = pg_curate,
               fetch_users: Callable[[], list[dict]] = pg_users,
               touch_user: Callable[[str, bool], None] = pg_touch_user,
               set_user: Callable[[str, dict, bool, str], dict] = pg_set_user,
               password: str | None = None, user: str = "fiftyoff",
               admin_password: str | None = None, tags: tuple[str, ...] | None = None,
               verifier: access.AccessVerifier | None | bool = True, admin_emails: str | None = None) -> FastAPI:
    """`password` (default: PREVIEW_PASSWORD env) turns on a browser login popup (HTTP Basic Auth) for
    everything except /api/health. `admin_password` (default: ADMIN_PASSWORD env) opens /admin/ and
    /admin/api/* to user "admin"; without it they stay closed. Only safe behind HTTPS (the Cloudflare tunnel).

    D37: with CF_ACCESS_TEAM + CF_ACCESS_AUD set (`verifier`; True = from env), a request carrying a valid
    Cloudflare Access token is let in as that person: viewers see the preview, admins (app_user role, or
    ADMIN_EMAILS owners) also see /admin/, and deactivated people see nothing. Requests without a valid token
    fall back to the passwords above, until they're removed from .env at cutover."""
    app = FastAPI(title="fiftyoff", docs_url=None, redoc_url=None)
    password = password if password is not None else os.environ.get("PREVIEW_PASSWORD") or None
    admin_password = admin_password if admin_password is not None else os.environ.get("ADMIN_PASSWORD") or None
    allowed_tags = tags if tags is not None else admin_tags()
    expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode() if password else None
    expected_admin = "Basic " + base64.b64encode(f"admin:{admin_password}".encode()).decode() if admin_password else None
    cache: dict[str, tuple[float, list[dict]]] = {}
    verifier = default_verifier() if verifier is True else verifier or None
    owner_emails = access.owners(admin_emails if admin_emails is not None else os.environ.get("ADMIN_EMAILS"))
    touched: dict[str, float] = {}

    def person(email: str) -> dict | None:
        return next((u for u in cached("users", fetch_users) if u["email"] == email), None)

    def admin_email(email: str | None) -> str | None:
        if not email:
            return None
        if email in owner_emails:
            return email
        u = person(email)
        return email if u and u["active"] and u["role"] == "admin" else None

    def is_admin(request: Request) -> str | None:
        """The admin identity, or None: a verified Access email with the admin role (D37), else the Phase 1
        admin password while it's still set. Routes only depend on this hook."""
        if getattr(request.state, "admin", None):
            return request.state.admin
        if expected_admin and secrets.compare_digest(request.headers.get("authorization", ""), expected_admin):
            return "admin"
        return None

    def login(realm: str) -> Response:
        return Response("Login required", status_code=401, headers={"WWW-Authenticate": f'Basic realm="{realm}"'})

    def touch(email: str) -> None:
        now = time.monotonic()
        if now - touched.get(email, float("-inf")) < TOUCH_SECONDS:
            return
        touched[email] = now
        try:
            touch_user(email, email in owner_emails)
        except Exception:  # noqa: BLE001 — bookkeeping must never block a page
            touched.pop(email, None)

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        admin_path = path == "/admin" or path.startswith("/admin/")
        request.state.email = request.state.admin = None
        email = await run_in_threadpool(verifier.verify, request.headers.get(access.HEADER)) \
            if verifier and path != "/api/health" else None  # a key refresh is a blocking HTTPS call
        if email:  # D37: a person Cloudflare Access let through, verified by us
            u = None if email in owner_emails else await run_in_threadpool(person, email)
            if u and not u["active"]:
                return Response("Your access to the fiftyoff preview has been turned off.", status_code=403)
            await run_in_threadpool(touch, email)
            request.state.email, request.state.admin = email, await run_in_threadpool(admin_email, email)
            if admin_path and not request.state.admin:
                return Response("Admins only.", status_code=403)
        elif admin_path:
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

    def pool_for(show: str, now: datetime) -> list[dict]:
        """Live-checked rows and/or seen-only rows (D39), each tagged with its subcategory (`_sub`)."""
        live = cached("live", fetch) if show != "seen" else []
        seen = []
        if show != "live":
            liveset = {r["asin"] for r in cached("live", fetch)}
            seen = [r for r in cached("seen", fetch_seen) if r["asin"] not in liveset
                    and _minutes(now, r["last_confirmed_at"]) <= SEEN_HOURS[show] * 60]
        nodes = {}
        if any(r.get("cats") and not r.get("cat_path") for r in seen):
            nodes = {n["id"]: (n["name"], n["parent_id"]) for n in cached("nodes", fetch_nodes)}
        return [{**r, "_sub": subcategory(r, nodes), "_inv": inversion(r)} for r in live + seen]

    @app.get("/api/feed")
    def feed(category: str | None = None,
             sort: str = Query("best", pattern="^(best|discount|newest|confirmed|price)$"), fresh: bool = False,
             show: str = Query("all", pattern="^(all|live|seen)$"), sub: str | None = Query(None, max_length=120),
             tier: str = Query("50", pattern="^(50|all)$"), acceptable: bool = False,
             q: str | None = Query(None, max_length=80), conf: str = Query("likely", pattern="^(all|likely|high)$"),
             inverted: bool = False, cap: bool = False,
             limit: int = Query(100, ge=1, le=500)):
        now = datetime.now(timezone.utc)
        pool = pool_for(show, now)
        # 10-06 test: `inverted` shows only inverted deals; `cap` measures them against the list price (the B arm)
        if cap:
            pool = [cap_at_list(r) for r in pool]
            pool = [r for r in pool if (r["strict"] >= 0.40 and r["ref_cents"] >= 10000)
                    or (r["strict"] >= 0.30 and r["ref_cents"] >= 20000)]  # the tiers (TrackerConfig.tiers)
        n_inverted = len({r["asin"] for r in pool if r["_inv"] and _keep(r, tier, acceptable, category, q, sub)})
        if inverted:
            pool = [r for r in pool if r["_inv"]]
        cats: dict[str, int] = {}
        for r in pool:  # category counts under every filter except the category itself (for the dropdown)
            if _keep(r, tier, acceptable, None, q, sub):
                cats[r["category"]] = cats.get(r["category"], 0) + 1
        rows = [r for r in pool if _keep(r, tier, acceptable, category, q, sub)
                and (not fresh or (_priced_min(now, r) is not None and _priced_min(now, r) < NEW_HOURS * 60))]
        # live confidence applies to live-checked units; a seen-only card instead says when the feed last showed it
        held = sum(r.get("source") is None and RANK[live_confidence(r, now)["label"]] < CONF_MIN[conf] for r in rows)
        rows = [r for r in rows if r.get("source") is not None or RANK[live_confidence(r, now)["label"]] >= CONF_MIN[conf]]
        products = sorted(group_products(rows, now), key=SORTS[sort])
        if sort == "best":
            # D39: a seen-only card whose reference looks off ranks as if it scored 25% less (the score shown is unchanged)
            products.sort(key=lambda p: -p["score"] * (FLAGGED_RANK if p["check_reference"] else 1))
            if not (sub or q):
                products = diversify(products)
        return {"products": products[:limit], "count": len(products), "units": len(rows), "held_back": held,
                "asins": len({r["asin"] for r in rows}), "inverted_count": n_inverted,
                "seen_only": sum(not p["verified"] for p in products),
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

    @app.get("/admin/api/me")
    def admin_me(request: Request):
        return {"email": request.state.email, "admin": is_admin(request), "owner": request.state.email in owner_emails,
                "access": verifier is not None,
                "logout": "/cdn-cgi/access/logout" if request.state.email else None}

    @app.get("/admin/api/people")
    def admin_people():
        """D37: everyone who has signed in through Cloudflare Access (or was set up here first)."""
        now = datetime.now(timezone.utc)
        rows = sorted(fetch_users(), key=lambda u: u["last_seen"] or u["updated_at"] or now, reverse=True)
        items = [{"email": u["email"], "role": "admin" if u["email"] in owner_emails else u["role"],
                  "active": True if u["email"] in owner_emails else u["active"], "owner": u["email"] in owner_emails,
                  "note": u["note"], "first_seen": u["first_seen"].isoformat() if u["first_seen"] else None,
                  "minutes_since_seen": _minutes(now, u["last_seen"]) if u["last_seen"] else None,
                  "updated_by": u["updated_by"]} for u in rows]
        return {"items": items, "count": len(items), "owners": sorted(owner_emails), "access": verifier is not None,
                "generated_at": now.isoformat()}

    @app.post("/admin/api/people/{email}")
    def admin_set_person(email: str, body: dict, request: Request):
        """{role?, active?, note?}. Invites themselves happen in the Cloudflare Access allow-list."""
        email = email.strip().lower()
        if not re.fullmatch(r"[^@\s/]{1,64}@[^@\s/]{1,190}\.[a-z]{2,}", email):
            return Response("bad email", status_code=400)
        try:
            out = set_user(email, body, email in owner_emails, is_admin(request))
        except ValueError as e:
            return Response(str(e), status_code=400)
        cache.pop("users", None)  # role and deactivation apply on the next request
        return {"email": email, **out}

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
