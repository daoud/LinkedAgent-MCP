# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Environment
cp .env.example .env          # first-time setup
make up                        # start PostgreSQL 16 on port 5433
make migrate                   # run Alembic migrations
make seed                      # insert default prompt template

# Development
make dev                       # FastAPI dev server on :8000 (uvicorn --reload)

# Testing
make test                      # unit tests only (tests/unit/)
make test-all                  # all tests including integration and e2e
source venv/bin/activate && python -m pytest tests/unit/test_scheduler.py -v   # single test file
source venv/bin/activate && python -m pytest tests/unit/test_scheduler.py::test_first_slot_when_day_empty -v  # single test

# Code quality
make lint                      # ruff check
make format                    # black + ruff --fix

# LinkedIn first-time auth
source venv/bin/activate && python scripts/linkedin_first_auth.py
```

PostgreSQL runs on **port 5433** (not 5432) to avoid conflicts with local installs.

## Architecture

### Pipeline data flow

```
Content File → Storage → ContentReader → LangGraph Pipeline → LinkedIn API
                    ↕ PostgreSQL metadata at every step
```

The LangGraph pipeline (`src/pipeline/graph.py`) wires 11 nodes:
`extract → dedup → sanitize → transform → validate → schedule → [approve] → wait_for_slot → preview → publish → finalize`

`schedule` routes conditionally to `approve` or straight to `wait_for_slot` depending on the live `require_approval` flag (see Scheduling below); `approve` then routes to `wait_for_slot` or `finalize` (on reject/timeout). `wait_for_slot` interrupts the graph until the assigned slot time arrives, then resumes into `preview`.

Each node lives in `src/pipeline/nodes/<name>.py` and receives/returns a `PipelineState` TypedDict (`src/pipeline/state.py`). The graph uses a PostgreSQL checkpointer (`src/pipeline/checkpointer.py`) for resumability — no Celery/Redis. `src/pipeline/resume.py` resumes an interrupted thread from either the manual `/pipeline/approve` route or the Sheets approval poller — it opens its **own** `AsyncSessionLocal` (separate from the route's), which matters when mocking DB access in tests that exercise the approve endpoint end-to-end.

### Settings singleton

`src/config.py` exports `get_settings()` (LRU-cached). All modules take `Settings` as a constructor argument; call `get_settings()` only at the entry point. The `post_slots_list` and `async_database_url` properties do derived computation from raw env vars.

### Async DB pattern

`src/database.py` creates a module-level `AsyncEngine` + `AsyncSessionLocal`. All service classes accept `AsyncSession` in their constructor (e.g., `CostTracker(session)`, `PromptManager(session)`). Important: `await session.execute(...)` returns a **synchronous** result object — `result.fetchall()` and `result.scalar_one_or_none()` are called without `await`.

When mocking in tests, use `AsyncMock` for `session` and `session.execute`, but use `MagicMock` for the returned result object so `.fetchall()` / `.scalar_one_or_none()` stay synchronous.

### Intelligence layer

`src/intelligence/` contains four stateless service classes used by the transform/validate pipeline nodes:
- `Sanitizer` — prompt-injection defense + content cleaning (uses Claude API for LLM-based check)
- `Transformer` — converts raw content to LinkedIn post via Claude API
- `Validator` — rule-based checks (char count, hashtags, URLs) + optional LLM tone review; rules loaded from `src/intelligence/validation_rules.yaml`
- `CostTracker` — records token usage to `llm_costs` table; enforces `LLM_MONTHLY_BUDGET`
- `PromptManager` — loads/renders `PromptTemplate` rows from DB with `{variable}` substitution

### LinkedIn client

`src/linkedin/auth.py` (`LinkedInAuth`) handles OAuth2 token storage and auto-refresh. `src/linkedin/client.py` (`LinkedInClient`) wraps the UGC API — all mutating methods accept `dry_run=True` (default) which validates the payload without hitting the API. `src/linkedin/rate_limiter.py` enforces per-day/per-hour caps via an in-memory sliding window.

### Scheduling + dedup

`src/scheduling/scheduler.py` (`PostScheduler`) assigns posts to the next free `(date, time)` slot, respects the daily post limit, and rolls over to the next day when full. Slots are stored as naive local times in the configured `TIMEZONE`. `src/scheduling/dedup.py` computes SHA-256 hashes of content and checks the `post_hash` unique column on the `posts` table.

Scheduling is runtime-configurable, not just env-driven: `src/scheduling/config.py` backs a single `ScheduleConfig` DB row (slots, daily limit, active weekdays/date range, `auto_publish`, `require_approval`, `enabled`) editable from the dashboard's Schedule tab. It seeds its defaults from `Settings` on first read, then `cached()` serves the last-loaded values without a DB round-trip for hot-path routing (e.g. the graph's `schedule`/`approve` conditional edges) — a background poll refreshes the cache, and every dashboard write refreshes it immediately.

### Storage + content sources

`src/ingestion/storage_client.py` defines an ABC (`StorageClient`) with `LocalStorageClient` and `S3StorageClient` implementations. `ContentReader` (`src/ingestion/content_reader.py`) composes storage + extractor into a single `read(path) → str` interface. Drop files into `test_content/` when `STORAGE_MODE=local`.

Beyond the local folder watcher (`src/ingestion/local_watcher.py`, watchdog-based), `src/ingestion/gdrive_source.py` (`GDriveSource`) polls a Google Drive folder for new files, reusing the Sheets integration's service-account credentials with an added read-only Drive scope; `src/ingestion/source_poller.py` drives configured sources (tracked in the `content_sources` table) on an interval. Each Drive file is imported once, keyed by `content_uploads.external_id`.

### Dashboard UI

`src/api/routes/ui.py` serves the static dashboard SPA; `src/api/routes/dashboard.py` (prefix `/api`) is its backing REST API — compose, post/approval CRUD, retry/publish/delete-from-LinkedIn actions, prompt templates, live logs, ops actions, and the Schedule tab's `/schedule`, `/schedule/queue`, `/sources*` endpoints. See `RUNBOOK.md` for the end-to-end walkthrough.

### Database models (8 tables)

`posts`, `content_uploads`, `approvals`, `prompt_templates`, `llm_costs`, `logs`, `content_sources`, `schedule_config` — all defined in `src/models/`. `Base` is in `src/models/base.py`. Alembic config is in `alembic.ini`; migrations live in `migrations/versions/` (currently 3 revisions — schema, post media/source columns, schedule config + sources).

## Phase completion status

| Phase | Status |
|-------|--------|
| 1 — Foundation (DB, config, models, migrations) | ✅ complete |
| 2 — Content Ingestion (storage, extractor, watcher) | ✅ complete |
| 3 — LinkedIn Client (auth, client, rate limiter) | ✅ complete |
| 4 — Intelligence Layer (sanitizer, transformer, validator, cost tracker, prompt manager) | ✅ complete |
| 5 — Scheduling + Dedup | ✅ complete |
| 6 — Approval Workflow (queue, poller, Sheets, Slack) | ✅ complete |
| 7 — LangGraph Orchestration (state, nodes, graph) | ✅ complete |
| 8 — FastAPI Service | ✅ complete |
| 9 — Observability + Security | ✅ complete |
| 10 — Deployment (Dockerfile, CI, K8s) | ✅ complete |

Development order is strict — complete each phase gate before starting the next. See `PROJECT_PLAN.md` for full task breakdown and `TASKS.md` for token budget rules.

Post-Phase-10 additions (not in the original 28-task plan, built on top of the completed pipeline): the dashboard UI, the runtime-configurable scheduling engine (`ScheduleConfig`), the Google Drive content source, and the `wait_for_slot` graph node — see the sections above.
