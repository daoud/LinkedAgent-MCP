from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update

from src.approval.queue import ApprovalQueue
from src.approval.slack_notifier import SlackNotifier
from src.config import get_settings
from src.database import AsyncSessionLocal
from src.models.approval import Approval
from src.models.post import Post
from src.pipeline.state import PipelineState

try:
    from langgraph.types import interrupt
except ImportError:  # langgraph < 0.2
    from langgraph.errors import NodeInterrupt as interrupt  # type: ignore[assignment]


async def approve_node(state: PipelineState) -> dict:
    """Enqueue for human approval, then interrupt until a decision arrives."""
    post_id = state["post_id"]
    settings = get_settings()

    approval_id = None
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()

        existing = await session.execute(
            select(Approval)
            .where(Approval.post_id == post_id)
            .order_by(Approval.created_at.desc())
            .limit(1)
        )
        approval = existing.scalar_one_or_none()

        if approval is None:
            queue = ApprovalQueue(session, settings)
            approval = await queue.enqueue(post)
            await session.commit()

            notifier = SlackNotifier(settings)
            await notifier.notify_pending(approval)

        approval_id = approval.id

    # Pause the graph here. On resume, `decision_data` is the value passed to
    # Command(resume=...) — e.g. {"decision": "approved", "decided_by": "sheet"}
    decision_data = interrupt({"approval_id": str(approval_id)})

    decision = "approved"
    decided_by = "api"
    if isinstance(decision_data, dict):
        decision = decision_data.get("decision", "approved")
        decided_by = decision_data.get("decided_by", "api")

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Approval)
            .where(Approval.id == approval_id)
            .values(
                decision=decision,
                decided_at=datetime.now(timezone.utc),
                decided_by=decided_by,
            )
        )
        post_status = "approved" if decision == "approved" else "rejected"
        await session.execute(
            update(Post).where(Post.id == post_id).values(status=post_status)
        )
        await session.commit()

    return {"approval_id": approval_id, "approval_status": decision}
