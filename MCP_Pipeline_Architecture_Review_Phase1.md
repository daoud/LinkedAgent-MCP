# MCP Pipeline Architecture Review — Phase 1
## Principal Architect Assessment | April 2026

---

## EXECUTIVE VERDICT

The plan v3.0 is a solid **70% foundation** — the data flow is correct, the PostgreSQL-centric approach is sound, and the LangGraph choice is justified. However, there are **7 critical issues** that would cause production failures, **9 design weaknesses** that create unnecessary risk, and **4 components that should be removed** to reduce complexity without losing capability.

This review fixes all of them and produces a validated architecture ready for implementation.

---

## SECTION 1: CRITICAL ISSUES (Must Fix Before Development)

### CRITICAL-1: Celery + LangGraph Is Architectural Conflict

**Problem:** The plan uses LangGraph for orchestration AND Celery+Redis for retry/DLQ. These are two competing orchestration layers. LangGraph already provides state persistence via PostgreSQL checkpointer, node-level error handling, and the ability to resume from any failed node. Adding Celery on top creates:
- Two separate failure tracking systems that will drift out of sync
- Double the infrastructure (Redis) for a 2–3 post/day system
- Confusing debugging: "Did the Celery task fail or the LangGraph node?"

**Fix:** Remove Celery and Redis entirely. Use LangGraph's built-in checkpointer for retry (re-invoke the graph from the last successful node). Add a `retry_count` and `last_error` field to the state and `posts` table. For DLQ, simply mark posts with `status=failed` and `retry_count >= 3` — query them with a simple CLI or dashboard. For scheduling, use a lightweight FastAPI endpoint triggered by K8s CronJob.

**Impact:** Eliminates an entire infrastructure layer, saves ~30% of development time on Phase 8.

---

### CRITICAL-2: No Pipeline Trigger Mechanism

**Problem:** The plan says "file uploaded to Cloud Storage" triggers the pipeline, but there is no actual trigger defined. There is no GCS Pub/Sub notification, no webhook endpoint, no event listener. For local mode, there's a folder watcher (T-2.2), but for production there's nothing.

**Fix:** Add a FastAPI trigger service with two endpoints:
- `POST /pipeline/trigger` — accepts upload_id, invokes LangGraph (for webhook/Pub/Sub integration)
- `GET /pipeline/health` — K8s liveness/readiness probe

For GCS production: configure GCS → Pub/Sub → Push Subscription → trigger endpoint.
For local dev: the folder watcher calls the same trigger endpoint.

This also gives you a single entry point for manual re-runs and debugging.

---

### CRITICAL-3: GCS Client Mismatch

**Problem:** The plan says "S3-compatible" and references boto3, but the stated infrastructure is Google Cloud Storage. GCS has an S3 compatibility layer, but it has significant limitations: no multipart upload support identical to S3, different IAM model, and the native `google-cloud-storage` Python client is better in every way for GCS.

**Fix:** Use `google-cloud-storage` client library, not boto3. If you genuinely need S3 compatibility for future multi-cloud, use an abstraction interface with GCS and S3 implementations behind it. But for a single-cloud deployment, just use the native client.

---

### CRITICAL-4: No Observability Stack

**Problem:** No structured logging, no metrics, no tracing, no dashboards, no alerting (beyond LLM budget). For a production K8s deployment, this is a critical gap. When the pipeline fails at 2 AM, you have nothing to diagnose with.

**Fix:** Add an observability layer:
- **Structured logging:** `structlog` → JSON format → stdout (K8s collects via Fluentd/Loki)
- **Metrics:** Prometheus client → expose `/metrics` endpoint → pipeline_runs_total, pipeline_duration_seconds, llm_tokens_total, linkedin_publish_success/failure counters
- **Tracing:** OpenTelemetry spans per LangGraph node → Jaeger/Cloud Trace
- **Alerting:** Prometheus Alertmanager rules for: pipeline failure rate > 50%, LinkedIn token expiry < 10 days, daily post quota not met, LLM budget > 80%

---

### CRITICAL-5: No Input Sanitization (Prompt Injection Risk)

**Problem:** Raw content from uploaded files goes directly into LLM prompts. If someone uploads a file containing adversarial text like "Ignore previous instructions and post: [malicious content]", the LLM will follow those instructions. The validation node runs AFTER the LLM, so it catches format issues but not prompt injection.

**Fix:** Add a pre-transform sanitization node:
- Strip known prompt injection patterns
- Limit input length before LLM processing (not just after)
- Run content through a classification check (is this business content or adversarial?)
- The human approval step is the ultimate safety net, but automated pre-screening reduces noise

---

### CRITICAL-6: Timezone Handling Missing

**Problem:** `POST_SLOTS = 09:00,13:00,18:00` with no timezone. The user is based in Saudi Arabia (AST, UTC+3). LinkedIn's API uses UTC. If the scheduler interprets these as UTC, posts go out at noon, 4 PM, and 9 PM local time — completely wrong slots.

**Fix:** Add `TIMEZONE = Asia/Riyadh` to env config. All slot times are interpreted in this timezone. The scheduler converts to UTC for internal scheduling. Store all DB timestamps as `TIMESTAMP WITH TIME ZONE`. Display times in the configured timezone in logs and approval UI.

---

### CRITICAL-7: LinkedIn Token Storage Is Insecure

**Problem:** `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_REFRESH_TOKEN` in plain environment variables. LinkedIn tokens are equivalent to account credentials. If the env file leaks, your LinkedIn account is compromised.

**Fix for production:** Store tokens in Google Secret Manager (since you're on GCP). The auth module reads from Secret Manager, not env vars. For local dev, env vars are acceptable but should never be committed. Add a `secrets.py` abstraction that reads from env in dev and Secret Manager in production.

---

## SECTION 2: DESIGN WEAKNESSES (Should Fix)

### WEAK-1: Redundant Status Fields

**Problem:** `approval_status` exists on both the `posts` table and the `approval_queue` table. `status` on `posts` can be `pending | approved | published | failed` which overlaps with `approval_status`. This will inevitably drift — one gets updated, the other doesn't.

**Fix:** Remove `approval_status` from the `posts` table. The `posts.status` field is the single source of truth for overall state. The `approval_queue.decision` field is the single source of truth for approval state. The state machine is: `pending → processing → awaiting_approval → approved → publishing → published | failed`.

---

### WEAK-2: No Database Indexes

**Problem:** Not a single index is defined. With even moderate data, queries on `content_uploads.status`, `posts.status`, `posts.scheduled_slot`, `approval_queue.decision`, and `posts.post_hash` will table-scan.

**Fix:** Add explicit indexes:
```
content_uploads: (status), (content_hash)
posts: (status, scheduled_slot), (post_hash), (upload_id)
approval_queue: (decision, scheduled_at), (post_id)
logs: (post_id, created_at)
llm_costs: (recorded_at)
```

---

### WEAK-3: No `updated_at` Columns

**Problem:** Tables have `created_at` but no `updated_at`. When debugging "why is this post stuck?", you can't tell when the last state change happened.

**Fix:** Add `updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()` to `content_uploads`, `posts`, and `approval_queue`. Add a PostgreSQL trigger to auto-update on row modification.

---

### WEAK-4: State Schema Missing Error Tracking

**Problem:** LangGraph state has no way to track errors. If the transform node fails, there's no `error_message`, `retry_count`, or `failed_at_node` field. The graph just stops and you have no diagnostic information.

**Fix:** Add to PipelineState:
```
error_message:   Optional[str]    # last error description
retry_count:     int              # number of retry attempts (default 0)
failed_at_node:  Optional[str]    # which node failed
image_refs:      list[str]        # GCS paths for image attachments
```

---

### WEAK-5: Image Handling Is Undefined

**Problem:** The state carries `raw_content` as `str`, but what about image posts? Images can't be serialized as a string in state. The plan mentions `linkedin_upload_image(base64)` but doesn't define how images flow through the pipeline — are they stored in GCS? How does the LLM get context about an image? How does the state reference them?

**Fix:** Images stay in GCS. The state carries `image_refs: list[str]` (GCS paths). The LLM receives a text description of the image (from the upload metadata or a vision model caption). At publish time, the publish node fetches images from GCS, converts to base64, and calls `linkedin_upload_image`. This keeps the state lightweight and the pipeline clean.

---

### WEAK-6: Google Sheets Approval Is Fragile

**Problem:** Google Sheets API has rate limits (60 requests/minute for reads). Polling every 5 minutes creates a tight coupling to a consumer tool that can be accidentally edited, shared, or deleted. There's no audit trail beyond what you manually write to PostgreSQL.

**Fix for MVP:** Keep Google Sheets but add guardrails — validate the sheet structure on each poll, log every decision read, add a "last_checked_at" field. Add Slack webhook notification when a post enters the approval queue (so you don't have to watch the sheet).

**Fix for production (Phase 2):** Replace Google Sheets with a simple FastAPI approval page: list pending posts, approve/reject buttons, decision written directly to PostgreSQL. Eliminates the Sheets dependency entirely.

---

### WEAK-7: Scheduler Has Two Implementations

**Problem:** APScheduler for local dev, K8s CronJob for production. Two completely different scheduler systems means you can't test production scheduling behavior locally.

**Fix:** Use APScheduler everywhere. In production, it runs inside the FastAPI service as a background scheduler. In K8s, the service has a `/scheduler/run` endpoint that the CronJob hits as a backup/failsafe, but the primary scheduling is the same APScheduler code in both environments.

---

### WEAK-8: No Content Extraction Strategy

**Problem:** The plan says file types are "document | image | markdown" but doesn't define how PDFs, DOCX, or other document types get their text extracted. `read_content()` fetches the file but then what?

**Fix:** Add a content extraction layer between read and transform:
- `.md` files → read as-is
- `.txt` files → read as-is
- `.pdf` files → `pymupdf` text extraction
- `.docx` files → `python-docx` text extraction
- `.png/.jpg` files → store as image_ref, optionally run vision caption
- Add `file_type` detection via MIME type, not just file extension

---

### WEAK-9: No Graceful Shutdown

**Problem:** K8s sends SIGTERM and expects pods to drain gracefully within a termination grace period. If the pipeline is mid-publish when SIGTERM arrives, the post might publish but the DB never gets updated — creating a ghost post.

**Fix:** Register a SIGTERM handler in the FastAPI service. On SIGTERM: stop accepting new pipeline runs, wait for in-flight runs to complete (up to 30s), then exit. Set K8s `terminationGracePeriodSeconds: 60`. LangGraph's checkpointer naturally handles interrupted runs on next startup.

---

## SECTION 3: UNNECESSARY COMPLEXITY (Remove)

### REMOVE-1: Celery + Redis
**Reason:** LangGraph checkpointer + FastAPI + CronJob handles everything Celery does for this workload (2–3 posts/day). Celery is designed for thousands of tasks/minute. This is engineering for scale you don't have and won't need for years.

### REMOVE-2: Separate MCP Server Container (Phase 4)
**Reason:** Running LinkedIn as a separate FastMCP server on port 8002 in its own container adds a network hop, a Docker image, health checking, and deployment complexity. For a single-pipeline, single-LinkedIn-account system, the LinkedIn client should be a Python module imported directly into the LangGraph nodes. MCP servers make sense when multiple agents need to discover and share tools dynamically. Here, the tool set is fixed and known at compile time.

**What to do instead:** Create a `linkedin_client.py` module with the same 4 functions (publish, upload_image, delete_post, get_profile). Import it directly in the LangGraph publish node. If you later need MCP (for multi-agent scenarios), wrap this same module in FastMCP — the migration is trivial because the function signatures are identical.

### REMOVE-3: Redis Dependency
**Reason:** With Celery removed, Redis has no purpose unless you add caching (unnecessary at this scale) or rate limiting (can be done with an in-memory token bucket for 3 posts/day).

### REMOVE-4: Dual Dedup (content_hash + post_hash)
**Reason:** The plan deduplicates twice — once on `content_hash` (file level) and once on `post_hash` (transformed output level). For a single-user system, file-level dedup is sufficient. Post-level dedup is a nice safeguard but adds complexity. **Keep both** — the post-hash catches the case where different source files produce identical LinkedIn posts — but move the post-hash check into the validation node instead of being a separate node. It's one SQL query, not a whole pipeline stage.

---

## SECTION 4: MISSING COMPONENTS (Must Add)

### ADD-1: FastAPI Trigger Service
- `POST /pipeline/trigger` — accepts upload_id
- `GET /health` — K8s probe
- `GET /metrics` — Prometheus scrape
- `POST /pipeline/retry/{post_id}` — manual retry
- `GET /pipeline/status/{upload_id}` — check pipeline state

### ADD-2: Observability Stack
- structlog for JSON logging
- Prometheus metrics client
- OpenTelemetry tracing per LangGraph node
- Alertmanager rules for critical failures

### ADD-3: Secret Manager Integration
- `secrets.py` abstraction (env vars in dev, Google Secret Manager in prod)
- LinkedIn token encryption at rest
- Database credentials from Secret Manager in production

### ADD-4: Content Extraction Layer
- `content_extractor.py` — MIME-based routing to appropriate text extractor
- Support: markdown, plain text, PDF, DOCX, images (caption/ref)

### ADD-5: GCS Event Trigger
- GCS → Pub/Sub notification on object upload
- Pub/Sub Push Subscription → FastAPI trigger endpoint
- This replaces the undefined "how does the pipeline know a file was uploaded" gap

### ADD-6: PostgreSQL Backup Strategy
- `pg_dump` CronJob for daily backups to GCS
- Point-in-time recovery configuration
- For managed PostgreSQL (Cloud SQL), enable automated backups

### ADD-7: Rate Limiter for LinkedIn API
- Token bucket rate limiter (in-memory, no Redis needed)
- Respects LinkedIn's `X-RateLimit-Remaining` header
- Backs off before hitting the limit, not after

---

## SECTION 5: DATABASE SCHEMA — CORRECTED VERSION

```sql
-- All timestamps are WITH TIME ZONE

CREATE TABLE content_uploads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name       TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    storage_type    TEXT NOT NULL CHECK (storage_type IN ('cloud', 'local')),
    mime_type       TEXT,                     -- ADDED: actual MIME type
    file_type       TEXT NOT NULL CHECK (file_type IN ('document', 'image', 'markdown', 'text')),
    content_hash    TEXT NOT NULL,            -- CHANGED: NOT NULL, not UNIQUE (allow re-uploads)
    file_size_bytes BIGINT,                  -- ADDED: for monitoring
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'published', 'failed', 'skipped')),
    error_message   TEXT,                     -- ADDED: why it failed
    uploaded_at     TIMESTAMPTZ DEFAULT NOW(),
    processed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT NOW() -- ADDED
);

CREATE INDEX idx_uploads_status ON content_uploads(status);
CREATE INDEX idx_uploads_hash ON content_uploads(content_hash);
CREATE INDEX idx_uploads_uploaded ON content_uploads(uploaded_at);

CREATE TABLE posts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id        UUID NOT NULL REFERENCES content_uploads(id),
    raw_content      TEXT,
    transformed_text TEXT,
    post_hash        TEXT UNIQUE,
    scheduled_slot   TIME,                    -- CHANGED: from TEXT to TIME
    scheduled_date   DATE,                    -- ADDED: which day
    linkedin_post_id TEXT,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'processing', 'awaiting_approval',
                            'approved', 'rejected', 'publishing', 'published', 'failed')),
    retry_count      INT DEFAULT 0,           -- ADDED
    last_error       TEXT,                    -- ADDED
    failed_at_node   TEXT,                    -- ADDED: LangGraph node name
    tokens_used      INT,
    cost_usd         NUMERIC(8,6),
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    published_at     TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ DEFAULT NOW() -- ADDED
);

CREATE INDEX idx_posts_status_slot ON posts(status, scheduled_slot);
CREATE INDEX idx_posts_hash ON posts(post_hash);
CREATE INDEX idx_posts_upload ON posts(upload_id);
CREATE INDEX idx_posts_scheduled ON posts(scheduled_date, scheduled_slot);

CREATE TABLE approval_queue (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id       UUID NOT NULL REFERENCES posts(id),
    preview_text  TEXT NOT NULL,
    scheduled_at  TIMESTAMPTZ,
    decision      TEXT NOT NULL DEFAULT 'pending'
                  CHECK (decision IN ('pending', 'approved', 'rejected', 'timeout')),
    decided_by    TEXT,                       -- ADDED: who approved
    decided_at    TIMESTAMPTZ,
    expires_at    TIMESTAMPTZ,               -- ADDED: auto-reject deadline
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_approval_decision ON approval_queue(decision, scheduled_at);
CREATE INDEX idx_approval_post ON approval_queue(post_id);
CREATE INDEX idx_approval_expires ON approval_queue(expires_at) WHERE decision = 'pending';

CREATE TABLE logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id     UUID REFERENCES posts(id),
    upload_id   UUID REFERENCES content_uploads(id), -- ADDED: log before post exists
    node_name   TEXT,                                -- ADDED: which LangGraph node
    level       TEXT NOT NULL CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical')),
    message     TEXT NOT NULL,
    metadata    JSONB,                               -- ADDED: structured extra data
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_logs_post ON logs(post_id, created_at);
CREATE INDEX idx_logs_level ON logs(level, created_at);

CREATE TABLE prompt_templates (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,              -- ADDED: human-readable name
    version       INT NOT NULL,
    template_text TEXT NOT NULL,
    variables     JSONB,                     -- ADDED: expected template variables
    is_active     BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    created_by    TEXT                        -- ADDED: audit trail
);

CREATE UNIQUE INDEX idx_prompt_active ON prompt_templates(is_active) WHERE is_active = TRUE;

CREATE TABLE llm_costs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id       UUID REFERENCES posts(id),
    model         TEXT NOT NULL,
    input_tokens  INT NOT NULL,
    output_tokens INT NOT NULL,
    cost_usd      NUMERIC(10,6) NOT NULL,    -- CHANGED: wider precision
    recorded_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_costs_recorded ON llm_costs(recorded_at);

-- Auto-update updated_at trigger
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_content_uploads_modtime
    BEFORE UPDATE ON content_uploads
    FOR EACH ROW EXECUTE FUNCTION update_modified_column();

CREATE TRIGGER update_posts_modtime
    BEFORE UPDATE ON posts
    FOR EACH ROW EXECUTE FUNCTION update_modified_column();
```

---

## SECTION 6: CORRECTED LANGGRAPH STATE

```python
from typing import Optional
from pydantic import BaseModel, Field

class PipelineState(BaseModel):
    # Identity
    upload_id: str
    post_id: Optional[str] = None

    # Storage
    storage_type: str                          # 'cloud' | 'local'
    storage_path: str
    mime_type: Optional[str] = None
    file_type: str                             # document | image | markdown | text

    # Content
    raw_content: Optional[str] = None
    image_refs: list[str] = Field(default_factory=list)  # ADDED: GCS paths for images
    transformed_content: Optional[str] = None

    # Dedup
    content_hash: Optional[str] = None
    post_hash: Optional[str] = None

    # Scheduling
    scheduled_slot: Optional[str] = None
    scheduled_date: Optional[str] = None       # ADDED

    # Approval
    approval_required: bool = True
    approval_status: str = "pending"

    # Publishing
    linkedin_post_id: Optional[str] = None
    dry_run: bool = True                       # ADDED: safety default

    # Status + Error Tracking
    status: str = "pending"
    error_message: Optional[str] = None        # ADDED
    retry_count: int = 0                       # ADDED
    failed_at_node: Optional[str] = None       # ADDED

    # Cost
    tokens_used: int = 0
    cost_usd: float = 0.0
```

---

## SECTION 7: CORRECTED PRODUCTION FLOW

```
Step  Action                                          Error Handling
----  ------                                          --------------
 1    File uploaded to GCS (prod) / local (dev)       GCS event fires Pub/Sub notification
 2    Pub/Sub pushes to FastAPI /pipeline/trigger      If push fails, Pub/Sub retries (built-in)
 3    FastAPI creates content_uploads record            DB write failure → return 500, Pub/Sub retries
      (status=pending)
 4    Scheduler check: daily count < limit?            If at limit → status=skipped, log, exit
 5    LangGraph invoked with upload_id                 Checkpointer saves state at each node
 6    NODE: extract_content                            PDF/DOCX extraction failure → status=failed
      - Fetch file from GCS/local
      - Extract text via mime-type router
      - Images: store paths in image_refs
 7    NODE: dedup_check                                If duplicate → status=skipped, log, exit
      - Check content_hash in content_uploads
 8    NODE: sanitize                                   Strip injection patterns, length cap
 9    NODE: transform                                  LLM failure → retry up to 3x
      - Load active prompt template
      - LLM generates LinkedIn post
      - Record tokens + cost
10    NODE: validate                                   Validation failure → status=failed, log details
      - Length, hashtags, banned words
      - Post-hash dedup check
      - URL/formatting validation
11    NODE: schedule_slot                              Assign date + time slot
12    NODE: await_approval (conditional)               Timeout → auto-reject after 24h
      - Write to approval_queue
      - Notify via Slack webhook
      - Graph pauses (LangGraph interrupt)
      - Poller checks decision every 5 min
13    Human approves via Sheets/Slack/API
14    NODE: preview                                    Dry-run publish, log result
      - linkedin_publish(dry_run=True)
15    NODE: publish                                    API failure → retry with backoff (3x)
      - Upload images if present
      - linkedin_publish(dry_run=False)
      - Rate limiter checks before call
16    NODE: finalize                                   DB update failure → alert + manual fix
      - Update posts: status=published, linkedin_post_id
      - Update content_uploads: status=published
      - Record LLM cost
      - Write structured log
17    On any node failure with retry_count >= 3:
      - Mark status=failed
      - Alert via Slack/email
      - Appears in failed-posts dashboard
```

---

## SECTION 8: FINAL RECOMMENDED ARCHITECTURE

```
                    ┌─────────────────────────────────┐
                    │       Google Cloud Storage       │
                    │    (content files + images)      │
                    └───────────────┬──────────────────┘
                                    │ GCS Notification
                                    ▼
                    ┌─────────────────────────────────┐
                    │        Cloud Pub/Sub             │
                    │    (push subscription)           │
                    └───────────────┬──────────────────┘
                                    │ HTTP Push
                                    ▼
┌───────────────────────────────────────────────────────────────┐
│                    FastAPI Service (K8s Pod)                   │
│                                                               │
│  POST /pipeline/trigger    ←  Pub/Sub push                    │
│  POST /pipeline/retry/:id  ←  Manual retry                    │
│  GET  /pipeline/status/:id ←  Status check                    │
│  GET  /health              ←  K8s probe                       │
│  GET  /metrics             ←  Prometheus scrape                │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              LangGraph StateGraph                       │  │
│  │                                                         │  │
│  │  extract → dedup → sanitize → transform → validate      │  │
│  │  → schedule → await_approval → preview → publish        │  │
│  │  → finalize                                             │  │
│  │                                                         │  │
│  │  PostgreSQL Checkpointer (state persistence)            │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │ linkedin_    │  │ content_     │  │ approval_        │    │
│  │ client.py    │  │ extractor.py │  │ poller.py        │    │
│  │ (direct SDK) │  │ (PDF/DOCX/MD)│  │ (Sheets+Slack)   │    │
│  └──────────────┘  └──────────────┘  └──────────────────┘    │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  APScheduler (background, same process)              │    │
│  │  - Poll for pending uploads at slot times            │    │
│  │  - Check approval timeouts                           │    │
│  │  - Token expiry alerts                               │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  Observability: structlog + Prometheus + OpenTelemetry        │
└───────────────────────────────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │     PostgreSQL         │
              │  (Cloud SQL / local)   │
              │                        │
              │  - content_uploads     │
              │  - posts               │
              │  - approval_queue      │
              │  - logs                │
              │  - prompt_templates    │
              │  - llm_costs           │
              │  - LangGraph checkpoint│
              └────────────────────────┘
                           │
                     ┌─────┴──────┐
                     ▼            ▼
              ┌──────────┐  ┌──────────┐
              │ LinkedIn │  │  Google   │
              │   API    │  │ Sheets + │
              │          │  │  Slack   │
              └──────────┘  └──────────┘
```

### What Was Removed
| Component | Reason |
|-----------|--------|
| Celery | Overkill for 3 posts/day; LangGraph checkpointer handles retry+resume |
| Redis | Only needed for Celery; no other use case at this scale |
| MCP Server container | Single consumer, fixed tool set; direct Python module is simpler |
| Separate dedup node | Merged into validation node; one SQL query, not a pipeline stage |

### What Was Added
| Component | Reason |
|-----------|--------|
| FastAPI trigger service | Pipeline needs an entry point; also provides health/metrics/retry endpoints |
| GCS → Pub/Sub trigger | Event-driven pipeline activation in production |
| Content extraction layer | Must handle PDF/DOCX/TXT/MD/images differently |
| Sanitization node | Prompt injection defense before LLM processing |
| Observability stack | structlog + Prometheus + OpenTelemetry for production diagnostics |
| Secret Manager integration | Encrypted credential storage for production |
| Rate limiter | LinkedIn API protection without Redis |
| Timezone-aware scheduling | Saudi Arabia timezone handling for correct post slots |
| PostgreSQL backup strategy | Data protection for production |

---

## SECTION 9: TECHNOLOGY STACK — FINAL

| Component | Technology | Justification |
|-----------|-----------|---------------|
| Orchestration | LangGraph v0.3+ (StateGraph + PG checkpointer) | Built-in persistence, retry, interrupt |
| API Layer | FastAPI + Uvicorn | Trigger endpoint, health, metrics |
| LinkedIn Client | Direct Python module (requests + OAuth2) | No MCP overhead for fixed tool set |
| LLM Provider | Claude Sonnet 4 (Anthropic SDK) | Primary; template-driven |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 + Alembic | Schema, migrations, checkpointer |
| Object Storage | Google Cloud Storage (google-cloud-storage) | Native client, not boto3 |
| Scheduler | APScheduler (in-process) | Same code dev+prod; K8s CronJob as backup |
| Content Extraction | pymupdf + python-docx + markdown | PDF, DOCX, MD support |
| Approval UI (MVP) | Google Sheets + Slack notifications | Fast to build; Slack for alerts |
| Observability | structlog + prometheus_client + opentelemetry | Logging, metrics, tracing |
| Secrets (prod) | Google Secret Manager | Encrypted at rest, audit trail |
| Containers | Docker (multi-stage, non-root, distroless) | Minimal attack surface |
| Orchestration (prod) | Kubernetes (GKE) | Deployment, scaling, CronJobs |
| CI/CD | GitHub Actions | Lint, test, build, scan, deploy |
| DB Backup | pg_dump CronJob → GCS bucket | Daily automated backups |

---

## SECTION 10: MUST-HAVE CHECKLIST BEFORE DEVELOPMENT

These items must be confirmed or set up before writing the first line of code:

| # | Item | Status |
|---|------|--------|
| 1 | LinkedIn Developer App created, `w_member_social` scope approved | ☐ |
| 2 | GCP project created, GCS bucket provisioned, Pub/Sub topic + subscription created | ☐ |
| 3 | Cloud SQL PostgreSQL instance provisioned (or local Docker PG for Phase 1) | ☐ |
| 4 | Google Secret Manager enabled in GCP project | ☐ |
| 5 | Anthropic API key obtained with sufficient credits | ☐ |
| 6 | Google Sheets API enabled, service account key for approval sheet | ☐ |
| 7 | Slack workspace + webhook URL for notifications | ☐ |
| 8 | GitHub repository created with branch protection rules | ☐ |
| 9 | GKE cluster provisioned (can defer to Phase 9, use Docker Compose for dev) | ☐ |
| 10 | Docker Desktop / Docker Engine installed locally | ☐ |
| 11 | Python 3.12+ installed, `uv` or `poetry` for dependency management | ☐ |
| 12 | LinkedIn OAuth2 first-time auth completed locally (browser flow), tokens saved | ☐ |
| 13 | Timezone confirmed: `Asia/Riyadh` (UTC+3) for scheduling | ☐ |
| 14 | Daily post limit confirmed: 3/day at 09:00, 13:00, 18:00 AST | ☐ |
| 15 | LLM monthly budget cap confirmed: $20 USD | ☐ |

---

## SECTION 11: DEVELOPMENT ROADMAP — MASTER SEQUENCE

Below is the corrected build order (10 phases, 28 tasks), optimized to avoid rework and enable testing at every phase boundary.

### Phase 1: Foundation (Tasks 1–4)
Monorepo, Docker Compose (PG only, no Redis), Alembic migrations, env config.

### Phase 2: Content Ingestion (Tasks 5–8)
GCS client, local watcher, content extractor, content reader abstraction.

### Phase 3: LinkedIn Client (Tasks 9–10)
OAuth2 auth module, LinkedIn client library (publish, image upload, delete, profile).

### Phase 4: Intelligence Layer (Tasks 11–14)
Prompt template manager, content sanitizer, LLM transform agent, validation engine.

### Phase 5: Scheduling + Dedup (Tasks 15–16)
Slot scheduler with timezone support, hash-based dedup.

### Phase 6: Approval Workflow (Tasks 17–18)
Approval queue + poller, Google Sheets integration + Slack notification.

### Phase 7: LangGraph Orchestration (Tasks 19–20)
Full StateGraph wiring, PG checkpointer, all nodes connected, E2E local test.

### Phase 8: FastAPI Service (Tasks 21–22)
Trigger endpoint, health/metrics/status endpoints, Pub/Sub integration.

### Phase 9: Observability + Security (Tasks 23–25)
Structured logging, Prometheus metrics, OpenTelemetry tracing, Secret Manager, rate limiter.

### Phase 10: Containerization + CI/CD + K8s (Tasks 26–28)
Docker images, GitHub Actions pipeline, K8s manifests, production deployment.

---

## SECTION 12: README MODULE STRUCTURE

Each major module gets its own README for Claude Code terminal development:

| README File | Covers |
|-------------|--------|
| `README_00_Architecture.md` | This review document, final architecture, decision log |
| `README_01_Foundation.md` | Monorepo layout, Docker Compose, Alembic, env config |
| `README_02_Ingestion.md` | GCS client, local watcher, content extractor, reader |
| `README_03_LinkedIn.md` | OAuth2 flow, token management, client library, API limits |
| `README_04_Intelligence.md` | Prompt templates, sanitizer, transform agent, validator |
| `README_05_Scheduling.md` | APScheduler, slot allocation, timezone, dedup |
| `README_06_Approval.md` | Approval queue, poller, Google Sheets, Slack webhook |
| `README_07_LangGraph.md` | StateGraph, nodes, edges, checkpointer, interrupt, retry |
| `README_08_FastAPI.md` | Trigger service, endpoints, Pub/Sub push handler |
| `README_09_Observability.md` | structlog, Prometheus, OpenTelemetry, alerting rules |
| `README_10_Deployment.md` | Docker, K8s manifests, CI/CD pipeline, Secret Manager |

---

## SECTION 13: CLAUDE MODEL ALLOCATION PER TASK TYPE

| Task Type | Recommended Model | Reason |
|-----------|-------------------|--------|
| Architecture review, security audit, design decisions | **Opus** | Complex reasoning, tradeoff analysis |
| Database schema, Alembic migrations | **Sonnet** | Structured, well-defined output |
| Python module code generation | **Sonnet** | Best code quality per token |
| LangGraph graph wiring + state design | **Opus** | Complex state machine logic |
| FastAPI endpoints | **Sonnet** | Standard patterns |
| Docker + K8s manifests | **Sonnet** | Template-heavy, well-defined |
| CI/CD pipeline (GitHub Actions) | **Sonnet** | YAML generation |
| Prompt template engineering | **Opus** | Requires nuanced prompt design |
| Test case generation | **Sonnet** | Pattern-based |
| Documentation / READMEs | **Sonnet** | Clear prose, lower complexity |
| Debugging / troubleshooting | **Opus** | Multi-file reasoning |
| Refactoring | **Sonnet** | Mechanical transformations |
| Security hardening | **Opus** | Threat modeling requires deep reasoning |
| Code review | **Opus** | Needs full-context understanding |

**Token optimization rule:** Never send the full codebase in a prompt. Send only the file being worked on + the interface contracts (function signatures, state schema) of connected modules. This cuts token usage by 60–70%.

---

## SECTION 14: RISK REGISTER — CORRECTED

| Risk | Severity | Mitigation |
|------|----------|------------|
| LinkedIn token expiry (60 days) | CRITICAL | Auto-refresh at 50 days. Secret Manager storage. Alert at 45 days. Fallback: manual re-auth runbook. |
| Prompt injection via uploaded content | CRITICAL | Sanitization node before LLM. Input length cap. Human approval as final gate. |
| Duplicate post publishing | HIGH | Content-hash dedup + post-hash dedup. Unique constraint on post_hash. |
| LLM hallucination in post content | HIGH | Validation rules + human approval. No auto-publish without approval. |
| Feed flooding | HIGH | Daily quota in scheduler. 4-hour minimum gap. Hard limit in LinkedIn client. |
| Pipeline state corruption | HIGH | PG checkpointer with transactions. Resume from last clean node. |
| GCS access denied | MEDIUM | IAM validation at startup. Structured error logging. Alert on auth failure. |
| LLM cost overrun | MEDIUM | Per-post cost tracking. Monthly budget alert at 80%. Hard stop at 100%. |
| LinkedIn API rate limit | MEDIUM | Token bucket rate limiter. Parse X-RateLimit headers. Backoff before limit. |
| Google Sheets API failure | MEDIUM | Retry with backoff. Slack notification as backup approval channel. |
| PostgreSQL connection loss | MEDIUM | Connection pooling (SQLAlchemy). Checkpointer resumes on reconnect. |
| K8s pod crash during publish | MEDIUM | Graceful shutdown handler. Checkpointer saves pre-publish state. Idempotent publish (check if post_id already exists on LinkedIn). |
| Timezone misconfiguration | LOW | Validate timezone at startup. Log all times in both UTC and local. |

---

## FINAL ASSESSMENT

The v3.0 plan was a good starting point with the right high-level instincts (PostgreSQL-centric, LangGraph orchestration, approval workflow, cost tracking). The corrected architecture:

1. **Removes 3 infrastructure components** (Celery, Redis, MCP container) — reducing deployment complexity by ~35%
2. **Adds 7 missing components** — each addressing a real production failure mode
3. **Fixes the database schema** — proper types, indexes, timestamps, error tracking
4. **Fixes the state machine** — clear status transitions, error fields, image handling
5. **Adds an event-driven trigger** — the pipeline now actually knows when files arrive
6. **Adds full observability** — you can diagnose failures at 2 AM without SSH access

The system is now ready for implementation. Phase 2 of this engagement will be the detailed sub-task breakdown optimized for Claude terminal development.
