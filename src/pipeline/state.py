from __future__ import annotations

import uuid
from typing import TypedDict


class PipelineState(TypedDict, total=False):
    # --- Input ---
    upload_id: uuid.UUID
    dry_run: bool                    # True = validate only, no LinkedIn API call
    tone: str | None              # compose-time tone override for the transform prompt
    image_path: str | None        # local path to an image to attach on publish
    source: str | None            # how the run was started: watcher|api|compose|compose-text
    title: str | None             # optional human label for the post
    skip_approval: bool           # dashboard "Publish to LinkedIn" after a reviewed dry run

    # --- Post tracking ---
    post_id: uuid.UUID | None

    # --- Content ---
    raw_content: str
    content_hash: str | None

    # --- Sanitization ---
    sanitized_content: str | None
    is_safe: bool
    injection_flags: list[str]

    # --- Transformation ---
    transformed_text: str | None

    # --- Validation ---
    validation_passed: bool
    validation_issues: list[dict]    # {"rule", "message", "severity"}

    # --- Scheduling ---
    scheduled_date: str | None    # ISO date YYYY-MM-DD
    scheduled_slot: str | None    # HH:MM

    # --- Approval ---
    approval_id: uuid.UUID | None
    approval_status: str | None   # pending|approved|rejected|timeout

    # --- Preview ---
    preview_result: dict | None

    # --- Publish ---
    linkedin_post_id: str | None
    image_asset_urn: str | None
    image_warning: str | None

    # --- Error tracking ---
    error: str | None
    failed_node: str | None

    # --- Cost tracking ---
    total_tokens: int
    total_cost_usd: float
