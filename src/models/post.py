from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    upload_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_uploads.id")
    )
    raw_content: Mapped[Optional[str]] = mapped_column(Text)
    transformed_text: Mapped[Optional[str]] = mapped_column(Text)
    post_hash: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    scheduled_slot: Mapped[Optional[time]] = mapped_column(Time)
    scheduled_date: Mapped[Optional[date]] = mapped_column(Date)
    linkedin_post_id: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )  # pending|processing|awaiting_approval|approved|rejected|publishing|published|failed
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    failed_at_node: Mapped[Optional[str]] = mapped_column(Text)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    cost_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
