from __future__ import annotations

from datetime import datetime

import pytz
from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.models.post import Post
from src.pipeline.state import PipelineState
from src.scheduling.scheduler import PostScheduler

try:
    from langgraph.types import interrupt
except ImportError:  # langgraph < 0.2
    from langgraph.errors import NodeInterrupt as interrupt


async def wait_for_slot_node(state: PipelineState) -> dict:
    """Pause the graph until the post's assigned slot time arrives.

    Runs after approval (or right after scheduling, when approval isn't
    required) and before preview/publish. Without this, DAILY_POST_LIMIT and
    POST_SLOTS only ever get *recorded* on the post — this is what makes them
    actually space posts out across the day instead of publishing back-to-back
    the moment a post is approved. Resumed by the scheduled-post poller in
    api/app.py once the slot time is due.
    """
    post_id = state["post_id"]
    settings = get_settings()
    tz = pytz.timezone(settings.timezone)
    scheduler = PostScheduler(settings)

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()

        if post.scheduled_date is None or post.scheduled_slot is None:
            return {}  # nothing was scheduled — proceed immediately

        slot_at = scheduler.next_run_time(post.scheduled_date, post.scheduled_slot)
        if datetime.now(tz) >= slot_at:
            return {}

        if post.status not in ("failed", "rejected"):
            post.status = "scheduled"
            await session.commit()

    interrupt({"wait_until": slot_at.isoformat()})
    return {}
