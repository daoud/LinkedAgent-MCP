from __future__ import annotations

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.post import Post
from src.pipeline.state import PipelineState
from src.scheduling.dedup import compute_hash, is_duplicate, set_content_hash


async def dedup_node(state: PipelineState) -> dict:
    raw_content = state["raw_content"]
    post_id = state["post_id"]

    h = compute_hash(raw_content)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()

        if await is_duplicate(h, session):
            post.status = "failed"
            post.last_error = "Duplicate content"
            post.failed_at_node = "dedup"
            await session.commit()
            return {
                "content_hash": h,
                "error": "Duplicate content",
                "failed_node": "dedup",
            }

        set_content_hash(post, raw_content)
        await session.commit()

    return {"content_hash": h}
