# Claude Coach

Personal hybrid training coach (musculação + corrida) that pulls Garmin data,
parses a PDF training plan via LLM-vision, lets you log workouts set-by-set,
and produces pre-workout briefings + weekly reports written by Claude/GPT.

> Built as a single-user app. There's only one password and no concept of
> tenants. If you want to use it yourself, fork it and deploy your own
> instance — nothing here is multi-tenant safe.

## Stack

- **Backend:** FastAPI, SQLAlchemy + Alembic, SQLite, APScheduler, structlog
- **Frontend:** Vite + React 18 + TS, Tailwind, TanStack Query/Router, Recharts
- **Integrations:** [`garth`](https://github.com/matin/garth) + `curl_cffi`
  (Garmin), Anthropic + OpenAI SDKs (LLM), Resend (email)
- **Persistence:** SQLite + YAML/Markdown files (plans, reports). DB and
  personal data live outside the repo.

Architecture decisions and roadmap: [`docs/architecture.md`](./docs/architecture.md).
Project guide for AI agents: [`CLAUDE.md`](./CLAUDE.md).

## Features

- PDF training plan parser (vision LLM)
- Garmin sync: sleep, HRV, body battery, stress, activities, weight, VO₂ max
- Set-by-set workout log with carry-over prefill + auto-match to Garmin
  activity
- Pre-workout briefing on demand (context-aware via Claude)
- Weekly report (auto-generated Mondays, optional email via Resend)
- Dashboard with intraday body battery curve, sleep/HRV trends, weekly volume

## Setup (local)

Prereqs: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+,
[pnpm](https://pnpm.io/).

```bash
cp .env.example .env       # fill in keys you have; rest can stay blank
make install
make migrate               # apply alembic migrations to data/metrics.db
make garmin-login          # interactive — needs Garmin email/password
make dev                   # backend :8000, frontend :5173
```

Open <http://localhost:5173>.

## Importing a plan

```bash
# Drop a PDF in the project root, then:
make parse pdf=./your-plan.pdf slug=my-plan
# Inspect data/plans/my-plan/REVIEW.md, accept suggestions, then it's active.
```

## Garmin backfill (optional)

```bash
cd backend && uv run python ../scripts/garmin_backfill.py \
  --start 2026-01-01 --end 2026-05-22
```

## Tests

```bash
make test     # pytest
make lint     # ruff + tsc
```

## What's *not* in the repo

Per `.gitignore`, the following stay strictly on your machine / your server:

- `.env` and any environment-specific overrides
- `data/profile.yaml` (your name, birthdate, etc)
- `data/plans/<your-plan>/` (your prescribed training)
- `data/reports/` (your weekly reports)
- `data/metrics.db` (Garmin time-series + workout log)
- `data/garmin_tokens/` (Garmin OAuth tokens)

The exercise catalog (`data/exercises/`) **is** committed — it's a generic
reference of common Portuguese-named exercises useful as a seed.

## Deploy

See [`docs/deploy-railway.md`](./docs/deploy-railway.md) for the Railway flow
(single container, persistent volume, env vars, custom domain).

## License

MIT — see [LICENSE](./LICENSE).
