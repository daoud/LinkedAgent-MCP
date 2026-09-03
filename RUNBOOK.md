# RUNBOOK — Run the pipeline and publish a LinkedIn post

This is a step-by-step guide for a **human or an AI agent** to take this project
from a clean checkout to a live post on LinkedIn.

- If anything here disagrees with `CLAUDE.md` or `README.md`, this file is the
  operational source of truth for *posting*; those are the architectural
  references.
- Every shell command assumes you are in the repo root
  (`.../LinkedIn/MCP`) unless stated otherwise.

---

## 1. What this system does

```
content file (.md/.txt/.pdf)
   → extract → dedup → sanitize → transform (Claude rewrites it as a LinkedIn post)
   → validate → schedule (assigns a time slot) → approve (human gate)
   → preview → publish (LinkedIn UGC API) → finalize
```

- The pipeline is a LangGraph state machine (`src/pipeline/graph.py`), 11 nodes.
- State + resumability live in **PostgreSQL** (no Redis/Celery). Postgres runs in
  Docker on **port 5433**.
- A FastAPI service (`:8000`) exposes trigger / status / approve endpoints and
  runs the background scheduler + folder watcher.
- **Every publish is a dry run by default.** You have to explicitly ask for a
  live post (`dry_run=false`).

---

## 2. Prerequisites (software)

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ (3.13 works) | `python3 --version` |
| Docker + Docker Compose | any recent | `docker info` |
| `make` | any | `make --version` |
| A virtualenv at `./venv` | — | `ls venv/bin/python` |

Create the venv if it does not exist:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

---

## 3. Credentials & external APIs

Copy the template and fill it in:

```bash
cp .env.example .env
```

### 3.1 Required

| Env var(s) | API / service | Where to get it | Cost | Expiry / rotation |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | **Anthropic Claude API** — used by the sanitize / transform / validate nodes to rewrite content into a LinkedIn post. | <https://console.anthropic.com> → *API Keys* → *Create Key*. Starts with `sk-ant-...`. | Pay-as-you-go. ~**$0.01 per post** with `claude-sonnet-5`. A monthly ceiling is enforced by `LLM_MONTHLY_BUDGET` (default `$20.00`) — the transform node fails closed when exceeded. | **No expiry.** Valid until you revoke it in the console. Rotate by creating a new key and replacing the value. |
| `LLM_MODEL` | (not a credential) | Model id string. Must be a current model — **`claude-sonnet-5`**. The old `claude-sonnet-4-20250514` now returns HTTP 404. | — | — |
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | **LinkedIn app** (OAuth2 client). | <https://www.linkedin.com/developers/apps> → *Create app* (needs a LinkedIn Company Page). In the app: *Products* → add **“Share on LinkedIn”** and **“Sign In with LinkedIn using OpenID Connect”**. *Auth* tab shows the Client ID / Secret. | Free. | Client secret does not expire but LinkedIn lets you rotate it in the *Auth* tab. |
| `LINKEDIN_ACCESS_TOKEN` | **LinkedIn OAuth2 access token** — bearer token for `POST /v2/ugcPosts`. | Run the helper (section 3.3). Scopes requested: `w_member_social openid profile`. | Free. | **~60 days** from issue. Stored as a Unix timestamp in `LINKEDIN_TOKEN_EXPIRES_AT`. The current token in `.env` expires **2026-11-01** (`1793525314`). |
| `LINKEDIN_REFRESH_TOKEN` | LinkedIn refresh token. | Same helper. Only issued if your app is approved for refresh tokens; otherwise blank and you re-run the helper every ~60 days. | Free. | ~365 days. |
| `LINKEDIN_TOKEN_EXPIRES_AT` | (derived) | Unix seconds; the helper prints it. `LinkedInAuth` auto-refreshes when within 7 days of this, **if** a refresh token is present. | — | — |
| `LINKEDIN_PROFILE_URN` | LinkedIn person URN — the post author. | Printed by the helper as `urn:li:person:XXXX` (from `GET /v2/me`). | — | Stable for the account. |
| `DATABASE_URL` | PostgreSQL | Leave the default: `postgresql://pipeline:pipeline@localhost:5433/pipeline`. `make up` starts this container. | — | — |

### 3.2 Optional — the approval workflow

The human-approval gate can post a card to Google Sheets + Slack and read the
decision back. It is **off unless `GOOGLE_SHEET_ID` is set**.

| Env var | Service | Where to get it |
|---|---|---|
| `GOOGLE_SHEETS_CREDENTIALS_FILE`, `GOOGLE_SHEET_ID` | Google Sheets API (service account) | <https://console.cloud.google.com> → enable *Google Sheets API* → create a **service account** → download JSON to `./credentials.json` → share the target Sheet with the service-account email → put the Sheet ID (from its URL) in `GOOGLE_SHEET_ID`. |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook | <https://api.slack.com/apps> → your app → *Incoming Webhooks* → *Add New Webhook to Workspace*. |

If you leave these blank (current state), approve posts with the API call in
section 7 instead.

### 3.3 One-time LinkedIn authorization

```bash
./venv/bin/python scripts/linkedin_first_auth.py
```

- Opens a browser, you log in to LinkedIn and authorize the app.
- The callback lands on `http://localhost:8080/auth/callback` — this exact URL
  must be listed under *Authorized redirect URLs* in the app’s *Auth* tab.
- On success it prints `LINKEDIN_ACCESS_TOKEN=`, `LINKEDIN_REFRESH_TOKEN=`,
  `LINKEDIN_TOKEN_EXPIRES_AT=`, `LINKEDIN_PROFILE_URN=` — **paste those four
  lines into `.env`**, replacing any existing values.

---

## 4. One-time setup

```bash
make up        # start PostgreSQL 16 in Docker on :5433, waits until ready
make migrate   # apply Alembic migrations (creates the 6 tables)
make seed      # insert the default prompt template ("linkedin_post")
make test      # sanity check — expect "190 passed"
```

---

## 5. Start the service

```bash
make dev       # uvicorn on http://localhost:8000 (with --reload)
```

Health check (separate terminal):

```bash
curl -s http://localhost:8000/health      # {"status":"ok","database":"ok"}
```

Leave this running. All commands below hit `http://localhost:8000`.

> `API_KEY` is unset by default, so no auth header is needed. If you set it,
> add `-H "X-API-Key: <value>"` to every non-public request.

---

## 6. Post to LinkedIn

### 6.1 Decide: approval on or off

Check `.env`:

- `APPROVAL_REQUIRED=true`  → the pipeline **pauses** at the `approve` node until
  you call the approve endpoint (section 7). This is the default and the safe
  choice.
- `APPROVAL_REQUIRED=false` → the pipeline runs straight through to publish.
  Use this only for a trusted, unattended run. **Restart `make dev` after
  changing `.env`.**

### 6.2 Decide: dry run or live

- `dry_run=true` (default everywhere) — runs the whole pipeline, validates the
  LinkedIn payload, **does not call LinkedIn**. The post ends in status
  `approved`.
- `dry_run=false` — actually publishes. The post ends in status `published`
  with a `linkedin_post_id`.

### 6.3 Trigger the pipeline

**Option A — upload a file through the API (recommended):**

```bash
curl -s -X POST "http://localhost:8000/pipeline/upload?dry_run=false" \
  -F "file=@test_content/my_post.md;type=text/markdown"
# → {"status":"accepted","upload_id":"<UUID>","thread_id":"upload-<UUID>"}
```

**Option B — drop a file in the watched folder:**

```bash
cp my_post.md test_content/
```

The folder watcher registers it and the background poller triggers the pipeline
within ~60s. **This path always uses `AUTO_PUBLISH_DRY_RUN`** (default `true`) —
set that to `false` in `.env` for the watcher to publish live.

**Option C — trigger an already-registered upload:**

```bash
curl -s -X POST http://localhost:8000/pipeline/trigger \
  -H 'Content-Type: application/json' \
  -d '{"upload_id":"<UUID>","dry_run":false}'
```

### 6.4 Find the post id

The trigger response gives you `upload_id`, not `post_id`. Get the post id:

```bash
docker compose exec -T postgres psql -U pipeline -d pipeline -tAc \
  "SELECT id, status FROM posts WHERE upload_id='<UPLOAD_UUID>' ORDER BY created_at DESC LIMIT 1;"
```

Then poll status any time:

```bash
curl -s http://localhost:8000/pipeline/status/<POST_UUID> | python3 -m json.tool
```

`status` walks through: `processing → awaiting_approval → scheduled → publishing → published`
(or `failed` with `last_error` + `failed_at_node`).

---

## 7. The approval step (`APPROVAL_REQUIRED=true`)

When status is `awaiting_approval`, get the approval id:

```bash
docker compose exec -T postgres psql -U pipeline -d pipeline -tAc \
  "SELECT id FROM approval_queue WHERE post_id='<POST_UUID>' ORDER BY created_at DESC LIMIT 1;"
```

(Or read it from the Slack card if Slack is configured.)

Approve (this resumes the paused graph → preview → publish):

```bash
curl -s -X POST http://localhost:8000/pipeline/approve/<APPROVAL_UUID> \
  -H 'Content-Type: application/json' \
  -d '{"decision":"approved","decided_by":"your-name"}'
```

Reject with `{"decision":"rejected", ...}` — the post ends `rejected`, nothing is
published.

> If `APPROVAL_TIMEOUT_H` (default 24) passes with no decision, the post times
> out and is not published.

### Scheduling note

`schedule_node` assigns the next free slot from `POST_SLOTS` (default
`09:00,13:00,18:00`, timezone `TIMEZONE`). After approval, `wait_for_slot`:

- **slot time already passed today** → publishes immediately.
- **slot time is in the future** → the post sits in `scheduled` until the
  background poller resumes it at slot time (checked every ~60s).

To publish right now regardless, either add a slot time a minute in the future
to `POST_SLOTS` and restart, or manually set the post’s `scheduled_slot` to a
past time.

---

## 8. Editing the post before it goes live

The `transform` node rewrites your source content with Claude — the result is
**not** verbatim your input. Three ways to control the final text:

1. **Edit the source, before triggering.** Rewrite `test_content/my_post.md` and
   trigger. Claude still rephrases, but works from your copy.

2. **Tune the prompt template.** The rewrite is driven by the `linkedin_post`
   row in the `prompt_templates` table (seeded from
   `scripts/seed_prompt_template.py` → `DEFAULT_TEMPLATE`). Edit that text and
   re-seed, or `UPDATE prompt_templates SET template_text='...' WHERE name='linkedin_post';`

3. **Edit the exact final text during the approval pause** (needs
   `APPROVAL_REQUIRED=true`). While status is `awaiting_approval`:

   ```bash
   docker compose exec -T postgres psql -U pipeline -d pipeline -c \
     "UPDATE posts SET transformed_text='<your exact final post text>' WHERE id='<POST_UUID>';"
   ```

   Then approve. `preview_node` and `publish_node` read `transformed_text` from
   the row at publish time, so your edit is exactly what gets posted. (Verify
   with `GET /pipeline/status/<id>` — or re-select the row — before approving.)

To see the current draft:

```bash
docker compose exec -T postgres psql -U pipeline -d pipeline -x -c \
  "SELECT status, transformed_text FROM posts WHERE id='<POST_UUID>';"
```

---

## 9. Verify on LinkedIn

On a live publish, status becomes `published` and `linkedin_post_id` is set,
e.g. `urn:li:share:7501237736646017025`. Open it at:

```
https://www.linkedin.com/feed/update/<linkedin_post_id>
```

The server log also shows `POST https://api.linkedin.com/v2/ugcPosts "HTTP/1.1 201 Created"`.

---

## 10. Retry a failed post

```bash
curl -s -X POST "http://localhost:8000/pipeline/retry/<POST_UUID>?dry_run=false"
```

Retry **reuses the same post row** (it does not create a duplicate) and re-runs
the whole pipeline from `extract`, clearing the previous error and draft first.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `status=failed`, `failed_at_node=transform`, error mentions `model: claude-sonnet-4-...` or `404` | Stale `LLM_MODEL` in `.env`. | Set `LLM_MODEL=claude-sonnet-5`, restart `make dev`, then `POST /pipeline/retry/<id>`. |
| `status=failed`, `failed_at_node=dedup`, `last_error=Duplicate content` | This exact source text was already published (matched on SHA-256 of raw content). | Change the content, or if it was a mistake: `DELETE FROM posts WHERE post_hash='<hash>' AND status='published'` is **not** advisable — instead edit the source so it differs. |
| Stuck at `awaiting_approval` forever | `APPROVAL_REQUIRED=true` and no Sheet configured, so nothing auto-approves. | Call `POST /pipeline/approve/<approval_id>` (section 7), or set `APPROVAL_REQUIRED=false` and retry. |
| Stuck at `scheduled` | Assigned slot time is in the future. | Wait for the slot, or adjust `POST_SLOTS` / the row’s `scheduled_slot`. |
| `401` from LinkedIn on publish; `failed_at_node=publish` | Access token expired (>60 days) or missing scope. | Re-run `scripts/linkedin_first_auth.py`, update the 4 `LINKEDIN_*` lines in `.env`, restart, retry. |
| `transform` fails with “Monthly LLM budget … exceeded” | `llm_costs` for the month ≥ `LLM_MONTHLY_BUDGET`. | Raise `LLM_MONTHLY_BUDGET` or wait for the next month. |
| Publish fails “interrupted after the LinkedIn API call may have been made” | Process died mid-publish; system fails closed to avoid a double post. | Check LinkedIn manually. If nothing posted, clear `status`/`linkedin_post_id` on the row and retry. If it did post, set `status='published'` + the `linkedin_post_id`. |
| Folder-drop file ignored | Name starts with `.`/`_`/`~`, or a duplicate `content_hash`/`file_name` already exists. | Rename / change content. |

Reset the whole local DB (destroys all post history):

```bash
make clean && make up && make migrate && make seed
```

---

## 12. Condensed sequence for an AI agent

Assumes `.env` is filled (section 3), venv exists, Docker is running.

```bash
# --- setup ---
make up && make migrate && make seed

# --- config for an immediate live post, no human gate ---
#   in .env set:  APPROVAL_REQUIRED=false   LLM_MODEL=claude-sonnet-5
#   ensure POST_SLOTS has a time earlier than "now" in TIMEZONE (default
#   09:00 usually satisfies this) so wait_for_slot passes through.

# --- start API ---
nohup ./venv/bin/python -m uvicorn src.api.app:app --port 8000 > /tmp/uvicorn.log 2>&1 &
until curl -sf http://localhost:8000/health >/dev/null; do sleep 1; done

# --- publish ---
UP=$(curl -s -X POST "http://localhost:8000/pipeline/upload?dry_run=false" \
      -F "file=@test_content/my_post.md;type=text/markdown" | python3 -c 'import sys,json;print(json.load(sys.stdin)["upload_id"])')

# --- wait for terminal state, then read result ---
until docker compose exec -T postgres psql -U pipeline -d pipeline -tAc \
  "SELECT status FROM posts WHERE upload_id='$UP'" | grep -qE 'published|failed|rejected'; do sleep 3; done
docker compose exec -T postgres psql -U pipeline -d pipeline -x -c \
  "SELECT status, linkedin_post_id, last_error, failed_at_node FROM posts WHERE upload_id='$UP';"
```

If `APPROVAL_REQUIRED=true` instead, insert between upload and wait:

```bash
POST=$(docker compose exec -T postgres psql -U pipeline -d pipeline -tAc \
  "SELECT id FROM posts WHERE upload_id='$UP' ORDER BY created_at DESC LIMIT 1;" | tr -d '[:space:]')
# (optional) edit the exact text:
# docker compose exec -T postgres psql -U pipeline -d pipeline -c \
#   "UPDATE posts SET transformed_text='...' WHERE id='$POST';"
until docker compose exec -T postgres psql -U pipeline -d pipeline -tAc \
  "SELECT status FROM posts WHERE id='$POST'" | grep -q awaiting_approval; do sleep 3; done
APPR=$(docker compose exec -T postgres psql -U pipeline -d pipeline -tAc \
  "SELECT id FROM approval_queue WHERE post_id='$POST' ORDER BY created_at DESC LIMIT 1;" | tr -d '[:space:]')
curl -s -X POST "http://localhost:8000/pipeline/approve/$APPR" \
  -H 'Content-Type: application/json' -d '{"decision":"approved","decided_by":"agent"}'
```

---

## 13. Endpoint reference

| Method + path | Body / query | Purpose |
|---|---|---|
| `GET /health` | — | Liveness + DB check (public, no API key). |
| `POST /pipeline/upload?dry_run=<bool>` | multipart `file=@...` | Register a file and run the pipeline. |
| `POST /pipeline/trigger` | `{"upload_id","dry_run"}` | Run the pipeline for an already-registered upload. |
| `GET /pipeline/status/{post_id}` | — | Full post state (status, error, tokens, cost, schedule, `linkedin_post_id`). |
| `POST /pipeline/approve/{approval_id}` | `{"decision","decided_by"}` | `approved` / `rejected`; resumes the paused graph. |
| `POST /pipeline/retry/{post_id}?dry_run=<bool>` | — | Re-run a failed post on the same row. |
| `GET /prometheus` | — | Prometheus metrics (public). `/metrics` is behind the API key. |
