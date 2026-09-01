from __future__ import annotations

import uuid

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.approval import Approval
from src.models.post import Post

try:
    from langgraph.types import Command
except ImportError:  # langgraph < 0.2
    from langgraph.pregel import Command  # type: ignore[assignment]


async def resume_pipeline_thread(graph, thread_id: str, resume_value=True) -> None:
    """Resume a graph paused at any interrupt() call on the given thread_id."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        async for _ in graph.astream(Command(resume=resume_value), config=config):
            pass
    except Exception as exc:
        print(f"[pipeline] Resume error for thread {thread_id}: {exc}")


async def resume_pipeline_for_approval(
    graph, approval_id: uuid.UUID, decision: str, decided_by: str
) -> None:
    """Resume a graph paused at the approve node's interrupt() for this approval.

    Shared by the manual /pipeline/approve route and the Sheets approval poller
    so both drive the same thread_id convention (f"upload-{upload_id}").
    """
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Approval).where(Approval.id == approval_id))
        approval = r.scalar_one_or_none()
        if approval is None:
            return
        r2 = await session.execute(select(Post).where(Post.id == approval.post_id))
        post = r2.scalar_one_or_none()
        if post is None or post.upload_id is None:
            return
        upload_id = post.upload_id

    await resume_pipeline_thread(
        graph,
        f"upload-{upload_id}",
        resume_value={"decision": decision, "decided_by": decided_by},
    )
