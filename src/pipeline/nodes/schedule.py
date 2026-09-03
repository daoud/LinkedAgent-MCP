from __future__ import annotations

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.post import Post
from src.pipeline.state import PipelineState
from src.scheduling.config import scheduler_kwargs
from src.scheduling.scheduler import PostScheduler


async def schedule_node(state: PipelineState) -> dict:
    post_id = state["post_id"]

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()

        scheduler = PostScheduler(**(await scheduler_kwargs(session)))
        scheduled_date, scheduled_slot = await scheduler.assign_slot(post, session)
        await session.commit()

    return {
        "scheduled_date": scheduled_date.isoformat(),
        "scheduled_slot": scheduled_slot.strftime("%H:%M"),
    }
