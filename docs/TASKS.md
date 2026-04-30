# Master Task List — 10 Phases, 28 Tasks

Development order is strict. Do not skip ahead.

## Phase 1: Foundation (6 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-1.1 | Project scaffold: pyproject.toml, Makefile, .gitignore, .pre-commit, .env.example | Sonnet | Low | Folder structure from README |
| T-1.2 | docker-compose.yaml: PostgreSQL 16 only | Sonnet | Low | None |
| T-1.3 | config.py: Pydantic Settings + validation | Sonnet | Low | .env.example vars |
| T-1.4 | Database: SQLAlchemy models (6 tables) | Sonnet | Medium | Schema from README_00 |
| T-1.5 | Alembic: migrations + indexes + triggers | Sonnet | Low | models/*.py |
| T-1.6 | Seed script: default prompt template | Sonnet | Low | prompt_template model |

**Gate:** `make up && make migrate && make seed && make test` all pass.

---

## Phase 2: Content Ingestion (4 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-2.1 | Storage client: ABC + Local + S3 implementations | Sonnet | Medium | config.py |
| T-2.2 | Content extractor: PDF/DOCX/MD/TXT | Sonnet | Medium | None |
| T-2.3 | Content reader: unified read interface | Sonnet | Low | storage_client.py + extractor.py signatures |
| T-2.4 | Local folder watcher (watchdog) | Sonnet | Low | storage_client.py signature |

**Gate:** Drop file in test_content/ → DB record created → text extracted.

---

## Phase 3: LinkedIn Client (2 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-3.1 | OAuth2 auth + first-time auth script | Sonnet | Medium | LinkedIn API docs summary |
| T-3.2 | LinkedIn client: publish, upload_image, delete, profile + rate limiter | Sonnet | Medium | auth.py signature |

**Gate:** `linkedin_first_auth.py` runs → dry_run publish succeeds.

---

## Phase 4: Intelligence Layer (5 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-4.1 | Prompt template manager | Sonnet | Low | prompt_template model |
| T-4.2 | Input sanitizer (prompt injection defense) | **Opus** | Low | None |
| T-4.3 | LLM transform agent | **Opus** | Medium | sanitizer.py + prompt_manager.py signatures |
| T-4.4 | Validation engine + rules YAML | Sonnet | Medium | None |
| T-4.5 | Cost tracker | Sonnet | Low | llm_cost model |

**Gate:** Sample markdown → sanitize → transform → validate → valid LinkedIn post.

---

## Phase 5: Scheduling + Dedup (2 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-5.1 | Post scheduler with timezone support | Sonnet | Medium | config.py (slots, timezone) |
| T-5.2 | Hash-based deduplication | Sonnet | Low | None |

**Gate:** Scheduler assigns correct AST slots. Duplicate content detected.

---

## Phase 6: Approval Workflow (4 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-6.1 | Approval queue manager | Sonnet | Medium | approval model |
| T-6.2 | Approval poller | Sonnet | Low | queue.py signature |
| T-6.3 | Google Sheets client | Sonnet | Medium | gspread docs |
| T-6.4 | Slack webhook notifier | Sonnet | Low | None |

**Gate:** Post enters queue → Sheet updated → Slack notified → approve in Sheet → poller detects.

---

## Phase 7: LangGraph Orchestration (4 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-7.1 | PipelineState definition | **Opus** | Low | State schema from README_00 |
| T-7.2 | 10 pipeline nodes (one prompt each) | Sonnet | Medium | state.py + target module signature |
| T-7.3 | Graph assembly: StateGraph + edges + checkpointer | **Opus** | Medium | All node signatures |
| T-7.4 | E2E local test | Sonnet | Low | graph.py |

**Gate:** Full pipeline: file → transform → approve → publish(dry_run) → finalize.

---

## Phase 8: FastAPI Service (4 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-8.1 | FastAPI app + middleware | Sonnet | Medium | None |
| T-8.2 | Pipeline routes: trigger, retry, status, upload | Sonnet | Medium | graph.py invoke signature |
| T-8.3 | Health + metrics routes | Sonnet | Low | metrics.py signature |
| T-8.4 | Background scheduler integration | Sonnet | Low | poller.py + queue.py signatures |

**Gate:** POST /pipeline/trigger invokes full pipeline. GET /health returns 200.

---

## Phase 9: Observability + Security (4 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-9.1 | Structured logging (structlog) | Sonnet | Low | None |
| T-9.2 | Prometheus metrics | Sonnet | Low | None |
| T-9.3 | OpenTelemetry tracing | Sonnet | Low | None |
| T-9.4 | Secrets management abstraction | **Opus** | Low | config.py |

**Gate:** JSON logs in stdout. /metrics endpoint works. Secrets load from env.

---

## Phase 10: Deployment (4 tasks)

| Task | Description | Claude Model | Tokens | Input Context |
|------|-------------|-------------|--------|---------------|
| T-10.1 | Dockerfile (multi-stage, non-root) | Sonnet | Low | pyproject.toml |
| T-10.2 | GitHub Actions CI/CD | Sonnet | Medium | Dockerfile |
| T-10.3 | Kubernetes manifests | Sonnet | Medium | Dockerfile + env vars |
| T-10.4 | Production checklist script | Sonnet | Low | config.py |

**Gate:** Docker builds. CI passes. K8s manifests apply. Checklist green.

---

## Token Optimization Rules

1. **One task per prompt.** Never combine tasks.
2. **Send only relevant context.** For T-7.2 (nodes), send state.py + the one module the node calls. Not the entire codebase.
3. **Use function signatures, not full files.** When a task depends on another module, send only the class/function signatures, not the implementation.
4. **Use Opus only where marked.** Opus is 5x the cost of Sonnet — use only for: state design, graph wiring, sanitizer, transform agent, secrets.
5. **Test after every task.** Catch errors early. A bug found in Phase 7 that originated in Phase 2 costs 10x more tokens to fix.
6. **Copy exact file paths.** Every task lists its output files. Use those paths.
7. **Commit after every phase gate.** Git commit = checkpoint. If something breaks, you can revert cleanly.

## Estimated Token Budget

| Phase | Opus Prompts | Sonnet Prompts | Est. Total Tokens |
|-------|-------------|---------------|-------------------|
| 1 | 0 | 6 | ~30K |
| 2 | 0 | 4 | ~25K |
| 3 | 0 | 2 | ~20K |
| 4 | 2 | 3 | ~40K |
| 5 | 0 | 2 | ~12K |
| 6 | 0 | 4 | ~25K |
| 7 | 2 | 12 | ~60K |
| 8 | 0 | 4 | ~25K |
| 9 | 1 | 3 | ~20K |
| 10 | 0 | 4 | ~25K |
| **Total** | **5** | **44** | **~280K** |
