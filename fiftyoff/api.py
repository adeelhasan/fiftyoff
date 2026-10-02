"""Read-only deal API + closed preview page.

Serves only the Keepa-consented fields (D19) from the `feed` view: title, Amazon link, our % off,
condition, current Resale price, plus our own "last confirmed" time. Every response carries the
required "Data by Keepa" attribution. Connects as a role that can read the feed view and nothing else.

    uvicorn fiftyoff.api:app      # FEED_DATABASE_URL points at the read-only role
"""

from __future__ import annotations

import base64
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, Response

ATTRIBUTION = {"text": "Data by Keepa", "url": "https://keepa.com"}
PREVIEW = Path(__file__).parent / "preview.html"
SORTS = {
    "newest": "last_confirmed_at DESC",
    "discount": "pct_off DESC, last_confirmed_at DESC",
    "price": "resale_cents ASC",
}


def pg_rows(category: str | None, sort: str, limit: int) -> list[dict]:
    import psycopg
    from psycopg.rows import dict_row

    sql = ("SELECT asin, title, category, cond, resale_cents, pct_off, last_confirmed_at, unconfirmed, url "
           "FROM feed WHERE (%(cat)s::text IS NULL OR category = %(cat)s) "
           f"ORDER BY {SORTS[sort]} LIMIT %(limit)s")
    with psycopg.connect(os.environ["FEED_DATABASE_URL"], row_factory=dict_row) as conn:
        return conn.execute(sql, {"cat": category, "limit": limit}).fetchall()


CACHE_SECONDS = 30  # however much traffic arrives, the database sees at most one query per filter per 30 s


def create_app(fetch: Callable[[str | None, str, int], list[dict]] = pg_rows,
               password: str | None = None, user: str = "fiftyoff") -> FastAPI:
    """`password` (default: PREVIEW_PASSWORD env) turns on a browser login popup (HTTP Basic Auth) for
    everything except /api/health. Only safe behind HTTPS, which the Cloudflare tunnel provides."""
    app = FastAPI(title="fiftyoff", docs_url=None, redoc_url=None)
    password = password if password is not None else os.environ.get("PREVIEW_PASSWORD") or None
    expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode() if password else None
    cache: dict[tuple, tuple[float, list[dict]]] = {}

    @app.middleware("http")
    async def gate(request: Request, call_next):
        if expected and request.url.path != "/api/health" \
                and not secrets.compare_digest(request.headers.get("authorization", ""), expected):
            return Response("Login required", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="fiftyoff preview"'})
        resp = await call_next(request)
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp

    def cached(category, sort, limit):
        key = (category, sort, limit)
        hit = cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        rows = fetch(category, sort, limit)
        cache[key] = (time.monotonic(), rows)
        return rows

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/feed")
    def feed(category: str | None = None, sort: str = Query("newest", pattern="^(newest|discount|price)$"),
             limit: int = Query(100, ge=1, le=500)):
        now = datetime.now(timezone.utc)
        deals = []
        for r in cached(category, sort, limit):
            seen = r["last_confirmed_at"]
            deals.append({
                "asin": r["asin"], "title": r["title"], "category": r["category"], "condition": r["cond"],
                "price": r["resale_cents"] / 100, "pct_off": int(r["pct_off"]), "url": r["url"],
                "last_confirmed_at": seen.isoformat(), "minutes_since_confirmed": int((now - seen).total_seconds() // 60),
                "unconfirmed": r["unconfirmed"],
            })
        return {"deals": deals, "count": len(deals), "attribution": ATTRIBUTION, "generated_at": now.isoformat()}

    @app.get("/", response_class=HTMLResponse)
    @app.get("/closed-preview", response_class=HTMLResponse)
    def preview():
        return PREVIEW.read_text()

    return app


app = create_app()
