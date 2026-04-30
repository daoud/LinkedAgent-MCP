# Phase 6: Approval Workflow

## Dependencies
- Phase 1 complete (DB + models)

## Tasks

### T-6.1: Approval Queue Manager
**Claude: Sonnet | Tokens: Medium**

Create `src/approval/queue.py`:
- `create_approval_request(post_id, preview_text, scheduled_at, db_session) → UUID`
  - Writes to approval_queue with decision=pending
  - Sets `expires_at` = now + `APPROVAL_TIMEOUT_H` hours
  - Returns approval_queue.id
- `check_decision(post_id, db_session) → str | None`
  - Returns: approved / rejected / timeout / None (still pending)
- `expire_stale_approvals(db_session) → int`
  - Finds all pending approvals where `expires_at < now()`
  - Sets decision=timeout
  - Updates posts.status=rejected
  - Returns count of expired
- `get_pending_approvals(db_session) → list[dict]`

### T-6.2: Approval Poller
**Claude: Sonnet | Tokens: Low**

Create `src/approval/poller.py`:
- `ApprovalPoller` class
- `poll_once(db_session) → list[dict]` — checks all pending approvals for decisions
- Reads decisions from Google Sheet (if configured) or DB directly
- Updates approval_queue.decision + decided_at
- Updates posts.status accordingly
- Runs via APScheduler every 5 minutes

### T-6.3: Google Sheets Client
**Claude: Sonnet | Tokens: Medium**

Create `src/approval/sheets_client.py`:
- `SheetsApprovalClient` class
- Uses `gspread` library + service account credentials
- `write_pending_post(post_id, preview_text, scheduled_at)` — appends row to sheet
- `read_decisions() → list[dict]` — reads Approve/Reject column values
- `mark_processed(row_number)` — marks row as processed
- Sheet columns: Post ID | Preview Text | Scheduled At | Decision | Decided At

### T-6.4: Slack Notifier
**Claude: Sonnet | Tokens: Low**

Create `src/approval/slack_notifier.py`:
- `send_approval_notification(post_id, preview_text, scheduled_at)`
  - Posts to Slack webhook with post preview
  - Includes: preview text (truncated to 500 chars), scheduled time, approval sheet link
- `send_alert(message, level="warning")`
  - Generic alert for failures, budget warnings, token expiry

## Completion Criteria
- [ ] Approval request created in DB with correct expiry
- [ ] Stale approvals auto-expire after timeout
- [ ] Google Sheet gets populated with pending posts
- [ ] Poller reads decisions from Sheet and updates DB
- [ ] Slack notification fires when post enters queue

## Files Created
```
src/approval/__init__.py
src/approval/queue.py
src/approval/poller.py
src/approval/sheets_client.py
src/approval/slack_notifier.py
tests/unit/test_approval_queue.py
tests/integration/test_approval_flow.py
```
