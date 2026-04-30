# Phase 7: LangGraph Orchestration

## Dependencies
- Phases 1-6 complete (all modules built and tested individually)

## Tasks

### T-7.1: Pipeline State Definition
**Claude: Opus | Tokens: Low**

Create `src/pipeline/state.py`:
- `PipelineState(TypedDict)` — exact fields from architecture doc
- All fields with correct types and defaults
- Used by every LangGraph node

Use Opus — state design determines the entire pipeline's behavior.

### T-7.2: Pipeline Nodes
**Claude: Sonnet | Tokens: Medium (one prompt per node)**

Create each node as a separate file in `src/pipeline/nodes/`:

`extract.py` — `extract_content_node(state) → state`
- Calls `content_reader.read_content(upload_id)`
- Sets `raw_content`, `image_refs`, `content_hash`
- Updates content_uploads.status=processing

`dedup.py` — `dedup_check_node(state) → state`
- Calls `dedup.check_content_duplicate(content_hash)`
- If duplicate: set status=skipped, return
- Conditional edge: if skipped → END

`sanitize.py` — `sanitize_node(state) → state`
- Calls `sanitizer.sanitize_content(raw_content)`
- Updates `raw_content` with sanitized version

`transform.py` — `transform_node(state) → state`
- Calls `transform_content(raw_content, image_refs)`
- Sets `transformed_content`, `tokens_used`, `cost_usd`
- Computes `post_hash`
- Creates `posts` record in DB

`validate.py` — `validate_node(state) → state`
- Calls `validator.validate_post(transformed_content)`
- Checks post_hash duplicate
- If invalid: set status=failed, return
- Conditional edge: if failed → END

`schedule.py` — `schedule_node(state) → state`
- Calls `scheduler.assign_slot(post_id)`
- Sets `scheduled_slot`, `scheduled_date`

`approve.py` — `approve_node(state) → state`
- If `APPROVAL_REQUIRED=false`: skip, set approval_status=approved
- Creates approval_queue record
- Sends Slack notification
- Writes to Google Sheet
- **LangGraph interrupt** — graph pauses here
- On resume: reads decision from state (set by poller)

`preview.py` — `preview_node(state) → state`
- Calls `linkedin_client.publish(dry_run=True)`
- Logs preview result
- No state change (validation only)

`publish.py` — `publish_node(state) → state`
- Calls `linkedin_client.upload_image()` for each image_ref
- Calls `linkedin_client.publish(dry_run=False)`
- Sets `linkedin_post_id`
- Rate limiter check before API call
- On failure: increment retry_count, set error_message

`finalize.py` — `finalize_node(state) → state`
- Updates posts.status=published, linkedin_post_id, published_at
- Updates content_uploads.status=published
- Records LLM cost via cost_tracker
- Writes structured log entry
- Sets status=published

Prompt strategy: Build one node per Claude prompt. Send only `state.py` + the module it calls as context. Never send all nodes at once.

### T-7.3: Graph Assembly
**Claude: Opus | Tokens: Medium**

Create `src/pipeline/graph.py`:
- Imports all nodes
- Defines `StateGraph(PipelineState)`
- Adds all nodes
- Defines edges:
  ```
  START → extract
  extract → dedup
  dedup → sanitize | END (conditional on status)
  sanitize → transform
  transform → validate
  validate → schedule | END (conditional on status)
  schedule → approve
  approve → preview (interrupt + resume)
  preview → publish
  publish → finalize | retry (conditional on error)
  finalize → END
  ```
- Error wrapper: each node wrapped in try/except that sets error_message + failed_at_node
- Retry logic: if retry_count < 3 and node failed, re-enter same node

Create `src/pipeline/checkpointer.py`:
- PostgreSQL checkpointer setup using `langgraph.checkpoint.postgres`
- Connection string from config

Use Opus — graph wiring with conditional edges and interrupts is complex.

### T-7.4: E2E Local Test
**Claude: Sonnet | Tokens: Low**

Create `tests/e2e/test_full_pipeline.py`:
- Place sample markdown in `test_content/`
- Create content_uploads record manually
- Invoke graph with upload_id
- Assert: transforms content, validates, creates approval request
- Manually set approval=approved in DB
- Resume graph
- Assert: publishes (dry_run), finalizes, status=published
- Assert: costs recorded, logs written

## Completion Criteria
- [ ] Each node works individually with mock state
- [ ] Graph compiles and renders Mermaid diagram
- [ ] Full pipeline runs locally with dry_run=True
- [ ] Checkpointer persists state across graph interrupts
- [ ] Retry logic re-enters failed node up to 3 times
- [ ] Conditional edges route correctly (skip duplicates, reject invalid)

## Files Created
```
src/pipeline/__init__.py
src/pipeline/state.py
src/pipeline/graph.py
src/pipeline/checkpointer.py
src/pipeline/nodes/__init__.py
src/pipeline/nodes/extract.py
src/pipeline/nodes/dedup.py
src/pipeline/nodes/sanitize.py
src/pipeline/nodes/transform.py
src/pipeline/nodes/validate.py
src/pipeline/nodes/schedule.py
src/pipeline/nodes/approve.py
src/pipeline/nodes/preview.py
src/pipeline/nodes/publish.py
src/pipeline/nodes/finalize.py
tests/e2e/test_full_pipeline.py
```
