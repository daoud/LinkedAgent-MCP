# Phase 3: LinkedIn Client

## Dependencies
- Phase 1 complete (config + DB)

## Tasks

### T-3.1: LinkedIn OAuth2 Auth Module
**Claude: Sonnet | Tokens: Medium**

Create `src/linkedin/auth.py`:
- `LinkedInAuth` class
- Methods: `get_access_token()`, `refresh_token()`, `is_token_expired() → bool`
- Token storage: read from env vars (dev), extensible to secret manager (prod)
- Auto-refresh: if token expires within 7 days, refresh before use
- Token expiry tracking: parse `expires_in` from OAuth response, store `token_expires_at`
- Scopes required: `w_member_social`, `r_liteprofile`

Create `scripts/linkedin_first_auth.py`:
- One-time browser-based OAuth2 flow
- Opens browser → user authorizes → callback captures code → exchanges for tokens
- Prints tokens to console for `.env` insertion
- Uses `http.server` for local callback (port 8080)

### T-3.2: LinkedIn API Client
**Claude: Sonnet | Tokens: Medium**

Create `src/linkedin/client.py`:
- `LinkedInClient` class, accepts `LinkedInAuth` instance
- `publish(text, media_urns=None, dry_run=True) → dict`
  - dry_run=True: validate payload, return preview, do NOT call API
  - dry_run=False: POST to LinkedIn UGC API, return `linkedin_post_id`
- `upload_image(image_bytes, filename) → media_urn`
  - Register upload → upload binary → return URN
- `delete_post(post_id) → bool`
- `get_profile() → dict` (profile URN, name)
- All methods use `LinkedInAuth.get_access_token()` for auth header

Create `src/linkedin/rate_limiter.py`:
- Token bucket rate limiter (in-memory)
- Parse `X-RateLimit-Limit` and `X-RateLimit-Remaining` from LinkedIn response headers
- `wait_if_needed()` — blocks if rate limit is close
- Default: max 100 calls/day (LinkedIn's limit for UGC posts)

Create `scripts/check_token_expiry.py`:
- CLI script: reads token, prints days until expiry, warns if < 14 days

## Completion Criteria
- [ ] `linkedin_first_auth.py` completes OAuth flow, prints tokens
- [ ] `LinkedInClient.publish(dry_run=True)` returns valid preview
- [ ] `LinkedInClient.get_profile()` returns profile URN
- [ ] Rate limiter blocks when limit approached
- [ ] Token refresh works before expiry

## Files Created
```
src/linkedin/__init__.py
src/linkedin/auth.py
src/linkedin/client.py
src/linkedin/rate_limiter.py
scripts/linkedin_first_auth.py
scripts/check_token_expiry.py
tests/unit/test_linkedin_auth.py
tests/unit/test_linkedin_client.py
tests/unit/test_rate_limiter.py
```
