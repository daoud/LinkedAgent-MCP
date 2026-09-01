from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.intelligence.cost_tracker import CostTracker, calculate_cost
from src.intelligence.prompt_manager import PromptManager
from src.intelligence.transform import Transformer
from src.models.post import Post
from src.pipeline.state import PipelineState


async def transform_node(state: PipelineState) -> dict:
    content = state.get("sanitized_content") or state["raw_content"]
    post_id = state["post_id"]
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        if await CostTracker(session).is_over_budget(settings.llm_monthly_budget):
            r = await session.execute(select(Post).where(Post.id == post_id))
            post = r.scalar_one()
            post.status = "failed"
            post.last_error = f"Monthly LLM budget (${settings.llm_monthly_budget:.2f}) exceeded"
            post.failed_at_node = "transform"
            await session.commit()
            return {
                "error": "Monthly LLM budget exceeded",
                "failed_node": "transform",
            }

        pm = PromptManager(session)
        system_prompt = await pm.render("linkedin_post", {"content": content, "tone": "professional and insightful"})

    transformer = Transformer(api_key=settings.anthropic_api_key, model=settings.llm_model)
    result = await asyncio.to_thread(transformer.transform, content, system_prompt, post_id=post_id)

    total_tokens = state.get("total_tokens", 0) + result.input_tokens + result.output_tokens
    total_cost = float(state.get("total_cost_usd", 0.0)) + float(
        calculate_cost(result.model, result.input_tokens, result.output_tokens)
    )

    async with AsyncSessionLocal() as session:
        await CostTracker(session).record(post_id, result.model, result.input_tokens, result.output_tokens)
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()
        post.transformed_text = result.transformed_text
        post.tokens_used = total_tokens
        post.cost_usd = Decimal(str(round(total_cost, 6)))
        await session.commit()

    return {
        "transformed_text": result.transformed_text,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
    }
