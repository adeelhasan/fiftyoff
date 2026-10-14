"""The API rater (2026-10-12; D42/D50's `api` backend): rates new products with the Anthropic API so the shelves
and alerts don't wait for the user's Mac.

Same candidates, rubric and validator as scripts/rate_local.py (fiftyoff/appeal.py). Ratings are stored as model
"sonnet" with rated_by = 'api', because the feed reads APPEAL_MODEL = "sonnet"; the exact model id, the tokens and the
cost of every call go to `rater_batch`. Spend stops at the monthly cap in preflight.toml [rater]. The model client is
passed in (`call`), so this module never imports it and the tests never reach the network. Rule 7: the tracker never
imports this module; no price, discount or availability is decided here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from .appeal import CANDIDATES_SQL, RUBRIC, parse_lines, products_block, rubric_version, upsert_rows

MODEL = "sonnet"     # appeal.model: the name the feed reads (fiftyoff/api.py APPEAL_MODEL), whichever backend rated
RATED_BY = "api"


@dataclass(frozen=True)
class RaterConfig:
    model_id: str = "claude-sonnet-5-5"
    effort: str = "low"
    batch: int = 60
    max_tokens: int = 16000
    interval_minutes: float = 15
    max_batches: int = 8
    monthly_usd_cap: float = 25.0
    price_input: float = 2.00
    price_output: float = 10.00
    price_cache_read: float = 0.20
    price_cache_write: float = 4.00  # the 1-hour TTL's write price (2x input; 5-minute writes are 1.25x)

    @classmethod
    def from_toml(cls, t: dict) -> "RaterConfig":
        return cls(**{k: v for k, v in t.items() if k in cls.__dataclass_fields__})


@dataclass
class Reply:
    """What one model call returned: the text, why it stopped, the request id and the token counts."""
    text: str
    stop_reason: str | None
    request_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


# call(system, user, cfg) -> Reply. Raises on API errors; the loop logs them and tries again next round.
Call = Callable[[str, str, RaterConfig], Reply]


class RaterStore(Protocol):
    def candidates(self, limit: int) -> list[list[str]]: ...  # [key, title, brand, category path]
    def rated_sample(self, limit: int, rated_by: str) -> list[list]: ...  # the same + [score, shelf] as rated
    def save(self, rows: list[tuple], prompt_v: str) -> int: ...
    def record(self, batch: dict) -> None: ...
    def spent_since(self, since: datetime) -> float: ...


def cost(r: Reply, cfg: RaterConfig) -> float:
    return round((r.input_tokens * cfg.price_input + r.output_tokens * cfg.price_output
                  + r.cache_read_tokens * cfg.price_cache_read + r.cache_write_tokens * cfg.price_cache_write) / 1e6, 4)


def month_start(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def batch(store: RaterStore, call: Call, cfg: RaterConfig, now: datetime, log: Callable[[str], None] = print,
          dry: bool = False) -> int:
    """One call for up to cfg.batch products. Returns how many were sent (0: nothing to rate, or the cap is reached)."""
    spent = store.spent_since(month_start(now))
    if spent >= cfg.monthly_usd_cap:
        log(f"monthly cap reached: ${spent:.2f} of ${cfg.monthly_usd_cap:.2f}; not calling")
        return 0
    rows = store.candidates(cfg.batch)
    if not rows:
        if dry:
            log(f"dry run: nothing to rate; ${spent:.2f} spent this month")
        return 0
    if dry:
        log(f"dry run: would rate {len(rows)} products with {cfg.model_id} (effort {cfg.effort}); ${spent:.2f} spent this month")
        return 0
    v = rubric_version()
    sent = {r[0] for r in rows}
    rec = {"at": now, "model_id": cfg.model_id, "prompt_v": v, "effort": cfg.effort, "sent": len(rows), "loaded": 0,
           "bad": 0, "stop_reason": None, "request_id": None, "input_tokens": 0, "output_tokens": 0,
           "cache_read_tokens": 0, "cache_write_tokens": 0, "usd": 0.0, "error": None}
    try:
        reply = call(RUBRIC.read_text(), products_block(["\t".join(r) for r in rows]), cfg)
    except Exception as e:  # noqa: BLE001 — log it, record it, try again next round
        rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        store.record(rec)
        log(f"call failed: {rec['error']}")
        return len(rows)
    rec.update(stop_reason=reply.stop_reason, request_id=reply.request_id, input_tokens=reply.input_tokens,
               output_tokens=reply.output_tokens, cache_read_tokens=reply.cache_read_tokens,
               cache_write_tokens=reply.cache_write_tokens, usd=cost(reply, cfg))
    if reply.stop_reason != "end_turn":  # cut off or refused: load nothing, the next round picks them up again
        rec["error"] = f"stop_reason {reply.stop_reason}"
        store.record(rec)
        log(f"{len(rows)} sent, none loaded: stop_reason {reply.stop_reason} (${rec['usd']:.4f})")
        return len(rows)
    got = [ln for ln in reply.text.splitlines() if ln.split("\t")[0].strip() in sent]
    good, bad = parse_lines(got, v, cfg.model_id)
    rec["bad"] = len(sent - {g[0] for g in good})  # rejected by the validator, or missing from the reply
    if good:
        rec["loaded"] = store.save(good, v)
    store.record(rec)
    log(f"{len(rows)} sent, {rec['loaded']} loaded ({v}), {rec['bad']} bad or missing, "
        f"tokens in {reply.input_tokens} / cached {reply.cache_read_tokens} / out {reply.output_tokens}, ${rec['usd']:.4f}")
    for b in bad[:3]:
        log(f"  bad: {b}")
    return len(rows)


def round_(store: RaterStore, call: Call, cfg: RaterConfig, log: Callable[[str], None] = print, dry: bool = False,
           clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> int:
    """Batches until one isn't full (or max_batches). Returns how many products were sent."""
    total = 0
    for _ in range(cfg.max_batches):
        n = batch(store, call, cfg, clock(), log, dry)
        total += n
        if n < cfg.batch:
            break
    return total


def band(score: int) -> str:
    return "0-2" if score <= 2 else "3-6" if score <= 6 else "7+"


def compare(store: RaterStore, call: Call, cfg: RaterConfig, now: datetime, n: int = 100, rated_by: str = "local",
            log: Callable[[str], None] = print) -> dict:
    """The supervised check: re-rate up to n products another backend rated (newest first), save nothing, and
    report agreement on the score band (0-2 / 3-6 / 7+), the exact score and the shelf. The calls are recorded
    in rater_batch, so they count toward the monthly cap."""
    sample = store.rated_sample(n, rated_by)
    old = {r[0]: (int(r[4]), r[5]) for r in sample}
    v = rubric_version()
    new: dict[str, tuple] = {}
    for i in range(0, len(sample), cfg.batch):
        rows = [r[:4] for r in sample[i:i + cfg.batch]]
        reply = call(RUBRIC.read_text(), products_block(["\t".join(r) for r in rows]), cfg)
        sent = {r[0] for r in rows}
        good, _ = parse_lines([ln for ln in reply.text.splitlines() if ln.split("\t")[0].strip() in sent], v, "compare")
        new.update({g[0]: g for g in good})
        store.record({"at": now, "model_id": cfg.model_id, "prompt_v": v, "effort": cfg.effort, "sent": len(rows),
                      "loaded": 0, "bad": len(sent - {g[0] for g in good}), "stop_reason": reply.stop_reason,
                      "request_id": reply.request_id, "input_tokens": reply.input_tokens,
                      "output_tokens": reply.output_tokens, "cache_read_tokens": reply.cache_read_tokens,
                      "cache_write_tokens": reply.cache_write_tokens, "usd": cost(reply, cfg), "error": "compare"})
    both = [k for k in old if k in new]
    out = {"sampled": len(sample), "compared": len(both),
           "band_agree": sum(band(old[k][0]) == band(new[k][1]) for k in both),
           "score_exact": sum(old[k][0] == new[k][1] for k in both),
           "score_within_1": sum(abs(old[k][0] - new[k][1]) <= 1 for k in both),
           "shelf_agree": sum(old[k][1] == new[k][7] for k in both),
           "mean_shift": round(sum(new[k][1] - old[k][0] for k in both) / len(both), 2) if both else None}
    log(f"compared {out['compared']} of {out['sampled']}: band {out['band_agree']}, exact {out['score_exact']}, "
        f"within 1 {out['score_within_1']}, shelf {out['shelf_agree']}, mean shift {out['mean_shift']} (api minus {rated_by})")
    return out


# The candidates query, turned around: products already rated by a given backend, newest rating first.
_RATED = ("WHERE NOT EXISTS (SELECT 1 FROM appeal a WHERE a.key IN (k.key, k.asin) AND a.model = 'sonnet')\n"
          "ORDER BY k.pri, k.priced_at DESC NULLS LAST LIMIT {limit}")
assert _RATED in CANDIDATES_SQL
# %% because psycopg reads % (the "50%+" in the query's comments) as a placeholder once there are parameters.
SAMPLE_SQL = (CANDIDATES_SQL.replace("%", "%%")
              .replace(_RATED, "JOIN appeal a ON a.key = k.key AND a.model = 'sonnet' AND a.rated_by = %s\n"
                               "ORDER BY a.rated_at DESC LIMIT {limit}")
              .replace("FROM k LEFT JOIN product p", ", a.score, a.shelf\nFROM k LEFT JOIN product p"))


class PgRaterStore:
    """The rater's database side, as the `fiftyoff` user (it writes `appeal` and `rater_batch`)."""

    def __init__(self, conn):
        self.conn = conn

    def candidates(self, limit: int) -> list[list[str]]:
        return [list(r) for r in self.conn.execute(CANDIDATES_SQL.format(limit=int(limit))).fetchall()]

    def rated_sample(self, limit: int, rated_by: str) -> list[list]:
        return [list(r) for r in self.conn.execute(SAMPLE_SQL.format(limit=int(limit)), (rated_by,)).fetchall()]

    def save(self, rows: list[tuple], prompt_v: str) -> int:
        return upsert_rows(self.conn, MODEL, prompt_v, rows, RATED_BY)

    def record(self, b: dict) -> None:
        cols = list(b)
        self.conn.execute(f"INSERT INTO rater_batch ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                          [b[c] for c in cols])

    def spent_since(self, since: datetime) -> float:
        row = self.conn.execute("SELECT coalesce(sum(usd), 0) FROM rater_batch WHERE at >= %s", (since,)).fetchone()
        return float(row[0])
