from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.intelligence.cost_tracker import CostTracker, calculate_cost
from src.intelligence.sanitizer import Sanitizer
from src.models.post import Post
from src.pipeline.state import PipelineState


async def sanitize_node(state: PipelineState) -> dict:
    raw_content = state["raw_content"]
    post_id = state["post_id"]
    settings = get_settings()

    sanitizer = Sanitizer(api_key=settings.anthropic_api_key, model=settings.llm_model)
    result = await asyncio.to_thread(sanitizer.sanitize, raw_content)

    model = result.model or settings.llm_model
    total_tokens = state.get("total_tokens", 0) + result.input_tokens + result.output_tokens
    total_cost = float(state.get("total_cost_usd", 0.0)) + float(
        calculate_cost(model, result.input_tokens, result.output_tokens)
    )

    async with AsyncSessionLocal() as session:
        await CostTracker(session).record(post_id, model, result.input_tokens, result.output_tokens)

        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()
        post.tokens_used = total_tokens
        post.cost_usd = Decimal(str(round(total_cost, 6)))
        if not result.is_safe:
            post.status = "failed"
            post.last_error = f"Content rejected: {', '.join(result.flags)}"
            post.failed_at_node = "sanitize"
        await session.commit()

    if not result.is_safe:
        return {
            "sanitized_content": result.cleaned,
            "is_safe": False,
            "injection_flags": result.flags,
            "error": f"Content rejected: {', '.join(result.flags)}",
            "failed_node": "sanitize",
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
        }

    return {
        "sanitized_content": result.cleaned,
        "is_safe": True,
        "injection_flags": result.flags,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
    }
