from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.intelligence.cost_tracker import CostTracker, calculate_cost
from src.intelligence.validator import Validator
from src.models.post import Post
from src.pipeline.state import PipelineState


async def validate_node(state: PipelineState) -> dict:
    text = state["transformed_text"]
    post_id = state["post_id"]
    settings = get_settings()

    validator = Validator(api_key=settings.anthropic_api_key)
    result = await asyncio.to_thread(validator.validate, text)

    issues = [
        {"rule": i.rule, "message": i.message, "severity": i.severity}
        for i in result.issues
    ]

    total_tokens = state.get("total_tokens", 0) + result.input_tokens + result.output_tokens
    total_cost = float(state.get("total_cost_usd", 0.0))
    if result.model:
        total_cost += float(calculate_cost(result.model, result.input_tokens, result.output_tokens))

    async with AsyncSessionLocal() as session:
        if result.model:
            await CostTracker(session).record(
                post_id, result.model, result.input_tokens, result.output_tokens
            )

        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()
        post.tokens_used = total_tokens
        post.cost_usd = Decimal(str(round(total_cost, 6)))
        if not result.passed:
            first_error = issues[0]["message"] if issues else "unknown"
            post.status = "failed"
            post.last_error = f"Validation failed: {first_error}"
            post.failed_at_node = "validate"
        await session.commit()

    if not result.passed:
        first_error = issues[0]["message"] if issues else "unknown"
        return {
            "validation_passed": False,
            "validation_issues": issues,
            "error": f"Validation failed: {first_error}",
            "failed_node": "validate",
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
        }

    return {
        "validation_passed": True,
        "validation_issues": issues,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
    }
