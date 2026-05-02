from __future__ import annotations

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.intelligence.sanitizer import Sanitizer
from src.models.post import Post
from src.pipeline.state import PipelineState


async def sanitize_node(state: PipelineState) -> dict:
    raw_content = state["raw_content"]
    post_id = state["post_id"]
    settings = get_settings()

    sanitizer = Sanitizer(api_key=settings.anthropic_api_key)
    result = sanitizer.sanitize(raw_content)

    if not result.is_safe:
        async with AsyncSessionLocal() as session:
            r = await session.execute(select(Post).where(Post.id == post_id))
            post = r.scalar_one()
            post.status = "failed"
            post.last_error = f"Content rejected: {', '.join(result.flags)}"
            post.failed_at_node = "sanitize"
            await session.commit()

        return {
            "sanitized_content": result.cleaned,
            "is_safe": False,
            "injection_flags": result.flags,
            "error": f"Content rejected: {', '.join(result.flags)}",
            "failed_node": "sanitize",
        }

    return {
        "sanitized_content": result.cleaned,
        "is_safe": True,
        "injection_flags": result.flags,
    }
