from __future__ import annotations

import uuid
from typing import Optional, TypedDict


class PipelineState(TypedDict, total=False):
    # --- Input ---
    upload_id: uuid.UUID
    dry_run: bool                    # True = validate only, no LinkedIn API call

    # --- Post tracking ---
    post_id: Optional[uuid.UUID]

    # --- Content ---
    raw_content: str
    content_hash: Optional[str]

    # --- Sanitization ---
    sanitized_content: Optional[str]
    is_safe: bool
    injection_flags: list[str]

    # --- Transformation ---
    transformed_text: Optional[str]

    # --- Validation ---
    validation_passed: bool
    validation_issues: list[dict]    # {"rule", "message", "severity"}

    # --- Scheduling ---
    scheduled_date: Optional[str]    # ISO date YYYY-MM-DD
    scheduled_slot: Optional[str]    # HH:MM

    # --- Approval ---
    approval_id: Optional[uuid.UUID]
    approval_status: Optional[str]   # pending|approved|rejected|timeout

    # --- Preview ---
    preview_result: Optional[dict]

    # --- Publish ---
    linkedin_post_id: Optional[str]

    # --- Error tracking ---
    error: Optional[str]
    failed_node: Optional[str]

    # --- Cost tracking ---
    total_tokens: int
    total_cost_usd: float
