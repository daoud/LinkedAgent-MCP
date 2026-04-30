# Phase 8: FastAPI Service

## Dependencies
- Phase 7 complete (LangGraph pipeline works locally)

## Tasks

### T-8.1: FastAPI Application
**Claude: Sonnet | Tokens: Medium**

Create `src/api/app.py`:
- FastAPI app with lifespan (startup: init DB, scheduler; shutdown: graceful drain)
- CORS middleware (configurable origins)
- Exception handlers for known error types
- SIGTERM handler for graceful shutdown in K8s

Create `src/api/middleware.py`:
- Request ID middleware (adds X-Request-ID to every request/response)
- Request logging middleware (structlog: method, path, status, duration)

### T-8.2: Pipeline Routes
**Claude: Sonnet | Tokens: Medium**

Create `src/api/routes/pipeline.py`:
- `POST /pipeline/trigger` — accepts `{upload_id: str}`, invokes LangGraph
  - Validates upload_id exists in content_uploads
  - Checks daily quota before starting
  - Runs graph asynchronously (background task)
  - Returns `{status: "triggered", upload_id: str}`
- `POST /pipeline/retry/{post_id}` — retries failed post
  - Resets retry_count, clears error
  - Re-invokes graph from failed_at_node
- `GET /pipeline/status/{upload_id}` — returns current pipeline state
  - Reads from posts table: status, scheduled_slot, approval_status, error
- `GET /pipeline/posts` — list recent posts with status
  - Query params: status, limit, offset
- `POST /pipeline/upload` — upload file directly via API
  - Accepts multipart file
  - Stores via StorageClient
  - Creates content_uploads record
  - Triggers pipeline

### T-8.3: Health + Metrics Routes
**Claude: Sonnet | Tokens: Low**

Create `src/api/routes/health.py`:
- `GET /health` — K8s liveness probe
  - Returns 200 if service is running
- `GET /ready` — K8s readiness probe
  - Checks DB connection
  - Checks LinkedIn token not expired
  - Returns 200 only if all checks pass
- `GET /metrics` — Prometheus metrics endpoint
  - Uses `prometheus_client` to expose counters/gauges

### T-8.4: Background Scheduler Integration
**Claude: Sonnet | Tokens: Low**

Wire APScheduler into FastAPI lifespan:
- Job 1: Poll approval decisions every 5 minutes
- Job 2: Expire stale approvals every 15 minutes
- Job 3: Check LinkedIn token expiry daily
- Job 4: Check LLM budget daily
- Scheduler starts on app startup, stops on shutdown

## Completion Criteria
- [ ] `make dev` starts FastAPI on port 8000
- [ ] POST /pipeline/trigger invokes pipeline
- [ ] GET /health returns 200
- [ ] GET /ready checks DB + LinkedIn token
- [ ] GET /metrics exposes Prometheus metrics
- [ ] Background jobs run on schedule
- [ ] Graceful shutdown drains in-flight work

## Files Created
```
src/api/__init__.py
src/api/app.py
src/api/middleware.py
src/api/routes/__init__.py
src/api/routes/pipeline.py
src/api/routes/health.py
tests/integration/test_api_trigger.py
tests/integration/test_api_health.py
```
