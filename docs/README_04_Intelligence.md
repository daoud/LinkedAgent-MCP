# Phase 4: Intelligence Layer

## Dependencies
- Phase 1 complete (DB + models for prompt_templates, llm_costs)

## Tasks

### T-4.1: Prompt Template Manager
**Claude: Sonnet | Tokens: Low**

Create `src/intelligence/prompt_manager.py`:
- `get_active_template(db_session) → PromptTemplate`
- `create_template(name, text, variables) → PromptTemplate`
- `activate_template(template_id) → None` (deactivates previous)
- Template rendering: `render(template, **variables) → str`
- Template variables: `{content}`, `{tone}`, `{max_length}`, `{hashtag_count}`, `{cta}`

### T-4.2: Input Sanitizer
**Claude: Opus | Tokens: Low**

Create `src/intelligence/sanitizer.py`:
- `sanitize_content(raw_text) → str`
- Strip prompt injection patterns:
  - "ignore previous instructions"
  - "system:", "assistant:", "human:" prefixes
  - Excessive special characters
  - Hidden unicode characters
- Truncate to max input length (5000 chars before LLM)
- Remove PII patterns (emails, phone numbers) — configurable
- Return cleaned text

Use Opus for this task — prompt injection defense requires nuanced threat modeling.

### T-4.3: LLM Transform Agent
**Claude: Opus | Tokens: Medium**

Create `src/intelligence/transform.py`:
- `transform_content(raw_content, image_refs, db_session) → tuple[str, int, float]`
  - Returns: (transformed_text, tokens_used, cost_usd)
- Uses Anthropic SDK (`anthropic.Anthropic`)
- Loads active prompt template from DB
- Renders template with content
- Calls Claude Sonnet 4
- Parses response
- Calculates cost from token counts
- Handles API errors with retry (3 attempts, exponential backoff)

Prompt template must instruct the LLM to:
- Write in LinkedIn professional tone
- Keep under 3000 characters
- Add 3-5 relevant hashtags at the end
- Include a call-to-action
- Format with line breaks for readability
- Never invent facts not in the source content

Use Opus to design the prompt template and the transform logic.

### T-4.4: Validation Engine
**Claude: Sonnet | Tokens: Medium**

Create `src/intelligence/validator.py`:
- `validate_post(text) → tuple[bool, list[str]]` returns (is_valid, error_list)
- Rules:
  - Max 3000 characters
  - Min 100 characters (reject empty/trivial posts)
  - 3-5 hashtags present
  - No banned words (loaded from `validation_rules.yaml`)
  - No raw URLs without context
  - Emoji count ≤ 5
  - No markdown syntax (headers, bold, links)
  - Post hash uniqueness check against DB

Create `src/intelligence/validation_rules.yaml`:
- banned_words list
- max_chars, min_chars
- max_emojis
- hashtag range

### T-4.5: Cost Tracker
**Claude: Sonnet | Tokens: Low**

Create `src/intelligence/cost_tracker.py`:
- `record_cost(post_id, model, input_tokens, output_tokens, db_session)`
- `get_monthly_spend(db_session) → float`
- `check_budget(db_session) → tuple[bool, float]` returns (within_budget, remaining)
- Alert hook: if monthly spend > 80% of `LLM_MONTHLY_BUDGET`, log warning
- Hard stop: if spend >= 100%, raise `BudgetExceededError`

## Completion Criteria
- [ ] Prompt template CRUD works, active template loads
- [ ] Sanitizer strips injection patterns
- [ ] Transform produces valid LinkedIn post from sample content
- [ ] Validator catches all rule violations
- [ ] Cost tracker records and alerts correctly

## Files Created
```
src/intelligence/__init__.py
src/intelligence/prompt_manager.py
src/intelligence/sanitizer.py
src/intelligence/transform.py
src/intelligence/validator.py
src/intelligence/cost_tracker.py
src/intelligence/validation_rules.yaml
tests/unit/test_sanitizer.py
tests/unit/test_validator.py
tests/unit/test_cost_tracker.py
tests/integration/test_transform_flow.py
```
