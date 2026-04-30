# Phase 9: Observability + Security

## Dependencies
- Phase 8 complete (FastAPI running)

## Tasks

### T-9.1: Structured Logging
**Claude: Sonnet | Tokens: Low**

Create `src/observability/logging.py`:
- Configure `structlog` with JSON output
- Fields: timestamp, level, logger, request_id, upload_id, post_id, node_name
- Bind context per pipeline run (upload_id, post_id follow through all logs)
- Log levels: DEBUG for dev, INFO for production
- Output to stdout (K8s collects from stdout)

Integrate into every module — replace all `print()` and basic `logging` with structlog.

### T-9.2: Prometheus Metrics
**Claude: Sonnet | Tokens: Low**

Create `src/observability/metrics.py`:
- Counters:
  - `pipeline_runs_total` (labels: status=success|failed|skipped)
  - `linkedin_publish_total` (labels: status=success|failed, dry_run=true|false)
  - `llm_calls_total` (labels: model, status=success|failed)
- Histograms:
  - `pipeline_duration_seconds`
  - `llm_call_duration_seconds`
- Gauges:
  - `llm_monthly_spend_usd`
  - `linkedin_token_days_remaining`
  - `pending_approvals_count`
  - `daily_posts_remaining`

### T-9.3: OpenTelemetry Tracing
**Claude: Sonnet | Tokens: Low**

Create `src/observability/tracing.py`:
- OpenTelemetry SDK setup
- Create span per LangGraph node
- Trace ID propagated through entire pipeline run
- Export to: console (dev), OTLP endpoint (prod)
- Integrations: SQLAlchemy, httpx/requests, FastAPI

### T-9.4: Secrets Management
**Claude: Opus | Tokens: Low**

Create `src/secrets.py`:
- Abstract `SecretsProvider` with `get_secret(key) → str`
- `EnvSecretsProvider` — reads from env vars (dev/local)
- `AWSSecretsProvider` — reads from AWS Secrets Manager (if AWS)
- Factory: `get_secrets_provider(config) → SecretsProvider`
- Used for: LinkedIn tokens, API keys, DB password
- Integration: config.py uses secrets provider for sensitive values

Use Opus — security architecture requires careful design.

## Completion Criteria
- [ ] All logs are JSON-structured with context
- [ ] `/metrics` endpoint shows all counters/gauges
- [ ] Pipeline run creates traceable span per node
- [ ] Secrets load from env (dev) or AWS Secrets Manager (prod)
- [ ] No plaintext secrets in logs

## Files Created
```
src/observability/__init__.py
src/observability/logging.py
src/observability/metrics.py
src/observability/tracing.py
src/secrets.py
```
