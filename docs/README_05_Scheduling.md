# Phase 5: Scheduling + Dedup

## Dependencies
- Phase 1 complete (DB + models)

## Tasks

### T-5.1: Post Scheduler
**Claude: Sonnet | Tokens: Medium**

Create `src/scheduling/scheduler.py`:
- `get_next_available_slot(db_session) → tuple[date, time] | None`
  - Queries posts table for today's published/scheduled count
  - If count >= `DAILY_POST_LIMIT`, check tomorrow
  - Returns next open (date, slot) pair
  - Respects `TIMEZONE` setting — all slot times are in configured timezone
- `assign_slot(post_id, db_session) → tuple[date, time]`
  - Gets next available slot
  - Updates post record with scheduled_date + scheduled_slot
  - Returns assigned slot
- `get_daily_count(target_date, db_session) → int`
- Timezone handling: `POST_SLOTS` interpreted as `TIMEZONE`, stored as UTC in DB

### T-5.2: Deduplication
**Claude: Sonnet | Tokens: Low**

Create `src/scheduling/dedup.py`:
- `check_content_duplicate(content_hash, db_session) → bool`
  - Checks content_uploads.content_hash for existing published/processing records
- `check_post_duplicate(post_hash, db_session) → bool`
  - Checks posts.post_hash for existing records
- `compute_hash(text) → str` — SHA256 of normalized text (stripped whitespace, lowercased)
- Both return True if duplicate found

## Completion Criteria
- [ ] Scheduler assigns correct slots respecting daily limit
- [ ] Scheduler rolls to next day when today is full
- [ ] Timezone conversion is correct (AST → UTC)
- [ ] Content dedup catches identical uploads
- [ ] Post dedup catches identical transformed text

## Files Created
```
src/scheduling/__init__.py
src/scheduling/scheduler.py
src/scheduling/dedup.py
tests/unit/test_scheduler.py
tests/unit/test_dedup.py
```
