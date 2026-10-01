"""Keepa API access for the pre-flight.

Every call goes: budget check -> request -> raw response saved to disk -> token ledger entry.
Raw is written before the caller sees (and parses) anything, per CLAUDE.md rule 4.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

API_BASE = "https://api.keepa.com"
DOMAIN_US = 1

# Keepa Time: minutes since 2011-01-01. unix_seconds = (keepa_minutes + OFFSET) * 60
KEEPA_TIME_OFFSET = 21564000

# csv history indexes (product object docs). Deal-object price arrays use the same indexing.
AMAZON = 0
NEW = 1
USED = 2
WAREHOUSE = 9
EXTRA_INFO_UPDATES = 15

CONDITIONS = {
    0: "Unknown",
    1: "New",
    2: "Used - Like New",
    3: "Used - Very Good",
    4: "Used - Good",
    5: "Used - Acceptable",
}

DEAL_PAGE_SIZE = 150
DEAL_PAGE_COST = 5
DEAL_MAX_RESULTS = 10_000
OFFER_PAGE_COST = 6  # per found offer page (10 offers), replaces the 1-token base cost


def keepa_to_unix(t: int) -> int:
    return (t + KEEPA_TIME_OFFSET) * 60


def unix_to_keepa(seconds: float) -> int:
    return int(seconds // 60) - KEEPA_TIME_OFFSET


def keepa_to_iso(t: int | None) -> str:
    if t is None or t <= 0:
        return "—"
    return datetime.fromtimestamp(keepa_to_unix(t), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def decode_csv(arr: list[int] | None) -> list[tuple[int, int]]:
    """Decode a `time, value` csv history into [(keepa_minutes, value)]. -1 = no offer."""
    if not arr:
        return []
    return [(arr[i], arr[i + 1]) for i in range(0, len(arr) - 1, 2)]


def decode_offer_csv(arr: list[int] | None) -> list[tuple[int, int, int]]:
    """Decode an offerCSV `time, price, shipping` history. Price -2 = undetermined."""
    if not arr:
        return []
    return [(arr[i], arr[i + 1], arr[i + 2]) for i in range(0, len(arr) - 2, 3)]


def history_offer_cost(n_asins: int, offers: int, historical_variations: bool = True) -> int:
    """Worst-case token cost of a product request with the offers parameter."""
    per = math.ceil(offers / 10) * OFFER_PAGE_COST + (1 if historical_variations else 0)
    return n_asins * per


class KeepaError(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class Transport(Protocol):
    def request(
        self, endpoint: str, params: dict[str, Any], body: dict | None
    ) -> tuple[int, dict]: ...


class LiveTransport:
    """The only code path that talks to api.keepa.com."""

    def __init__(self, api_key: str, timeout: float = 180):
        import requests

        if not api_key:
            raise KeepaError("KEEPA_API_KEY is not set (see .env.example)")
        self._key = api_key
        self._timeout = timeout
        self._session = requests.Session()

    def request(self, endpoint, params, body, retries: int = 5):
        import requests

        url = f"{API_BASE}/{endpoint}"
        q = {"key": self._key, **params}
        for attempt in range(retries):
            try:
                if body is not None:
                    r = self._session.post(url, params=q, json=body, timeout=self._timeout)
                else:
                    r = self._session.get(url, params=q, timeout=self._timeout)
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                # Dropped connections happen on long runs; back off and retry the same request.
                if attempt == retries - 1:
                    raise
                wait = 15 * 2 ** attempt
                print(f"  network error ({type(e).__name__}); retrying in {wait}s")
                time.sleep(wait)
        try:
            data = r.json()
        except ValueError:
            data = {"error": {"type": "non-json", "message": r.text[:500]}}
        return r.status_code, data


class FixtureTransport:
    """Serves saved JSON instead of calling Keepa. Used by tests and `--fixtures`.

    Looks up `<dir>/<endpoint>[-<key>].json`, where key is the deal page / category or 'probe'.
    """

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.calls: list[tuple[str, dict, dict | None]] = []

    def request(self, endpoint, params, body):
        self.calls.append((endpoint, params, body))
        if endpoint == "deal":
            cats = body.get("includeCategories") or []
            key = f"deal-cat{cats[0]}-p{body['page']}" if cats else f"deal-p{body['page']}"
        elif endpoint == "product" and params.get("update") == -1:
            key = "probe"
        elif endpoint == "product":
            key = f"product-{params['asin']}"
        else:
            key = endpoint
        path = self.dir / f"{key}.json"
        if not path.exists():
            # Mirrors an empty deal page so paging terminates.
            return 200, {"tokensConsumed": 0, "tokensLeft": 1200, "refillRate": 20,
                         "deals": {"dr": [], "categoryIds": [], "categoryNames": [], "categoryCount": []}}
        return 200, json.loads(path.read_text())


class Ledger:
    """Append-only JSONL record of every Keepa call and its actual token usage."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def spent(self) -> int:
        return sum(e.get("tokensConsumed") or 0 for e in self.entries())

    def record(self, entry: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")


class Keepa:
    def __init__(self, transport: Transport, ledger: Ledger, raw_dir: Path, token_cap: int,
                 sleep=time.sleep):
        self.transport = transport
        self.ledger = ledger
        self.raw_dir = Path(raw_dir)
        self.token_cap = token_cap
        self.tokens_left: int | None = None
        self.refill_rate: int | None = None
        self._sleep = sleep
        self._seq = 0

    def remaining_budget(self) -> int:
        return self.token_cap - self.ledger.spent()

    def call(self, endpoint: str, *, label: str, estimate: int, params: dict | None = None,
             body: dict | None = None) -> dict:
        params = params or {}
        if estimate > self.remaining_budget():
            raise BudgetExceeded(
                f"{label}: estimated {estimate} tokens but only {self.remaining_budget()} left "
                f"of the pre-flight cap ({self.token_cap}). Raise budget.token_cap in "
                f"preflight.toml deliberately if you want to continue."
            )
        self._wait_for_tokens(estimate)

        sent_at = datetime.now(timezone.utc).isoformat()
        status, data = self.transport.request(endpoint, params, body)

        # Raw first — before anything inspects the payload.
        self._seq += 1
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = self.raw_dir / f"{self._seq:03d}-{label}.json"
        raw_path.write_text(json.dumps({
            "request": {"endpoint": endpoint, "params": params, "body": body, "sentAt": sent_at},
            "status": status,
            "response": data,
        }))

        self.tokens_left = data.get("tokensLeft", self.tokens_left)
        self.refill_rate = data.get("refillRate", self.refill_rate)
        self.ledger.record({
            "at": sent_at,
            "label": label,
            "endpoint": endpoint,
            "estimate": estimate,
            "tokensConsumed": data.get("tokensConsumed"),
            "tokensLeft": data.get("tokensLeft"),
            "refillRate": data.get("refillRate"),
            "status": status,
            "raw": str(raw_path),
        })
        if status != 200:
            raise KeepaError(f"{label}: HTTP {status}: {data.get('error')}")
        return data

    def _wait_for_tokens(self, needed: int) -> None:
        # Keepa executes any request while the balance is positive and lets it go negative;
        # we wait instead so a burst never digs a hole.
        if self.tokens_left is None or self.tokens_left >= needed or not self.refill_rate:
            return
        minutes = math.ceil((needed - self.tokens_left) / self.refill_rate)
        print(f"  waiting ~{minutes} min for tokens to refill ({self.tokens_left} left, need {needed})")
        self._sleep(minutes * 60 + 5)
        self.tokens_left = needed


def load_api_key(env_path: Path = Path(".env")) -> str:
    key = os.environ.get("KEEPA_API_KEY", "")
    if not key and env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("KEEPA_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key
