# fiftyoff

Research spike: is there a big enough, measurable pool of genuinely ~50%-off Amazon Resale
inventory, and can Keepa discover it and reconstruct its history?

- Plan: [`docs/fiftyoff_research_plan_v0.4.md`](docs/fiftyoff_research_plan_v0.4.md)
- Agent rules / gate: [`CLAUDE.md`](CLAUDE.md)
- Pre-registered decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- Output: `research/preflight-report.md` → GO / PARTIAL GO / STOP

## Setup

```bash
cp .env.example .env   # add KEEPA_API_KEY
uv sync
```

Run it with the steps in [`docs/PREFLIGHT.md`](docs/PREFLIGHT.md). The pre-flight never runs automatically. It is triggered manually and asks for confirmation
before spending Keepa tokens.
