from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.post import Post
from src.observability.log_store import log_event
from src.pipeline.state import PipelineState


async def finalize_node(state: PipelineState) -> dict:
    post_id = state.get("post_id")
    if post_id is None:
        return {}

    dry_run = state.get("dry_run", True)
    error = state.get("error")
    approval_status = state.get("approval_status")
    linkedin_post_id = state.get("linkedin_post_id")

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()

        if error:
            if post.status not in ("failed", "rejected"):
                post.status = "failed"
                post.last_error = post.last_error or error
                post.failed_at_node = post.failed_at_node or state.get("failed_node")
        elif approval_status in ("rejected", "timeout"):
            # approve_node (or ApprovalQueue.expire_timed_out) already set
            # post.status to "rejected"/"failed" — nothing was published,
            # don't overwrite that with "approved"/"published" below.
            pass
        elif dry_run:
            post.status = "approved"
        else:
            post.status = "published"
            post.published_at = post.published_at or datetime.now(UTC)
            if linkedin_post_id:
                post.linkedin_post_id = linkedin_post_id

        final_status = post.status
        await session.commit()

    lvl = "error" if final_status == "failed" else "info"
    msg = f"Pipeline finished — status={final_status}"
    if state.get("image_warning"):
        msg += f" (note: {state['image_warning']})"
    if state.get("error"):
        msg += f" — {state.get('error')}"
    await log_event(lvl, msg, node="finalize", post_id=post_id)

    return {}
