"""Public API v1 and the beta site (docs/handoffs/api-v1.md).

Every viewer gets the same bytes: there is no admin branch here, so these routes never call `is_admin`, and the
edge may cache them once the beta opens. Fields are the allowlist in DEAL / GONE / SHELF below; score, appeal,
rank and the other internals feed the order but never leave (CLAUDE.md, D19/D24/D36).

Payloads come from a snapshot that a background thread rebuilds every SNAPSHOT_SECONDS; endpoints only read it
(index into it, or filter and page its ordered deal list), so no request runs the selection or waits on Postgres. `/d/{slug}` logs one click row and
redirects: to Amazon while a qualifying unit is live, else to our "this one sold" page.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .score import image_url
from .shelving import AISLE_NAMES, UNSORTED

log = logging.getLogger("fiftyoff.api_v1")
if not log.handlers:  # uvicorn configures only its own loggers; without this the build timings go nowhere
    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)

SNAPSHOT_SECONDS = 60
SNAPSHOT_LOG_EVERY = 60  # log a build's timing once an hour (and every slow one)
SNAPSHOT_SLOW = 10.0  # a normal build is ~6 s on the VPS (10-11)
ATTRIBUTION = {"text": "Data by Keepa", "url": "https://keepa.com"}
ACCEPTABLE = "Used - Acceptable"
JUST_IN = 5           # today: the newest cards
TODAY_SHELVES = 8     # today: featured `front` shelves, in delight order...
TODAY_PER_SHELF = 5   # ...with this many cards each
TODAY_GONE = 6
SAME_SHELF = 3        # the "this one sold" page: live cards from the same shelf
GONE_WINDOWS = {"24h": 24, "3d": 72, "7d": 168}
GRADES = {"like-new": "Like New", "very-good": "Very Good", "good": "Good", "acceptable": "Acceptable"}
DEFAULT_GRADES = ("like-new", "very-good", "good")  # the site's default; Acceptable only when asked for
PRICE_BANDS = {"any": (0, float("inf")), "under-100": (0, 100), "100-300": (100, 300), "300-plus": (300, float("inf"))}
PAGE = 60
SURFACES = {"web", "email", "push"}

DEAL = ("id", "slug", "title", "image", "shelf", "aisle", "pct_off", "price", "from", "usual_price", "condition",
        "variants", "units", "fit", "landed_at", "is_new", "url")
GONE = DEAL + ("gone_at", "last_price", "up_for_min", "up_for_is_lower_bound")
SHELF = ("id", "name", "aisle", "aisle_name", "description", "live", "per_week")
# never in a v1 payload, at any depth (the handoff's list; the allowlists above already keep them out)
FORBIDDEN = {"score", "score_parts", "delight", "appeal", "rank", "monthly_sold", "arb", "confidence",
             "check_reference", "source", "verified", "watching", "watchers", "why", "tags", "ref_flags", "ref_cents"}

CACHE_OPEN = {"v1": "public, max-age=30, s-maxage=60, stale-while-revalidate=300",
              "static": "public, max-age=31536000, immutable", "html": "public, max-age=0, s-maxage=60"}
# Until the beta opens (SITE_OPEN), nothing may sit in a shared cache: Cloudflare would keep one password-checked
# 200 and serve it to anyone.
CACHE_CLOSED = {"v1": "private, max-age=30", "static": "private, max-age=31536000, immutable", "html": "private, max-age=0"}


def _iso(t: datetime | None) -> str | None:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def slug(asin: str, title: str | None) -> str:
    """lower(asin) + the first six title words, URL-safe. /d/ resolves on the ASIN prefix only."""
    words = re.findall(r"[a-z0-9]+", (title or "").lower())[:6]
    return "-".join([asin.lower(), *words])


def condition(cond: str | None) -> str | None:
    """"Used - Like New" -> "Like New"."""
    return cond.removeprefix("Used - ") if cond else cond


def _lead(rows: list[dict]) -> dict:
    """The unit a card quotes: the cheapest (best % off on a tie), so price, usual price and % off agree."""
    return min(rows, key=lambda r: (r["resale_cents"], -(r["strict"] or 0)))


def deal(p: dict, now: datetime) -> dict:
    """A card from api.public_deals (with `_rows`) -> the public Deal. It quotes one unit, the cheapest: its ASIN,
    title, price, reference and condition; `from` says other variants cost more."""
    rows = p["_rows"]
    lead, best = _lead(rows), rows[0]
    s = slug(lead["asin"], lead["title"])  # the link goes to the unit the card quotes
    landed = best.get("priced_at")
    return {"id": lead["asin"], "slug": s, "title": lead["title"], "image": image_url(lead["image"]), "shelf": p["shelf"],
            "aisle": p["aisle"], "pct_off": round(lead["strict"] * 100), "price": lead["resale_cents"] / 100,
            "from": len({r["resale_cents"] for r in rows}) > 1,
            "usual_price": lead["ref_cents"] / 100 if lead.get("ref_cents") else None,
            "condition": condition(lead["cond"]), "variants": p["variants"], "units": p["unit_count"],
            "fit": bool((p["appeal"] or {}).get("fit")), "landed_at": _iso(landed),
            "is_new": bool(p["is_new"]), "url": f"/d/{s}"}


def gone(r: dict, now: datetime) -> dict:
    """A placed gone row from api.public_gone (`_shelf`, `_aisle`, `_fit`, `_lifespan`) -> the public Gone."""
    s = slug(r["asin"], r["title"])
    ls = r.get("_lifespan") or {}
    price = r["resale_cents"] / 100
    return {"id": r["asin"], "slug": s, "title": r["title"], "image": image_url(r["image"]), "shelf": r["_shelf"],
            "aisle": r["_aisle"], "pct_off": round(r["strict"] * 100), "price": price, "from": False,
            "usual_price": r["ref_cents"] / 100 if r.get("ref_cents") else None, "condition": condition(r["cond"]),
            "variants": 1, "units": 1, "fit": r["_fit"], "landed_at": _iso(r.get("priced_at")), "is_new": False,
            "url": f"/d/{s}", "gone_at": _iso(r["gone_at"]), "last_price": price,
            "up_for_min": ls.get("lower_min"), "up_for_is_lower_bound": ls.get("upper_min") is None}


def aisle_counts(deals: list[dict]) -> list[dict]:
    n: dict[str, int] = {}
    for d in deals:
        n[d["aisle"]] = n.get(d["aisle"], 0) + 1
    return [{"id": a, "name": AISLE_NAMES.get(a, a), "count": c} for a, c in sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))]


SORTS = {"newest": lambda d: d["landed_at"] or "", "discount": lambda d: d["pct_off"], "price-asc": lambda d: -d["price"],
         "price-desc": lambda d: d["price"]}  # each sorted descending; ties keep the delight order


def page_deals(deals: list[dict], now: datetime, aisle: str | None = None, cond: tuple[str, ...] = DEFAULT_GRADES,
               price: str = "any", nofit: bool = False, sort: str = "newest", since: datetime | None = None,
               limit: int = PAGE, offset: int = 0) -> dict:
    """The All deals page: the design's filters (condition, price band, aisle, hide size-dependent) and sorts. With
    `since` (the visitor's last look), cards that landed after it come first ("new since your last look")."""
    grades = {GRADES[c] for c in cond}
    lo, hi = PRICE_BANDS[price]
    pool = [d for d in deals if d["condition"] in grades and lo <= d["price"] < hi and not (nofit and d["fit"])]
    cut = _iso(since) if since else None
    matched = [d for d in pool if not aisle or d["aisle"] == aisle]
    key = SORTS[sort]
    matched = sorted(matched, key=lambda d: (bool(cut) and (d["landed_at"] or "") > cut, key(d)), reverse=True)
    return {"deals": matched[offset:offset + limit], "count": len(matched), "total": len(deals),
            "new_count": sum((d["landed_at"] or "") > cut for d in matched) if cut else None,
            "aisles": aisle_counts(pool),  # counted under every filter except the aisle itself
            "generated_at": _iso(now), "attribution": ATTRIBUTION}


def _shelf_name(meta: dict, sid: str) -> str:
    n = meta.get(sid, {}).get("name") or ("just in" if sid == UNSORTED else sid.replace("-", " "))
    return n[:1].upper() + n[1:]


def build(now: datetime, cards: list[dict], gone_rows: list[dict], meta: dict, per_week: dict[str, int]) -> dict:
    """Every v1 payload, plus the indexes the per-item endpoints read. Pure: the inputs are the public selection
    (api.public_deals with Acceptable units kept, api.public_gone), the shelf rows and the arrivals per shelf."""
    cards = sorted(cards, key=lambda p: (-p["delight"], -p["score"]))
    deals = [deal(p, now) for p in cards]
    # a seen-only row Keepa gave no grade ("Unknown") can't match the site's condition filter: left out, counted
    graded = [d["condition"] in GRADES.values() for d in deals]
    ungraded = graded.count(False)
    cards = [p for p, ok in zip(cards, graded) if ok]
    deals = [d for d, ok in zip(deals, graded) if ok]
    prime = [d for d in deals if d["condition"] != condition(ACCEPTABLE)]  # what the site shows by default
    by_shelf: dict[str, list[dict]] = {}
    for d in deals:
        by_shelf.setdefault(d["shelf"], []).append(d)
    aisles = aisle_counts(prime)

    # shelves in the shelves page's order: the mean delight of their three best cards, empty ones last
    delight = {}
    for p in cards:
        delight.setdefault(p["shelf"], []).append(p["delight"])
    public_ids = [sid for sid, x in meta.items() if x.get("role") in ("front", "aisle")]
    if UNSORTED in by_shelf:
        public_ids.append(UNSORTED)
    order = sorted(public_ids, key=lambda k: (k == UNSORTED, -sum(delight.get(k, [0])[:3]) / 3, k))

    def shelf(sid: str) -> dict:
        x = meta.get(sid, {})
        aisle = x.get("aisle") or (by_shelf[sid][0]["aisle"] if by_shelf.get(sid) else "other")
        return {"id": sid, "name": _shelf_name(meta, sid), "aisle": aisle, "aisle_name": AISLE_NAMES.get(aisle, aisle),
                "description": x.get("description"), "live": len(by_shelf.get(sid, [])), "per_week": per_week.get(sid, 0)}

    shelves = {sid: shelf(sid) for sid in order}
    gone_items = sorted((gone(r, now) for r in gone_rows), key=lambda g: g["gone_at"] or "", reverse=True)
    gone_by_window = {}
    for w, hours in GONE_WINDOWS.items():
        cut = _iso(now - timedelta(hours=hours))
        items = [g for g in gone_items if (g["gone_at"] or "") >= cut]
        gone_by_window[w] = {"gone": items, "count": len(items), "attribution": ATTRIBUTION, "generated_at": _iso(now)}
    featured = [sid for sid in order if sid != UNSORTED and meta.get(sid, {}).get("role") == "front"
                and any(d["condition"] != condition(ACCEPTABLE) for d in by_shelf.get(sid, []))][:TODAY_SHELVES]
    just_in = sorted((d for d in prime if d["landed_at"]), key=lambda d: d["landed_at"], reverse=True)

    by_asin = {}
    for p, d in zip(cards, deals):
        for r in p["_rows"]:
            by_asin.setdefault(r["asin"], d)
    gone_by_asin = {}
    for g in gone_items:
        gone_by_asin.setdefault(g["id"], g)
    return {
        "built_at": now, "ungraded": ungraded,
        "deals": deals,  # in delight order; /deals filters, sorts and pages it per request
        "today": {"just_in": just_in[:JUST_IN], "last_landed_at": just_in[0]["landed_at"] if just_in else None,
                  "aisles": aisles,
                  "shelves": [{**shelves[sid], "deals": [d for d in by_shelf[sid] if d["condition"] != condition(ACCEPTABLE)][:TODAY_PER_SHELF]}
                              for sid in featured],
                  "gone": gone_items[:TODAY_GONE], "generated_at": _iso(now), "attribution": ATTRIBUTION},
        "shelves": {"shelves": list(shelves.values()), "generated_at": _iso(now), "attribution": ATTRIBUTION},
        "shelf": {sid: {"shelf": s, "deals": by_shelf.get(sid, []), "generated_at": _iso(now), "attribution": ATTRIBUTION}
                  for sid, s in shelves.items()},
        "gone": gone_by_window,
        "by_asin": by_asin, "gone_by_asin": gone_by_asin,
        "by_shelf_prime": {sid: [d for d in ds if d["condition"] != condition(ACCEPTABLE)] for sid, ds in by_shelf.items()},
    }


class Snapshot:
    """The latest build, swapped in whole. `start()` rebuilds it every `interval` seconds on a daemon thread."""

    def __init__(self, build: Callable[[datetime], dict], interval: float = SNAPSHOT_SECONDS):
        self.build, self.interval = build, interval
        self.data: dict | None = None
        self._thread: threading.Thread | None = None
        self.builds = 0

    def refresh(self, now: datetime | None = None) -> dict:
        t = time.monotonic()
        self.data = self.build(now or datetime.now(timezone.utc))
        took = time.monotonic() - t
        if self.builds % SNAPSHOT_LOG_EVERY == 0 or took > SNAPSHOT_SLOW:
            log.info("v1 snapshot: %d deals (%d ungraded left out), %d gone in 7 d, built in %.1f s",
                     len(self.data["deals"]), self.data["ungraded"], self.data["gone"]["7d"]["count"], took)
        self.builds += 1
        return self.data

    def _run(self) -> None:
        while True:
            try:
                self.refresh()
            except Exception:  # noqa: BLE001 — one failed build keeps the last snapshot; the next try is a minute away
                log.exception("v1 snapshot build failed")
            time.sleep(self.interval)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="v1-snapshot", daemon=True)
            self._thread.start()


ASIN = re.compile(r"[A-Z0-9]{10}")
SLUG = re.compile(r"([a-z0-9]{10})(?:-[a-z0-9-]*)?")


def create_site(snapshot: Snapshot, log_click: Callable[[dict], None], site_dir: Path, is_open: Callable[[], bool]) -> FastAPI:
    """The beta site's app: /api/v1, /d/{slug} and the static export (web/out). Mounted per host by api.create_app,
    inside its gate middleware (the preview password applies until the beta opens)."""
    site = FastAPI(title="fiftyoff site", docs_url=None, redoc_url=None, openapi_url=None)
    v1 = APIRouter(prefix="/api/v1")

    def snap() -> dict | None:
        return snapshot.data

    def unavailable() -> Response:
        return JSONResponse({"error": "warming up"}, status_code=503, headers={"Retry-After": "5"})

    get = lambda path: v1.api_route(path, methods=["GET", "HEAD"])  # noqa: E731 — curl -I works too

    @get("/deals")
    def deals(aisle: str | None = Query(None, max_length=40),
              cond: list[str] = Query(list(DEFAULT_GRADES)), price: str = Query("any", pattern="^(any|under-100|100-300|300-plus)$"),
              nofit: bool = False, sort: str = Query("newest", pattern="^(newest|discount|price-asc|price-desc)$"),
              since: datetime | None = None, limit: int = Query(PAGE, ge=1, le=200), offset: int = Query(0, ge=0)):
        s = snap()
        if not s:
            return unavailable()
        cond = [c for x in cond for c in x.split(",") if c]  # ?cond=like-new&cond=good or ?cond=like-new,good
        if not cond or any(c not in GRADES for c in cond):
            return JSONResponse({"error": f"cond: one or more of {', '.join(GRADES)}"}, status_code=422)
        if since and since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        return page_deals(s["deals"], s["built_at"], aisle, tuple(cond), price, nofit, sort, since, limit, offset)

    @get("/today")
    def today():
        s = snap()
        return s["today"] if s else unavailable()

    @get("/shelves")
    def shelves():
        s = snap()
        return s["shelves"] if s else unavailable()

    @get("/shelves/{shelf_id}")
    def shelf(shelf_id: str):
        s = snap()
        if not s:
            return unavailable()
        return s["shelf"].get(shelf_id) or JSONResponse({"error": "no such shelf"}, status_code=404)

    @get("/gone")
    def gone_list(window: str = Query("24h", pattern="^(24h|3d|7d)$")):
        s = snap()
        return s["gone"][window] if s else unavailable()

    @get("/product/{asin}")
    def product(asin: str):
        s = snap()
        if not s:
            return unavailable()
        asin = asin.upper()
        if not ASIN.fullmatch(asin):
            return JSONResponse({"error": "bad asin"}, status_code=404)
        d, g = s["by_asin"].get(asin), s["gone_by_asin"].get(asin)
        shelf_id = (d or g or {}).get("shelf")
        same = [x for x in s["by_shelf_prime"].get(shelf_id, []) if x is not d][:SAME_SHELF]
        return {"deal": d, "gone": None if d else g, "same_shelf": same, "attribution": ATTRIBUTION}

    site.include_router(v1)

    def record(row: dict) -> None:
        try:
            log_click(row)
        except Exception:  # noqa: BLE001 — a lost click row never costs the visitor their redirect
            log.exception("click insert failed")

    @site.api_route("/d/{slug_}", methods=["GET", "HEAD"])
    def out(slug_: str, request: Request, background: BackgroundTasks, s_: str | None = Query(None, alias="s", max_length=10)):
        m = SLUG.fullmatch(slug_.lower())
        asin = m.group(1).upper() if m else None
        s = snap()
        live = None if s is None or asin is None else asin in s["by_asin"]
        if asin and live is not False:  # live, or the snapshot isn't built yet: send them on rather than to "sold"
            to = f"https://www.amazon.com/dp/{asin}?aod=1"
        else:
            to = f"/sold/?id={asin}" if asin else "/sold/"
        ref = request.headers.get("referer")
        background.add_task(record, {"asin": asin, "slug": slug_[:120], "surface": s_ if s_ in SURFACES else None,
                                     "live": live, "referer_path": urlsplit(ref).path[:200] if ref else None})
        return RedirectResponse(to, status_code=302)

    def page(*parts: str) -> Response:
        f = site_dir.joinpath(*parts, "index.html")
        return FileResponse(f, media_type="text/html") if f.is_file() else Response("Not found", status_code=404)

    # The export has one page per dynamic route; the page reads its id from the URL (web.md).
    @site.get("/shelf/{rest:path}")
    def shelf_page(rest: str):
        return page("shelf", "_")

    @site.get("/sold/{rest:path}")
    def sold_page(rest: str):
        return page("sold")

    site.mount("/", StaticFiles(directory=site_dir, html=True, check_dir=False), name="web")

    @site.middleware("http")
    async def cache_headers(request: Request, call_next):
        resp = await call_next(request)
        path = request.url.path
        rules = CACHE_OPEN if is_open() else CACHE_CLOSED
        if path.startswith("/d/") or resp.status_code >= 500:
            resp.headers["Cache-Control"] = "no-store"
        elif path.startswith("/api/v1/"):
            resp.headers["Cache-Control"] = rules["v1"]
        elif path.startswith("/_next/static/"):
            resp.headers["Cache-Control"] = rules["static"]
        else:
            resp.headers["Cache-Control"] = rules["html"]
        return resp

    return site
