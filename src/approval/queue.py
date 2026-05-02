from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.models.approval import Approval
from src.models.post import Post


class ApprovalQueue:
    def __init__(self, session: AsyncSession, settings: Optional[Settings] = None) -> None:
        self._session = session
        self._settings = settings or get_settings()

    async def enqueue(self, post: Post) -> Approval:
        """Create an Approval record and set the post status to awaiting_approval."""
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self._settings.approval_timeout_h)
        approval = Approval(
            post_id=post.id,
            preview_text=post.content or "",
            scheduled_at=None,
            decision="pending",
            expires_at=expires_at,
        )
        self._session.add(approval)
        post.status = "awaiting_approval"
        await self._session.flush()
        return approval

    async def get_pending(self) -> list[Approval]:
        """Return all pending approvals that have not yet expired."""
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            select(Approval)
            .where(Approval.decision == "pending")
            .where(Approval.expires_at > now)
            .order_by(Approval.created_at)
        )
        return list(result.scalars().all())

    async def expire_timed_out(self) -> list[Approval]:
        """Mark past-deadline pending approvals as timeout and reject their posts."""
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            select(Approval)
            .where(Approval.decision == "pending")
            .where(Approval.expires_at <= now)
        )
        approvals = list(result.scalars().all())
        for approval in approvals:
            approval.decision = "timeout"
            approval.decided_at = now
            await self._session.execute(
                update(Post)
                .where(Post.id == approval.post_id)
                .values(status="failed", last_error="Approval timed out")
            )
        if approvals:
            await self._session.flush()
        return approvals

    async def record_decision(
        self,
        approval_id: uuid.UUID,
        decision: str,
        decided_by: str = "sheet",
    ) -> Approval:
        """Apply an approve/reject decision and update the linked post's status."""
        result = await self._session.execute(
            select(Approval).where(Approval.id == approval_id)
        )
        approval = result.scalar_one()
        approval.decision = decision
        approval.decided_by = decided_by
        approval.decided_at = datetime.now(timezone.utc)

        new_post_status = "approved" if decision == "approved" else "rejected"
        await self._session.execute(
            update(Post).where(Post.id == approval.post_id).values(status=new_post_status)
        )
        await self._session.flush()
        return approval
