from __future__ import annotations

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.intelligence.prompt_manager import PromptManager
from src.intelligence.transform import Transformer
from src.models.post import Post
from src.pipeline.state import PipelineState


async def transform_node(state: PipelineState) -> dict:
    content = state.get("sanitized_content") or state["raw_content"]
    post_id = state["post_id"]
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        pm = PromptManager(session)
        system_prompt = await pm.render("linkedin_post", {})

    transformer = Transformer(api_key=settings.anthropic_api_key)
    result = transformer.transform(content, system_prompt, post_id=post_id)

    prior_tokens = state.get("total_tokens", 0)
    total_tokens = prior_tokens + result.input_tokens + result.output_tokens

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()
        post.transformed_text = result.transformed_text
        post.tokens_used = total_tokens
        await session.commit()

    return {
        "transformed_text": result.transformed_text,
        "total_tokens": total_tokens,
    }
