# fiftyoff

Tools for finding genuinely ~50%-off **Amazon Resale** (formerly Warehouse) deals with the
[Keepa API](https://keepa.com/#!api) and measuring how long they last.

"50% off" on Amazon is often measured against an inflated list price. fiftyoff re-prices each
Resale offer against a **strict reference**: the lowest of Amazon's price, the New price and their
48 h / 30 d / 90 d averages. A deal only counts if it's still half off by that measure.

## What's here

| Script | What it does |
|---|---|
| `preflight.py` | Budget-capped feasibility probe: deal-feed census, history samples, offline report |
| `track1.py` | How often popular $100+ products have a Resale offer, and how deep the discount goes |
| `collector.py` | Forward collector: sweeps the deal feed every 30 min and re-checks a watchlist to time how long each Resale unit lasts |
| `tracker.py` | New-deal tracker: incremental deal-feed sweeps, priority live checks, unit lifespans with lower/upper bounds and HIGH/MEDIUM/LOW confidence, state in Postgres |
| `fiftyoff/api.py` | Read-only deal feed API and preview page (FastAPI), served through a database role that can only read the feed |
| `fiftyoff/` | Keepa client (raw response saved before parsing, token ledger, hard token caps), strict-discount and episode analysis |

How the tracker decides a unit is gone: Amazon often hides a Resale unit for a while and then shows
it again (the same offer, back within minutes to hours). So a missing unit is first *unconfirmed*,
counts as *gone* only after 6 hours of continuous absence, and is *revived* if it comes back. Every
lifespan is reported as a range, never a single precise time.

Design rules the code enforces:
- Paid Keepa calls happen only from an explicit command, after a printed token estimate and a `[y/N]` prompt.
- Every command has a free `--dry-run`.
- Token caps live in `preflight.toml`, and every call is recorded in a ledger.
- Tests use synthetic fixtures. A socket guard fails any test that touches the network.
- Discount formulas are versioned, so results can be replayed from saved raw responses.

## Run it

You need your own Keepa API key ([plans](https://keepa.com/#!api); the base plan is 20 tokens/min).

```bash
cp .env.example .env          # add KEEPA_API_KEY
```

**With Docker** (OrbStack or Docker Desktop):

```bash
docker compose up -d                                    # Postgres 17 (localhost only)
docker compose run --rm app                             # tests, offline
docker compose run --rm app collector.py run --dry-run  # plan and token rate, no requests
docker compose run --rm app tracker.py unlock           # approve a tracker run: token cap + expiry, [y/N]
docker compose --profile tracker up -d tracker          # long-running tracker
docker compose up -d api                                # feed API + preview on 127.0.0.1:8000
```

**Or with [uv](https://docs.astral.sh/uv/):**

```bash
uv sync
uv run pytest
uv run preflight.py --fixtures tests/fixtures/keepa probe   # free rehearsal against fixtures
```

`collector.py run` refuses to start until you run `collector.py unlock`, which records your
approval locally.

## Data

No Keepa data is included. Keepa's terms allow API data to be used only for your own internal
purposes. Outputs go to `research/`, which is gitignored. Don't publish them.

## Status

This is a research prototype from a hackathon project: CLI scripts and analysis code, not a hosted
service.

## License

MIT for the code. Keepa data you collect with it stays under Keepa's terms.
