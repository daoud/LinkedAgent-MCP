# Architecture Reference

## Data Flow

```
[Content File]
  → Upload to Storage (S3/Local)
  → PostgreSQL: content_uploads record (status=pending)
  → Event trigger → FastAPI /pipeline/trigger
  → LangGraph StateGraph:
      extract_content → dedup_check → sanitize → transform (LLM)
      → validate → schedule_slot → await_approval → preview
      → publish → finalize
  → LinkedIn API: post published
  → PostgreSQL: status=published, cost recorded
```

## Storage Abstraction

```
StorageClient (ABC)
  ├── LocalStorageClient    → ./test_content/ (dev)
  ├── S3StorageClient       → AWS S3 (production option A)
  └── GCSStorageClient      → Google Cloud Storage (production option B)
```

Selected at runtime via `STORAGE_MODE` env var.

## PostgreSQL Schema

### content_uploads
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| file_name | TEXT NOT NULL | |
| storage_path | TEXT NOT NULL | S3 URL or local path |
| storage_type | TEXT NOT NULL | cloud / local |
| mime_type | TEXT | |
| file_type | TEXT NOT NULL | document / image / markdown / text |
| content_hash | TEXT NOT NULL | SHA256 for dedup |
| file_size_bytes | BIGINT | |
| status | TEXT NOT NULL | pending / processing / published / failed / skipped |
| error_message | TEXT | |
| uploaded_at | TIMESTAMPTZ | |
| processed_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | auto-updated trigger |

### posts
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| upload_id | UUID FK → content_uploads | |
| raw_content | TEXT | |
| transformed_text | TEXT | |
| post_hash | TEXT UNIQUE | dedup on transformed output |
| scheduled_slot | TIME | |
| scheduled_date | DATE | |
| linkedin_post_id | TEXT | |
| status | TEXT NOT NULL | pending / processing / awaiting_approval / approved / rejected / publishing / published / failed |
| retry_count | INT DEFAULT 0 | |
| last_error | TEXT | |
| failed_at_node | TEXT | LangGraph node name |
| tokens_used | INT | |
| cost_usd | NUMERIC(8,6) | |
| created_at | TIMESTAMPTZ | |
| published_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### approval_queue
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| post_id | UUID FK → posts | |
| preview_text | TEXT NOT NULL | |
| scheduled_at | TIMESTAMPTZ | |
| decision | TEXT NOT NULL | pending / approved / rejected / timeout |
| decided_by | TEXT | |
| decided_at | TIMESTAMPTZ | |
| expires_at | TIMESTAMPTZ | auto-reject deadline |
| created_at | TIMESTAMPTZ | |

### logs
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| post_id | UUID FK → posts (nullable) | |
| upload_id | UUID FK → content_uploads (nullable) | |
| node_name | TEXT | LangGraph node |
| level | TEXT NOT NULL | debug / info / warning / error / critical |
| message | TEXT NOT NULL | |
| metadata | JSONB | structured extra data |
| created_at | TIMESTAMPTZ | |

### prompt_templates
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| name | TEXT NOT NULL | |
| version | INT NOT NULL | |
| template_text | TEXT NOT NULL | |
| variables | JSONB | expected template vars |
| is_active | BOOLEAN | unique partial index: only one active |
| created_at | TIMESTAMPTZ | |

### llm_costs
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| post_id | UUID FK → posts | |
| model | TEXT NOT NULL | |
| input_tokens | INT NOT NULL | |
| output_tokens | INT NOT NULL | |
| cost_usd | NUMERIC(10,6) NOT NULL | |
| recorded_at | TIMESTAMPTZ | |

## LangGraph PipelineState

```python
class PipelineState(TypedDict):
    upload_id: str
    post_id: str | None
    storage_type: str               # cloud | local
    storage_path: str
    mime_type: str | None
    file_type: str                  # document | image | markdown | text
    raw_content: str | None
    image_refs: list[str]           # storage paths for images
    transformed_content: str | None
    content_hash: str | None
    post_hash: str | None
    scheduled_slot: str | None
    scheduled_date: str | None
    approval_required: bool
    approval_status: str
    linkedin_post_id: str | None
    dry_run: bool
    status: str
    error_message: str | None
    retry_count: int
    failed_at_node: str | None
    tokens_used: int
    cost_usd: float
```

## LangGraph Node Map

```
extract_content
  → dedup_check ──[duplicate]──→ END (status=skipped)
  → sanitize
  → transform (LLM call)
  → validate ──[invalid]──→ END (status=failed)
  → schedule_slot
  → await_approval ──[rejected]──→ END (status=rejected)
  → preview (dry_run=True)
  → publish (dry_run=False)
  → finalize
  → END (status=published)

Any node failure with retry_count < 3 → retry same node
Any node failure with retry_count >= 3 → END (status=failed, alert)
```

## Environment Variables

```
ENVIRONMENT=development|staging|production
TIMEZONE=Asia/Riyadh

# Storage
STORAGE_MODE=local|s3|gcs
LOCAL_CONTENT_DIR=./test_content/
AWS_S3_BUCKET=your-bucket
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/pipeline

# LinkedIn
LINKEDIN_CLIENT_ID=...
LINKEDIN_CLIENT_SECRET=...
LINKEDIN_ACCESS_TOKEN=...
LINKEDIN_REFRESH_TOKEN=...
LINKEDIN_PROFILE_URN=urn:li:person:...

# LLM
ANTHROPIC_API_KEY=...
LLM_MODEL=claude-sonnet-4-20250514
LLM_MONTHLY_BUDGET=20.00

# Scheduling
DAILY_POST_LIMIT=3
POST_SLOTS=09:00,13:00,18:00
APPROVAL_TIMEOUT_H=24
APPROVAL_REQUIRED=true

# Approval
GOOGLE_SHEETS_CREDENTIALS_FILE=./credentials.json
GOOGLE_SHEET_ID=...
SLACK_WEBHOOK_URL=...

# Observability
LOG_LEVEL=INFO
ENABLE_METRICS=true
```
