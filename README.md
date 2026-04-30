# LinkedIn Auto-Publisher Pipeline

Automated content-to-LinkedIn publishing pipeline.
Upload content → LLM transforms → Human approves → LinkedIn publishes.

## Stack

| Component | Technology |
|-----------|-----------|
| Orchestration | LangGraph (StateGraph + PG checkpointer) |
| API | FastAPI + Uvicorn |
| LinkedIn | Direct Python client (OAuth2) |
| LLM | Claude Sonnet 4 (Anthropic SDK) |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 + Alembic |
| Storage | Abstracted (Local / AWS S3 / GCS / MinIO) |
| Scheduler | APScheduler (in-process) |
| Approval | Google Sheets + Slack webhook |
| Observability | structlog + Prometheus + OpenTelemetry |
| Containers | Docker (multi-stage) |
| CI/CD | GitHub Actions |
| Production | Kubernetes |

## Architecture

```
Content File → Storage (S3/Local) → PostgreSQL metadata
  → LangGraph Pipeline:
    extract → dedup → sanitize → transform (LLM)
    → validate → schedule → approve → preview → publish → finalize
  → LinkedIn API
```

## Quick Start (Local Dev)

```bash
cp .env.example .env          # Edit with your credentials
make up                       # Start PostgreSQL via Docker Compose
make migrate                  # Run Alembic migrations
make seed                     # Insert default prompt template
make dev                      # Start FastAPI dev server
make test                     # Run test suite
```

## Development Phases

| Phase | Module | README |
|-------|--------|--------|
| 1 | Foundation + Environment | [docs/README_01_Foundation.md](docs/README_01_Foundation.md) |
| 2 | Content Ingestion | [docs/README_02_Ingestion.md](docs/README_02_Ingestion.md) |
| 3 | LinkedIn Client | [docs/README_03_LinkedIn.md](docs/README_03_LinkedIn.md) |
| 4 | Intelligence Layer | [docs/README_04_Intelligence.md](docs/README_04_Intelligence.md) |
| 5 | Scheduling + Dedup | [docs/README_05_Scheduling.md](docs/README_05_Scheduling.md) |
| 6 | Approval Workflow | [docs/README_06_Approval.md](docs/README_06_Approval.md) |
| 7 | LangGraph Orchestration | [docs/README_07_LangGraph.md](docs/README_07_LangGraph.md) |
| 8 | FastAPI Service | [docs/README_08_API.md](docs/README_08_API.md) |
| 9 | Observability + Security | [docs/README_09_Observability.md](docs/README_09_Observability.md) |
| 10 | Docker + K8s + CI/CD | [docs/README_10_Deployment.md](docs/README_10_Deployment.md) |

## Folder Structure

```
linkedin-publisher/
├── src/
│   ├── config.py                  # Env config + validation
│   ├── database.py                # SQLAlchemy engine + session
│   ├── models/                    # SQLAlchemy ORM models
│   ├── ingestion/                 # Storage + content extraction
│   ├── linkedin/                  # OAuth2 + API client
│   ├── intelligence/              # LLM transform + validation
│   ├── scheduling/                # Slot scheduler + dedup
│   ├── approval/                  # Queue + Sheets + Slack
│   ├── pipeline/                  # LangGraph graph + nodes
│   ├── api/                       # FastAPI endpoints
│   └── observability/             # Logging + metrics + tracing
├── migrations/                    # Alembic migrations
├── tests/                         # Unit + integration + E2E
├── scripts/                       # CLI utilities
├── test_content/                  # Local dev sample files
├── k8s/                           # Kubernetes manifests
├── docs/                          # Module READMEs
├── docker-compose.yaml            # Local dev (PG only)
├── Dockerfile                     # Production image
└── .github/workflows/ci.yaml     # CI/CD pipeline
```
