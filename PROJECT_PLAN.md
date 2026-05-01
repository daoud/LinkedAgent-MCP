# LinkedIn Auto-Publisher — Project Development Plan

## Overview

Automated content-to-LinkedIn publishing pipeline.
Upload content → LLM transforms → Human approves → LinkedIn publishes.

**Stack:** LangGraph · FastAPI · Claude Sonnet 4 · PostgreSQL 16 · SQLAlchemy 2.0 · APScheduler · Google Sheets · Slack · Docker · Kubernetes · GitHub Actions

---

## Architecture

```
Content File
    │
    ▼
Storage (Local / S3)
    │
    ▼
PostgreSQL (metadata)
    │
    ▼
LangGraph Pipeline
    extract → dedup → sanitize → transform (LLM)
    → validate → schedule → approve → preview → publish → finalize
    │
    ▼
LinkedIn API
```

---

## Current State

| Layer | Status |
|-------|--------|
| Folder structure | Complete |
| File stubs | Created (all empty) |
| Implementation | Not started |
| Migrations | Not run |
| Tests | Not written |

---

## Phase 1: Foundation

**Goal:** Working local environment with database, config, and models.

| Task | File(s) | Description |
|------|---------|-------------|
| T-1.1 | `pyproject.toml`, `Makefile`, `.gitignore`, `.env.example` | Project scaffold, tooling, pre-commit hooks |
| T-1.2 | `docker-compose.yaml` | PostgreSQL 16 local dev container |
| T-1.3 | `src/config.py` | Pydantic Settings + env validation |
| T-1.4 | `src/models/*.py` | SQLAlchemy ORM — 6 tables: posts, content_uploads, approvals, prompt_templates, llm_costs, logs |
| T-1.5 | `migrations/versions/001_initial_schema.py` | Alembic migration + indexes + triggers |
| T-1.6 | `scripts/seed.py` | Default prompt template seed data |

**Gate:** `make up && make migrate && make seed && make test` all pass.

---

## Phase 2: Content Ingestion

**Goal:** Drop a file → DB record created → text extracted.

| Task | File(s) | Description |
|------|---------|-------------|
| T-2.1 | `src/ingestion/storage_client.py` | ABC + Local + S3 implementations |
| T-2.2 | `src/ingestion/content_extractor.py` | PDF / DOCX / MD / TXT extraction |
| T-2.3 | `src/ingestion/content_reader.py` | Unified read interface |
| T-2.4 | `src/ingestion/local_watcher.py` | Watchdog folder watcher → trigger endpoint |

**Gate:** Drop file in `test_content/` → DB record created → text extracted.

---

## Phase 3: LinkedIn Client

**Goal:** Authenticated LinkedIn API client with dry-run publish.

| Task | File(s) | Description |
|------|---------|-------------|
| T-3.1 | `src/linkedin/auth.py` | OAuth2 auth + first-time auth script |
| T-3.2 | `src/linkedin/client.py`, `src/linkedin/rate_limiter.py` | publish, upload_image, delete, profile + rate limiter |

**Gate:** `scripts/linkedin_first_auth.py` runs → dry_run publish succeeds.

---

## Phase 4: Intelligence Layer

**Goal:** Raw content → sanitized → LLM-transformed → validated LinkedIn post.

| Task | File(s) | Model | Description |
|------|---------|-------|-------------|
| T-4.1 | `src/intelligence/prompt_manager.py` | Sonnet | Load + render prompt templates from DB |
| T-4.2 | `src/intelligence/sanitizer.py` | **Opus** | Prompt injection defense + content cleaning |
| T-4.3 | `src/intelligence/transform.py` | **Opus** | LLM transform agent (Claude Anthropic SDK) |
| T-4.4 | `src/intelligence/validator.py`, `validation_rules.yaml` | Sonnet | Post validation engine + rules |
| T-4.5 | `src/intelligence/cost_tracker.py` | Sonnet | Track token usage + cost per run |

**Gate:** Sample markdown → sanitize → transform → validate → valid LinkedIn post.

---

## Phase 5: Scheduling + Deduplication

**Goal:** Posts assigned to correct time slots; duplicate content rejected.

| Task | File(s) | Description |
|------|---------|-------------|
| T-5.1 | `src/scheduling/scheduler.py` | Post scheduler with timezone support (AST slots) |
| T-5.2 | `src/scheduling/dedup.py` | Hash-based deduplication |

**Gate:** Scheduler assigns correct AST slots. Duplicate content detected.

---

## Phase 6: Approval Workflow

**Goal:** Post enters queue → Sheet updated → Slack notified → approve in Sheet → poller detects.

| Task | File(s) | Description |
|------|---------|-------------|
| T-6.1 | `src/approval/queue.py` | Approval queue manager |
| T-6.2 | `src/approval/poller.py` | Polls Google Sheets for approval decisions |
| T-6.3 | `src/approval/sheets_client.py` | Google Sheets read/write via gspread |
| T-6.4 | `src/approval/slack_notifier.py` | Slack webhook notifications |

**Gate:** Full approval cycle works end-to-end.

---

## Phase 7: LangGraph Orchestration

**Goal:** Full pipeline wired as a stateful LangGraph graph with PostgreSQL checkpointer.

| Task | File(s) | Model | Description |
|------|---------|-------|-------------|
| T-7.1 | `src/pipeline/state.py` | **Opus** | PipelineState TypedDict definition |
| T-7.2 | `src/pipeline/nodes/*.py` (10 nodes) | Sonnet | One node per pipeline step |
| T-7.3 | `src/pipeline/graph.py`, `src/pipeline/checkpointer.py` | **Opus** | StateGraph assembly + edges + PG checkpointer |
| T-7.4 | `tests/test_pipeline_e2e.py` | Sonnet | E2E local test: file → publish (dry_run) → finalize |

**Pipeline nodes:** extract → dedup → sanitize → transform → validate → schedule → approve → preview → publish → finalize

**Gate:** Full pipeline: file → transform → approve → publish(dry_run) → finalize.

---

## Phase 8: FastAPI Service

**Goal:** HTTP API for triggering and monitoring the pipeline.

| Task | File(s) | Description |
|------|---------|-------------|
| T-8.1 | `src/api/app.py`, `src/api/middleware.py` | FastAPI app + CORS + auth middleware |
| T-8.2 | `src/api/routes/pipeline.py` | POST /pipeline/trigger, POST /pipeline/retry, GET /pipeline/status, POST /pipeline/upload |
| T-8.3 | `src/api/routes/health.py` | GET /health, GET /metrics |
| T-8.4 | Background scheduler integration | APScheduler wired into FastAPI lifespan |

**Gate:** `POST /pipeline/trigger` invokes full pipeline. `GET /health` returns 200.

---

## Phase 9: Observability + Security

**Goal:** Production-grade logging, metrics, tracing, and secrets management.

| Task | File(s) | Model | Description |
|------|---------|-------|-------------|
| T-9.1 | `src/observability/logging.py` | Sonnet | Structured JSON logging with structlog |
| T-9.2 | `src/observability/metrics.py` | Sonnet | Prometheus metrics (pipeline runs, latency, errors) |
| T-9.3 | `src/observability/tracing.py` | Sonnet | OpenTelemetry distributed tracing |
| T-9.4 | `src/secrets.py` | **Opus** | Secrets abstraction (env / Secret Manager) |

**Gate:** JSON logs in stdout. `/metrics` endpoint works. Secrets load from env.

---

## Phase 10: Deployment

**Goal:** Production-ready Docker image, CI/CD pipeline, Kubernetes deployment.

| Task | File(s) | Description |
|------|---------|-------------|
| T-10.1 | `Dockerfile` | Multi-stage build, non-root user |
| T-10.2 | `.github/workflows/ci.yaml` | GitHub Actions: lint → test → build → push |
| T-10.3 | `k8s/` | Deployment, Service, ConfigMap, CronJob manifests |
| T-10.4 | `scripts/production_checklist.py` | Pre-deploy validation script |

**Gate:** Docker builds. CI passes. K8s manifests apply. Checklist green.

---

## Token Budget

| Phase | Opus | Sonnet | Est. Tokens |
|-------|------|--------|-------------|
| 1 — Foundation | 0 | 6 | ~30K |
| 2 — Ingestion | 0 | 4 | ~25K |
| 3 — LinkedIn | 0 | 2 | ~20K |
| 4 — Intelligence | 2 | 3 | ~40K |
| 5 — Scheduling | 0 | 2 | ~12K |
| 6 — Approval | 0 | 4 | ~25K |
| 7 — LangGraph | 2 | 2 | ~60K |
| 8 — FastAPI | 0 | 4 | ~25K |
| 9 — Observability | 1 | 3 | ~20K |
| 10 — Deployment | 0 | 4 | ~25K |
| **Total** | **5** | **34** | **~282K** |

---

## Development Rules

1. **One task per session.** Never combine tasks.
2. **Gate before advancing.** Every phase has a gate — pass it before starting the next phase.
3. **Opus only where marked.** Opus is 5× the cost of Sonnet.
4. **Commit after every phase gate.** Git commit = checkpoint.
5. **Test after every task.** A bug found in Phase 7 that originated in Phase 2 costs 10× more to fix.
6. **No Celery/Redis.** LangGraph checkpointer handles retries and state; no second orchestration layer.

---

## Quick Start

```bash
cp .env.example .env      # fill in credentials
make up                   # start PostgreSQL
make migrate              # run Alembic migrations
make seed                 # insert default prompt template
make dev                  # start FastAPI dev server
make test                 # run full test suite
```
