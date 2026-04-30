# Phase 10: Docker + CI/CD + Kubernetes

## Dependencies
- Phases 1-9 complete (full pipeline works locally)

## Tasks

### T-10.1: Dockerfile
**Claude: Sonnet | Tokens: Low**

Create `Dockerfile`:
- Multi-stage build:
  - Stage 1 (builder): Python 3.12, install dependencies via uv
  - Stage 2 (runtime): Python 3.12-slim, copy only installed packages + src
- Non-root user (uid 1000)
- HEALTHCHECK: curl http://localhost:8000/health
- Expose port 8000
- Entrypoint: `uvicorn src.api.app:app --host 0.0.0.0 --port 8000`
- Labels: version, commit SHA, build date

Create `.dockerignore`:
- tests/, test_content/, .git/, .env, __pycache__, .venv/

Test: `docker build -t linkedin-publisher . && docker run -p 8000:8000 linkedin-publisher`

### T-10.2: GitHub Actions CI/CD
**Claude: Sonnet | Tokens: Medium**

Create `.github/workflows/ci.yaml`:
- Trigger: push to main, pull request to main
- Jobs:
  1. **lint**: ruff check, black check, mypy
  2. **test**: spin up PostgreSQL service, run pytest with coverage, fail if < 80%
  3. **build**: docker build, tag with commit SHA + branch
  4. **scan**: trivy image scan, fail on HIGH/CRITICAL CVEs
  5. **push**: push to container registry (GitHub Container Registry / ECR)
     - Only on main branch merge
  6. **deploy-staging**: kubectl apply to staging namespace
     - Only on main branch merge
  7. **deploy-production**: manual approval gate, then kubectl apply to prod
     - Only on manual trigger after staging verified

### T-10.3: Kubernetes Manifests
**Claude: Sonnet | Tokens: Medium**

Create `k8s/` manifests:

`namespace.yaml` — `linkedin-publisher` namespace

`configmap.yaml` — non-secret env vars:
- ENVIRONMENT, TIMEZONE, STORAGE_MODE, DAILY_POST_LIMIT, POST_SLOTS
- LOG_LEVEL, ENABLE_METRICS

`secrets.yaml` — template (actual values via kubectl or CI/CD):
- DATABASE_URL, ANTHROPIC_API_KEY, LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET
- LINKEDIN_ACCESS_TOKEN, LINKEDIN_REFRESH_TOKEN, AWS keys

`deployment.yaml`:
- 1 replica (single LinkedIn account, no need for multiple)
- Resource requests: 256Mi memory, 250m CPU
- Resource limits: 512Mi memory, 500m CPU
- Liveness probe: GET /health every 30s
- Readiness probe: GET /ready every 10s
- terminationGracePeriodSeconds: 60
- Image pull from registry
- envFrom: configmap + secrets

`service.yaml` — ClusterIP on port 8000

`cronjob.yaml` — backup job:
- Schedule: daily at 02:00 UTC
- pg_dump → upload to cloud storage bucket

`ingress.yaml` — optional, for external trigger endpoint:
- TLS termination
- Path: /pipeline/trigger → service:8000

### T-10.4: Production Checklist Script
**Claude: Sonnet | Tokens: Low**

Create `scripts/production_checklist.py`:
- Validates all env vars are set
- Tests DB connection
- Tests LinkedIn token validity + days remaining
- Tests Anthropic API key
- Tests cloud storage access
- Tests Google Sheets access
- Prints GO/NO-GO status for each

## Completion Criteria
- [ ] Docker image builds and runs locally
- [ ] CI pipeline passes: lint, test, build, scan
- [ ] K8s manifests apply to a cluster without errors
- [ ] Health + readiness probes work in K8s
- [ ] Production checklist script validates all dependencies
- [ ] Staging deploy works end-to-end with dry_run=True

## Files Created
```
Dockerfile
.dockerignore
.github/workflows/ci.yaml
k8s/namespace.yaml
k8s/configmap.yaml
k8s/secrets.yaml
k8s/deployment.yaml
k8s/service.yaml
k8s/cronjob.yaml
k8s/ingress.yaml
scripts/production_checklist.py
```
