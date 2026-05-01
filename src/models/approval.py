from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Approval(Base):
    __tablename__ = "approval_queue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("posts.id"), nullable=False
    )
    preview_text: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )  # pending|approved|rejected|timeout
    decided_by: Mapped[Optional[str]] = mapped_column(Text)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
