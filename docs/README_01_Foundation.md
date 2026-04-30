# Phase 1: Foundation & Environment Setup

## Prerequisites
- Python 3.12+
- Docker Desktop
- Git
- `uv` package manager (`pip install uv`)

## Tasks

### T-1.1: Project Scaffold
**Claude: Sonnet | Tokens: Low**

Create:
- `pyproject.toml` with all dependencies
- `.gitignore` (Python + Docker + env)
- `.pre-commit-config.yaml` (ruff, black, mypy)
- `Makefile` with commands: up, down, migrate, seed, dev, test, lint, format
- `.env.example` with all env vars from architecture doc
- `src/__init__.py`

Prompt strategy: Single prompt, provide folder structure + dependency list.

### T-1.2: Docker Compose (Local Dev)
**Claude: Sonnet | Tokens: Low**

Create `docker-compose.yaml`:
- PostgreSQL 16 (port 5432, volume for persistence)
- Health check on PG
- No Redis, no Celery

Test: `docker compose up -d && docker compose ps` shows healthy.

### T-1.3: Config Loader
**Claude: Sonnet | Tokens: Low**

Create `src/config.py`:
- Pydantic `Settings` class loading from `.env`
- Validation: STORAGE_MODE must be local|s3|gcs
- Validation: TIMEZONE must be valid pytz timezone
- Validation: POST_SLOTS parsed into list of time objects
- Singleton pattern for app-wide access

Files: `src/config.py`, `tests/unit/test_config.py`

### T-1.4: Database Setup
**Claude: Sonnet | Tokens: Medium**

Create `src/database.py`:
- SQLAlchemy 2.0 async engine + sessionmaker
- Connection pool configuration
- `get_db()` dependency for FastAPI

Create all SQLAlchemy models:
- `src/models/__init__.py` (exports all models)
- `src/models/content_upload.py`
- `src/models/post.py`
- `src/models/approval.py`
- `src/models/log.py`
- `src/models/prompt_template.py`
- `src/models/llm_cost.py`

Each model matches schema in `README_00_Architecture.md`.

### T-1.5: Alembic Migrations
**Claude: Sonnet | Tokens: Low**

Create:
- `alembic.ini` (reads DATABASE_URL from env)
- `migrations/env.py` (imports all models)
- `migrations/versions/001_initial_schema.py` — all 6 tables + indexes + triggers

Test: `make migrate` runs clean. `make down && make up && make migrate` is idempotent.

### T-1.6: Seed Script
**Claude: Sonnet | Tokens: Low**

Create `scripts/seed_prompt_template.py`:
- Inserts default LinkedIn post prompt template
- Template includes: content placeholder, tone instructions, hashtag rules, CTA, character limit
- Marks as `is_active=True`

## Completion Criteria
- [ ] `make up` starts PostgreSQL
- [ ] `make migrate` creates all tables
- [ ] `make seed` inserts prompt template
- [ ] `make lint` passes
- [ ] `make test` passes (config + model tests)
- [ ] `.env.example` has every variable documented

## Files Created
```
pyproject.toml
Makefile
.gitignore
.pre-commit-config.yaml
.env.example
docker-compose.yaml
alembic.ini
src/__init__.py
src/config.py
src/database.py
src/models/__init__.py
src/models/content_upload.py
src/models/post.py
src/models/approval.py
src/models/log.py
src/models/prompt_template.py
src/models/llm_cost.py
migrations/env.py
migrations/versions/001_initial_schema.py
scripts/seed_prompt_template.py
tests/__init__.py
tests/conftest.py
tests/unit/test_config.py
```
