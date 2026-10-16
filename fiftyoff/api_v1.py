"""Public API v1 and the beta site (docs/handoffs/api-v1.md).

Every viewer gets the same bytes: there is no admin branch here, so these routes never call `is_admin`, and the
edge may cache them once the beta opens. Fields are the allowlist in DEAL / GONE / SHELF below; score, appeal,
rank and the other internals feed the order but never leave (CLAUDE.md, D19/D24/D36).

Payloads come from a snapshot that a background thread rebuilds every SNAPSHOT_SECONDS; endpoints only read it
(index into it, or filter and page its ordered deal list), so no request runs the selection or waits on Postgres. `/d/{slug}` logs one click row and
redirects: to Amazon while a qualifying unit is live, else to our "this one sold" page.
"""

from __future__ import annotations

import html
import logging
import random
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

from . import sizes as sz
from .alerts import no_store_path
from .search import WORD, matches, words  # noqa: F401 — shared with keyword alerts (notify.py)
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
# today-quality §4: Just in, newest first among cards that pass every gate (never an ungated fallback)
JUST_IN = 5           # today: at most this many
JUST_IN_H = 24        # landed within this many hours
JUST_IN_APPEAL = 6    # the stored appeal rating (D42) at or above this
# today-quality §8 (amends D56): Today has a row for every `front` shelf with live cards. Rotation sets the order:
TODAY_SHELVES = None  # a cap on the rows, if the payload grows (None: every shelf)
TODAY_PINNED = 3      # the best-scoring few first every day, then...
TODAY_POOL = 16       # ...the rest of the top this many, shuffled per day (seed = the UTC date), then the others in score order
TODAY_PER_SHELF = 5   # cards per row
# D66: the shelves that open Today, in this order, every day (when they have live cards). Hand-kept: edit freely. The
# other front shelves follow under `rotate`.
TODAY_SHELF_ORDER = ("watches", "jewelry", "handbags-sunglasses", "wearables-gadgets", "laptops-tablets",
                     "headphones-earbuds", "luggage", "cameras-lenses", "cookware-knives")  # robot vacuums out (user,
# 10-15: lower interest; 5 live, so one in Featured left a row of 4): it rotates with the rest
SHELF_GONE = 12       # D66: a shelf page ends with its recently gone units (the 7-day window), up to this many
TODAY_GONE = 6
TODAY_GONE_WINDOW = "3d"  # the strip uses /gone/'s default window, so the two agree (REPORT 10)
# The featured row (trust-first §1.2; D63): from every Today shelf, the best-rated cards that pass every rule, one per
# shelf, by appeal and then delight. The appeal rating (D42) is the brand test: the rubric gives 7-8 to "a recognised,
# well-regarded brand" and 9-10 to "a well-known, desirable brand". Tunable.
FEATURED_N = 5                # the lead card and four beside it...
FEATURED_POOL = 10            # ...drawn from the best this many (one per shelf), a new draw every hour (seed = the UTC
FEATURED_ROTATE_H = 1         # hour), so the top of the page looks fresh; the draw keeps the pool's order
FEATURED_APPEAL = 8           # the stored appeal rating at or above this...
FEATURED_FILL_APPEAL = 7      # ...then, if fewer than FEATURED_N pass, this
FEATURED_FRESH_H = 24        # last confirmed within this many hours (19 of 22 cards rated 8+ were, 10-14; 12 h: 15)
FEATURED_MIN_USUAL = 80.0    # usual price floor, dollars
FEATURED_PCT = (50, 75)      # a believable band: 91% reads fake (Priya)
MIX_RUN = 2                  # the default All deals order: at most this many cards in a row from one shelf
# trust-first §4.4, the "almost half off" page: deals we already hold under 50% (tracker tiers), no extra Keepa spend.
# Branded and well rated only, and fresh: live units are checked like the rest, seen ones by the 12 h sweep.
ALMOST_APPEAL = 5            # the stored appeal rating (D42) at or above this
ALMOST_FRESH_H = 24          # the quoted unit seen within this many hours
ALMOST_MAX = 120
SAME_SHELF = 3        # the "this one sold" page: live cards from the same shelf
GONE_WINDOWS = {"24h": 24, "3d": 72, "7d": 168}
GRADES = {"like-new": "Like New", "very-good": "Very Good", "good": "Good", "acceptable": "Acceptable"}
DEFAULT_GRADES = ("like-new", "very-good", "good")  # the site's default; Acceptable only when asked for
PRICE_BANDS = {"any": (0, float("inf")), "under-100": (0, 100), "100-300": (100, 300), "300-plus": (300, float("inf"))}
PAGE = 60
# A/B arms: the tagline (trust-first), then the featured layout (D64: a lead card + rows, or a plain row of cards).
# Old rows have one letter (the tagline only). Anything else is stored as no arm.
VARIANTS = {"a", "b", "aa", "ab", "ba", "bb"}
PAGES = {"today", "deals", "shelf", "deal", "share", "search", "gone", "sold", "almost", "sizes"}  # share = a deal page opened from a shared link  # page_view counts
# ?s= on /d/ and /deal/ links: where the card was. D64: a card opens our deal page with its s=, and the deal page's
# Amazon button passes the same s= on (its click row's referer_path is /deal/...); "related" = the deal page's own
# "more on this shelf" cards, "deal" = a deal page reached with no s=.
SURFACES = {"web", "email", "push", "ios", "featured", "share", "search", "almost", "deal", "sizes", "related"}

DEAL = ("id", "slug", "title", "image", "shelf", "aisle", "pct_off", "price", "from", "usual_price", "condition",
        "variants", "units", "fit", "size", "landed_at", "is_new", "url", "confirmed_at",  # confirmed_at: our own last sighting
        "brand")  # alerts-beta: a keyword alert's prefill (brand + a model word)
# D59: the size picker's groups, in the order the page shows them (sizes.facet_key names them)
SIZE_GROUPS = (("letter", "S, M, L sizes"), ("num", "Numbered sizes"), ("waist", "Waist"), ("length", "Inseam"),
               ("shoe-men", "Men's shoes"), ("shoe-women", "Women's shoes"), ("shoe-kids", "Kids' shoes"))
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
    landed = lead.get("priced_at")  # QA 10-12: the quoted unit's own price time, not the top-scored variant's
    return {"id": lead["asin"], "slug": s, "title": lead["title"], "image": image_url(lead["image"]), "shelf": p["shelf"],
            "aisle": p["aisle"], "pct_off": round(lead["strict"] * 100), "price": lead["resale_cents"] / 100,
            "from": len({r["resale_cents"] for r in rows}) > 1,
            "usual_price": lead["ref_cents"] / 100 if lead.get("ref_cents") else None,
            "condition": condition(lead["cond"]), "variants": p["variants"], "units": p["unit_count"],
            "fit": bool((p["appeal"] or {}).get("fit")), "size": (p.get("_sizes", {}).get(lead["asin"]) or {}).get("label"),
            "landed_at": _iso(landed),
            "is_new": bool(p["is_new"]), "url": f"/d/{s}", "confirmed_at": _iso(lead.get("last_confirmed_at")),
            "brand": lead.get("brand") or next((r["brand"] for r in rows if r.get("brand")), None)}


def gone(r: dict, now: datetime) -> dict:
    """A placed gone row from api.public_gone (`_shelf`, `_aisle`, `_fit`, `_lifespan`) -> the public Gone."""
    s = slug(r["asin"], r["title"])
    ls = r.get("_lifespan") or {}
    price = r["resale_cents"] / 100
    return {"id": r["asin"], "slug": s, "title": r["title"], "image": image_url(r["image"]), "shelf": r["_shelf"],
            "aisle": r["_aisle"], "pct_off": round(r["strict"] * 100), "price": price, "from": False,
            "usual_price": r["ref_cents"] / 100 if r.get("ref_cents") else None, "condition": condition(r["cond"]),
            "variants": 1, "units": 1, "fit": r["_fit"], "size": (sz.parse(r["title"], r["_shelf"]) or {}).get("label") if r["_fit"] else None,
            "landed_at": _iso(r.get("priced_at")), "is_new": False,
            "url": f"/d/{s}", "confirmed_at": _iso(r.get("last_seen_at")), "gone_at": _iso(r["gone_at"]), "last_price": price,
            "up_for_min": ls.get("lower_min"), "up_for_is_lower_bound": ls.get("upper_min") is None, "brand": r.get("brand")}


def attach_sizes(p: dict) -> dict:
    """D59: each unit's size on a size-dependent card (the rater's `fit`), read from the unit's own title. The rater's
    stored size (rated per parent) stands in only when the card is one ASIN. Sets p["_sizes"]: asin -> size."""
    a = p.get("appeal") or {}
    p["_sizes"] = {}
    if not a.get("fit"):
        return p
    asins = {r["asin"] for r in p["_rows"]}
    for r in p["_rows"]:
        z = sz.parse(r["title"], p["shelf"])
        if z is None and len(asins) == 1:
            z = sz.parse_text(a.get("size"), p["shelf"], r["title"])
        if z:
            p["_sizes"][r["asin"]] = z
    return p


def size_facets(cards: list[dict], now: datetime) -> dict:
    """D59: the size picker. For each group, the sizes on offer and how many cards (not units) have one, Acceptable
    left out like every default count."""
    n: dict[tuple[str, str], set[int]] = {}
    sized = unsized = 0
    for i, p in enumerate(cards):
        if not (p.get("appeal") or {}).get("fit"):
            continue
        zs = [p["_sizes"][r["asin"]] for r in p["_rows"] if r["asin"] in p["_sizes"] and r["cond"] != ACCEPTABLE]
        if not zs:
            unsized += any(r["cond"] != ACCEPTABLE for r in p["_rows"])
            continue
        sized += 1
        for z in zs:
            for k in sz.facet_key(z):
                n.setdefault(k, set()).add(i)
    groups = []
    for gid, name in SIZE_GROUPS:
        vals = sorted(((v, len(ix)) for (g, v), ix in n.items() if g == gid), key=lambda kv: sz.order(gid, kv[0]))
        groups.append({"id": gid, "name": name, "values": [{"v": v, "n": c} for v, c in vals]})
    return {"groups": groups, "sized": sized, "unsized": unsized, "generated_at": _iso(now), "attribution": ATTRIBUTION}


def sized_deals(cards: list[dict], now: datetime, prefs: dict, cond: tuple[str, ...] = DEFAULT_GRADES,
                sort: str = "best", limit: int = PAGE, offset: int = 0) -> dict:
    """D59, the sizes page: size-dependent cards with a unit in one of the visitor's sizes, quoting the cheapest such
    unit. With no sizes given, every card with a readable size. Cards come in delight order ("best")."""
    grades = {GRADES[c] for c in cond}
    out = []
    for p in cards:
        if not p["_sizes"]:
            continue
        rows = [r for r in p["_rows"] if r["asin"] in p["_sizes"] and condition(r["cond"]) in grades
                and (not sz.wanted(prefs) or sz.matches(p["_sizes"][r["asin"]], prefs))]
        if rows:
            out.append(deal({**p, "_rows": rows}, now))
    if sort != "best":
        out.sort(key=SORTS[sort], reverse=True)
    return {"deals": out[offset:offset + limit], "count": len(out), "generated_at": _iso(now), "attribution": ATTRIBUTION}


def aisle_counts(deals: list[dict]) -> list[dict]:
    n: dict[str, int] = {}
    for d in deals:
        n[d["aisle"]] = n.get(d["aisle"], 0) + 1
    return [{"id": a, "name": AISLE_NAMES.get(a, a), "count": c} for a, c in sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))]


SORTS = {"newest": lambda d: d["landed_at"] or "", "mixed": lambda d: d["landed_at"] or "", "discount": lambda d: d["pct_off"],
         "price-asc": lambda d: -d["price"], "price-desc": lambda d: d["price"],
         "saved": lambda d: (d["usual_price"] or d["price"]) - d["price"]}  # each sorted descending; ties keep the delight order


SEARCH_GONE = 12  # gone matches shown under search results (D54)


def mix(deals: list[dict], run: int = MIX_RUN) -> list[dict]:
    """trust-first §1.4: newest first, but no more than `run` cards in a row from one shelf. Greedy: take the next
    card in order unless it would extend a run; then the first later card from another shelf. Deterministic."""
    rest, out = list(deals), []
    while rest:
        tail = [d["shelf"] for d in out[-run:]]
        blocked = len(tail) == run and len(set(tail)) == 1 and tail[0]
        i = next((k for k, d in enumerate(rest) if d["shelf"] != blocked), 0) if blocked else 0
        out.append(rest.pop(i))
    return out


def featured(rows: list[str], picks: dict[str, list[tuple[dict, dict]]], now: datetime) -> list[dict]:
    """D63, D64: up to FEATURED_N deals from Today's shelves (`rows`; `picks[shelf]`: its (card, Deal) pairs), one per
    shelf, best appeal first and then delight. Every one passes every rule: rated FEATURED_APPEAL or more (then
    FEATURED_FILL_APPEAL to fill), confirmed recently, not Acceptable, a usual price above the floor, % off in the
    believable band, no reference warning. D64: drawn each hour from the best FEATURED_POOL, kept in rank order (the
    lead card is the best of the draw). No model call here (rule 7): the ratings are stored."""
    lo, hi = FEATURED_PCT
    fresh = _iso(now - timedelta(hours=FEATURED_FRESH_H))
    appeal = lambda p: (p.get("appeal") or {}).get("score") or 0

    def ok(p: dict, d: dict) -> bool:
        # freshness of the unit the card quotes, not of its freshest variant (the deal page says "price as of")
        return not (d["shelf"] == UNSORTED or d["condition"] == "Acceptable" or (d.get("confirmed_at") or "") < fresh
                    or (d["usual_price"] or 0) < FEATURED_MIN_USUAL or not lo <= d["pct_off"] <= hi
                    or p.get("check_reference"))
    pool = sorted(((p, d) for sid in rows for p, d in picks.get(sid, []) if appeal(p) >= FEATURED_FILL_APPEAL and ok(p, d)),
                  key=lambda x: (appeal(x[0]) < FEATURED_APPEAL, -appeal(x[0]), -x[0]["delight"]))
    top, shelves = [], set()
    for _, d in pool:
        if d["shelf"] not in shelves:
            top.append(d)
            shelves.add(d["shelf"])
            if len(top) == FEATURED_POOL:
                break
    hour = int(now.timestamp() // (FEATURED_ROTATE_H * 3600))
    drawn = set(random.Random(hour).sample(range(len(top)), min(FEATURED_N, len(top))))
    return [d for i, d in enumerate(top) if i in drawn]


def just_in(pairs: list[tuple[dict, dict]], front: set[str], now: datetime, skip: set[str] = frozenset()) -> list[dict]:
    """today-quality §4: the newest cards that pass every gate: a `front` shelf, appeal ≥ JUST_IN_APPEAL, not
    Acceptable, not size-dependent (the payload is the same for everyone, so it can't know a visitor's sizes), landed
    within JUST_IN_H. Fewer than JUST_IN is fine; there's no ungated fallback."""
    cut = _iso(now - timedelta(hours=JUST_IN_H))
    ok = [d for p, d in pairs if d["shelf"] in front and d["condition"] != "Acceptable" and not d["fit"]
          and ((p.get("appeal") or {}).get("score") or 0) >= JUST_IN_APPEAL and (d["landed_at"] or "") >= cut
          and d["id"] not in skip]
    return sorted(ok, key=lambda d: d["landed_at"], reverse=True)[:JUST_IN]


def almost(cards: list[dict], now: datetime) -> list[dict]:
    """trust-first §4.4: from api.public_deals(almost=True) (in delight order): a brand, appeal ≥ ALMOST_APPEAL, no
    reference warning, not Acceptable, a real shelf, the quoted unit seen within ALMOST_FRESH_H. Never 50%+."""
    fresh = _iso(now - timedelta(hours=ALMOST_FRESH_H))
    out = []
    for p in cards:
        d = deal(p, now)
        if (d["pct_off"] >= 50 or d["shelf"] == UNSORTED or d["condition"] == "Acceptable"
                or (d["confirmed_at"] or "") < fresh or p.get("check_reference")
                or ((p.get("appeal") or {}).get("score") or 0) < ALMOST_APPEAL
                or not any(r.get("brand") for r in p["_rows"])):
            continue
        out.append(d)
        if len(out) == ALMOST_MAX:
            break
    return out


def rotate(order: list[str], day: str, n: int | None = TODAY_SHELVES, pinned: int = TODAY_PINNED,
           pool: int = TODAY_POOL) -> list[str]:
    """today-quality §8 (amends D56): the order of Today's shelf rows, every shelf in `order` (score order). The top
    `pinned` first every day, then the rest of the top `pool` shuffled with the UTC date as seed (so the second
    screen changes day to day), then the others in score order. `n` caps the rows."""
    mid = order[pinned:pool]
    random.Random(day).shuffle(mid)
    return (order[:pinned] + mid + order[pool:])[:n]


def related(s: dict, x: dict | None) -> tuple[list[dict], str | None]:
    """The deal page's "more on this shelf": up to SAME_SHELF live cards from the deal's shelf. D69: for a sized deal,
    the shelf's cards with a unit in the size it quotes, each quoting that unit (like the sizes page), when there are
    any; then the size's label is returned too."""
    if not x:
        return [], None
    shelf = [y for y in s["by_shelf_prime"].get(x["shelf"], []) if y["id"] != x["id"]]
    z = (sz.parse(x["title"], x["shelf"]) or sz.parse_text(x["size"], x["shelf"], x["title"])) if x.get("size") else None
    mine = set(sz.facet_key(z)) if z else set()
    fits = []
    for p in s["cards"] if mine else []:
        if p["shelf"] != x["shelf"] or not p["_sizes"] or any(r["asin"] == x["id"] for r in p["_rows"]):
            continue
        rows = [r for r in p["_rows"] if r["asin"] in p["_sizes"] and r["cond"] != ACCEPTABLE
                and mine & set(sz.facet_key(p["_sizes"][r["asin"]]))]
        if rows:
            fits.append(deal({**p, "_rows": rows}, s["built_at"]))
            if len(fits) == SAME_SHELF:
                break
    return (fits or shelf[:SAME_SHELF]), (z["label"] if fits else None)


def today_order(front: list[str], day: str) -> list[str]:
    """D66: Today's rows. TODAY_SHELF_ORDER's shelves first, in that order (those in `front`, i.e. with live cards),
    then the other front shelves under `rotate`."""
    pinned = [sid for sid in TODAY_SHELF_ORDER if sid in front]
    return pinned + rotate([sid for sid in front if sid not in pinned], day)


def page_deals(deals: list[dict], now: datetime, aisle: str | None = None, cond: tuple[str, ...] = DEFAULT_GRADES,
               price: str = "any", nofit: bool = False, sort: str = "newest", since: datetime | None = None,
               limit: int = PAGE, offset: int = 0, hide: frozenset[str] = frozenset(),
               only: set[int] | None = None) -> dict:
    """The All deals page: the design's filters (condition, price band, aisle, hide size-dependent) and sorts. With
    `since` (the visitor's last look), cards that landed after it come first ("new since your last look")."""
    grades = {GRADES[c] for c in cond}
    lo, hi = PRICE_BANDS[price]
    # `only`: the positions a search matched; `hide`: aisles the visitor turned off (§4.3)
    base = [d for i, d in enumerate(deals) if d["condition"] in grades and lo <= d["price"] < hi and not (nofit and d["fit"])
            and (only is None or i in only)]
    pool = [d for d in base if d["aisle"] not in hide]
    cut = _iso(since) if since else None
    matched = [d for d in pool if not aisle or d["aisle"] == aisle]
    key = SORTS[sort]
    matched = sorted(matched, key=lambda d: (bool(cut) and (d["landed_at"] or "") > cut, key(d)), reverse=True)
    if sort == "mixed":  # interleave within each group, so "new since your last look" still comes first
        fresh = [d for d in matched if cut and (d["landed_at"] or "") > cut]
        matched = mix(fresh) + mix(matched[len(fresh):])
    return {"deals": matched[offset:offset + limit], "count": len(matched), "total": len(deals),
            "new_count": sum((d["landed_at"] or "") > cut for d in matched) if cut else None,
            "aisles": aisle_counts(base),  # counted under every filter except the aisle and the hidden aisles
            "generated_at": _iso(now), "attribution": ATTRIBUTION}


def _shelf_name(meta: dict, sid: str) -> str:
    n = meta.get(sid, {}).get("name") or ("just in" if sid == UNSORTED else sid.replace("-", " "))
    return n[:1].upper() + n[1:]


def build(now: datetime, cards: list[dict], gone_rows: list[dict], meta: dict, per_week: dict[str, int],
          near: list[dict] | None = None) -> dict:
    """Every v1 payload, plus the indexes the per-item endpoints read. Pure: the inputs are the public selection
    (api.public_deals with Acceptable units kept, api.public_gone), the shelf rows and the arrivals per shelf."""
    cards = [attach_sizes(p) for p in sorted(cards, key=lambda p: (-p["delight"], -p["score"]))]
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

    def shelf(sid: str) -> dict:  # `live` leaves Acceptable out, like the aisle counts (REPORT 10)
        x = meta.get(sid, {})
        aisle = x.get("aisle") or (by_shelf[sid][0]["aisle"] if by_shelf.get(sid) else "other")
        return {"id": sid, "name": _shelf_name(meta, sid), "aisle": aisle, "aisle_name": AISLE_NAMES.get(aisle, aisle),
                "description": x.get("description"), "live": sum(d["condition"] != condition(ACCEPTABLE) for d in by_shelf.get(sid, [])), "per_week": per_week.get(sid, 0)}

    shelves = {sid: shelf(sid) for sid in order}
    gone_items = sorted((gone(r, now) for r in gone_rows), key=lambda g: g["gone_at"] or "", reverse=True)
    gone_by_window = {}
    for w, hours in GONE_WINDOWS.items():
        cut = _iso(now - timedelta(hours=hours))
        items = [g for g in gone_items if (g["gone_at"] or "") >= cut]
        gone_by_window[w] = {"gone": items, "count": len(items), "attribution": ATTRIBUTION, "generated_at": _iso(now)}
    # Today: a row per front shelf; Featured is the best-rated of them (D63), and rows skip its cards (a row left empty
    # drops out). Just in stays in the payload (the gated newest, maybe in a row too) but the site no longer shows it.
    pairs = [(p, d) for p, d in zip(cards, deals) if d["condition"] != condition(ACCEPTABLE)]
    picks: dict[str, list[tuple[dict, dict]]] = {}
    for p, d in pairs:
        picks.setdefault(d["shelf"], []).append((p, d))
    front = [sid for sid in order if sid != UNSORTED and meta.get(sid, {}).get("role") == "front" and picks.get(sid)]
    rows = today_order(front, now.date().isoformat())
    feat = featured(rows, picks, now)
    newest = just_in(pairs, set(front), now, skip={d["id"] for d in feat})
    shown = {d["id"] for d in feat}
    today_rows = [{**shelves[sid], "deals": [d for _, d in picks[sid] if d["id"] not in shown][:TODAY_PER_SHELF]}
                  for sid in rows]

    search = [words(d["title"], *(r.get("brand") for r in p["_rows"])) for p, d in zip(cards, deals)]
    by_asin = {}
    for p, d in zip(cards, deals):
        for r in p["_rows"]:
            by_asin.setdefault(r["asin"], d)
    gone_by_asin = {}
    for g in gone_items:
        gone_by_asin.setdefault(g["id"], g)
    return {
        "built_at": now, "ungraded": ungraded,
        "search": search, "gone_search": [words(g["title"]) for g in gone_by_window["7d"]["gone"]],
        "deals": deals,  # in delight order; /deals filters, sorts and pages it per request
        "today": {"just_in": newest, "last_landed_at": newest[0]["landed_at"] if newest else None,
                  "aisles": aisles,
                  # the count line under the tagline (today-quality §9): All deals' default count, shelves with live deals
                  "count": len(prime), "shelf_count": sum(1 for s in shelves.values() if s["live"] and s["id"] != UNSORTED),
                  "featured": feat,
                  "shelves": [r for r in today_rows if r["deals"]],
                  "gone": gone_by_window[TODAY_GONE_WINDOW]["gone"][:TODAY_GONE], "generated_at": _iso(now), "attribution": ATTRIBUTION},
        "shelves": {"shelves": list(shelves.values()), "generated_at": _iso(now), "attribution": ATTRIBUTION},
        "shelf": {sid: {"shelf": s, "deals": by_shelf.get(sid, []),
                        "gone": [g for g in gone_by_window["7d"]["gone"] if g["shelf"] == sid][:SHELF_GONE],
                        "generated_at": _iso(now), "attribution": ATTRIBUTION}
                  for sid, s in shelves.items()},
        "gone": gone_by_window,
        "almost": {"deals": almost([attach_sizes(p) for p in sorted(near or [], key=lambda p: (-p["delight"], -p["score"]))], now),
                   "generated_at": _iso(now), "attribution": ATTRIBUTION},
        "by_asin": by_asin, "gone_by_asin": gone_by_asin,
        "cards": cards, "sizes": size_facets(cards, now),  # D59: the sizes page filters `cards` per request
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


def create_site(snapshot: Snapshot, log_click: Callable[[dict], None], site_dir: Path, is_open: Callable[[], bool],
                log_view: Callable[[str, str], None] = lambda page, variant: None,
                log_open: Callable[[dict], None] = lambda row: None, alerts=None) -> FastAPI:
    """The beta site's app: /api/v1, /d/{slug} and the static export (web/out). Mounted per host by api.create_app,
    inside its gate middleware (the preview password applies until the beta opens). `alerts` (an alerts.Alerts)
    adds the keyword-alert routes (alerts-beta.md); without it they don't exist."""
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
              nofit: bool = False, sort: str = Query("newest", pattern="^(newest|mixed|discount|price-asc|price-desc|saved)$"),
              since: datetime | None = None, limit: int = Query(PAGE, ge=1, le=200), offset: int = Query(0, ge=0),
              q: str | None = Query(None, max_length=80), hide: str | None = Query(None, max_length=400)):
        s = snap()
        if not s:
            return unavailable()
        cond = [c for x in cond for c in x.split(",") if c]  # ?cond=like-new&cond=good or ?cond=like-new,good
        if not cond or any(c not in GRADES for c in cond):
            return JSONResponse({"error": f"cond: one or more of {', '.join(GRADES)}"}, status_code=422)
        if since and since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        only = {i for i, ix in enumerate(s["search"]) if matches(q, ix)} if q and q.strip() else None
        out = page_deals(s["deals"], s["built_at"], aisle, tuple(cond), price, nofit, sort, since, limit, offset,
                         frozenset(x for x in (hide or "").split(",") if x), only)
        if only is not None:  # D54: what matched and has gone, so an empty search still says something
            gone7 = s["gone"]["7d"]["gone"]
            out["gone"] = [g for g, ix in zip(gone7, s["gone_search"]) if matches(q, ix)][:SEARCH_GONE]
        return out

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

    @get("/almost")
    def almost_list():
        s = snap()
        return s["almost"] if s else unavailable()

    @get("/sizes")
    def size_picker():
        s = snap()
        return s["sizes"] if s else unavailable()

    @get("/sized")
    def sized(letter: str = Query("", max_length=200), num: str = Query("", max_length=200),
              waist: str = Query("", max_length=200), length: str = Query("", max_length=200),
              shoe: str = Query("", max_length=400), cond: list[str] = Query(list(DEFAULT_GRADES)),
              sort: str = Query("best", pattern="^(best|newest|discount|price-asc)$"),
              limit: int = Query(PAGE, ge=1, le=200), offset: int = Query(0, ge=0)):
        s = snap()
        if not s:
            return unavailable()
        cond = [c for x in cond for c in x.split(",") if c]
        if not cond or any(c not in GRADES for c in cond):
            return JSONResponse({"error": f"cond: one or more of {', '.join(GRADES)}"}, status_code=422)
        split = lambda x: {v.strip() for v in x.split(",") if v.strip()}  # noqa: E731
        prefs = {"letter": {v.upper() for v in split(letter)}, "num": split(num), "waist": split(waist),
                 "length": split(length), "shoe": {v.lower() for v in split(shoe)}}
        return sized_deals(s["cards"], s["built_at"], prefs, tuple(cond), sort, limit, offset)

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
        same, size = related(s, d or g)
        return {"deal": d, "gone": None if d else g, "same_shelf": same, "same_size": size, "attribution": ATTRIBUTION}

    @v1.post("/view")
    def view(background: BackgroundTasks, page: str = Query(..., max_length=10), v: str = Query("", max_length=2)):
        """A page view, counted per day, page and A/B arm. Nothing about the visitor is kept."""
        if page not in PAGES:
            return JSONResponse({"error": "page"}, status_code=422)
        background.add_task(_safe, log_view, page, v if v in VARIANTS else "")
        return Response(status_code=204)

    @v1.post("/open")
    def open_(background: BackgroundTasks, id: str = Query(..., max_length=10), s: str = Query("", max_length=10),
              v: str = Query("", max_length=2)):
        """D64: a deal page opened: which deal, from which surface, in which arm. Nothing about the visitor is kept."""
        asin = id.upper()
        if not ASIN.fullmatch(asin):
            return JSONResponse({"error": "id"}, status_code=422)
        background.add_task(_safe, log_open, {"asin": asin, "surface": s if s in SURFACES else None,
                                              "variant": v if v in VARIANTS else None})
        return Response(status_code=204)

    site.include_router(v1)
    if alerts is not None:
        from .alerts import router as alert_router
        for r in alert_router(alerts):
            site.include_router(r)

    def _safe(fn: Callable, *a) -> None:
        try:
            fn(*a)
        except Exception:  # noqa: BLE001 — a lost count never costs the visitor anything
            log.exception("page view insert failed")

    def record(row: dict) -> None:
        try:
            log_click(row)
        except Exception:  # noqa: BLE001 — a lost click row never costs the visitor their redirect
            log.exception("click insert failed")

    @site.api_route("/d/{slug_}", methods=["GET", "HEAD"])
    def out(slug_: str, request: Request, background: BackgroundTasks, s_: str | None = Query(None, alias="s", max_length=10),
            v: str | None = Query(None, max_length=2)):
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
                                     "live": live, "referer_path": urlsplit(ref).path[:200] if ref else None,
                                     "variant": v if v in VARIANTS else None})
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

    @site.get("/deal/{rest:path}")
    def deal_page(rest: str):
        """trust-first §4.2: the shared deal page. One exported page; the link preview (title, photo, a line of text) is
        written into its head here, from the snapshot, so a pasted link shows the deal."""
        f = site_dir / "deal" / "index.html"
        if not f.is_file():
            return Response("Not found", status_code=404)
        m = SLUG.match(rest.lower())
        s = snap()
        asin = m.group(1).upper() if m else None
        d = (s["by_asin"].get(asin) or s["gone_by_asin"].get(asin)) if s and asin else None
        doc = f.read_text()
        if d:
            gone = asin not in s["by_asin"]
            title = f"{d['pct_off']}% off: {d['title']}"[:140]
            line = (f"Gone. Last price ${d['price']:,.2f}, {d['condition']}." if gone else
                    f"${d['price']:,.2f}, {d['condition']}" + (f", usually ${d['usual_price']:,.2f}" if d.get("usual_price") else "")
                    + ". Amazon Resale, sold and shipped by Amazon.")
            e = lambda x: html.escape(x, quote=True)  # noqa: E731
            meta = (f'<meta property="og:title" content="{e(title)}"/><meta property="og:description" content="{e(line)}"/>'
                    f'<meta property="og:site_name" content="fiftyOff"/><meta property="og:type" content="product"/>'
                    + (f'<meta property="og:image" content="{e(d["image"])}"/>' if d.get("image") else "")
                    + '<meta name="twitter:card" content="summary_large_image"/>')
            doc = re.sub(r"<title>.*?</title>", f"<title>{e(title)} · fiftyOff</title>", doc, count=1)
            doc = doc.replace("</head>", meta + "</head>", 1)
        return Response(doc, media_type="text/html")

    site.mount("/", StaticFiles(directory=site_dir, html=True, check_dir=False), name="web")

    @site.middleware("http")
    async def cache_headers(request: Request, call_next):
        resp = await call_next(request)
        path = request.url.path
        rules = CACHE_OPEN if is_open() else CACHE_CLOSED
        if path.startswith("/d/") or resp.status_code >= 500 or no_store_path(path):  # alerts: never cached
            resp.headers["Cache-Control"] = "no-store"
        elif path.startswith("/api/v1/"):
            resp.headers["Cache-Control"] = rules["v1"]
        elif path.startswith("/_next/static/"):
            resp.headers["Cache-Control"] = rules["static"]
        else:
            resp.headers["Cache-Control"] = rules["html"]
        return resp

    return site
