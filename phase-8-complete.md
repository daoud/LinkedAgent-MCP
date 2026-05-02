This is the start of our conversation — there's no prior exchange to summarize.

What I can summarize from the **project context** loaded at session start:

**Project:** A LinkedIn post automation pipeline built with FastAPI, LangGraph, PostgreSQL, and the Claude API.

**Architecture:** Content files flow through a 10-node LangGraph pipeline (`extract → dedup → sanitize → transform → validate → schedule → approve → preview → publish → finalize`), with PostgreSQL as the checkpointer and metadata store.

**Key components:**
- Intelligence layer (`src/intelligence/`) — Sanitizer, Transformer, Validator, CostTracker, PromptManager
- LinkedIn OAuth2 client with dry-run support and rate limiting
- Scheduling with slot-based daily limits and SHA-256 dedup
- Local/S3 storage abstraction
- 6 DB tables: `posts`, `content_uploads`, `approvals`, `prompt_templates`, `llm_costs`, `logs`

**Phase status:** Phases 1–8 complete. Phases 9 (Observability/Security) and 10 (Deployment) are stubs only.

**Recent git activity:** Phase 8 (FastAPI service) was the last completed phase, per the most recent commit.

If you meant to reference a previous Claude Code session, that context isn't available here. Let me know what you'd like to work on.
