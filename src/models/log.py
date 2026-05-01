from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    post_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("posts.id")
    )
    upload_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_uploads.id")
    )
    node_name: Mapped[Optional[str]] = mapped_column(Text)
    level: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # debug|info|warning|error|critical
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # "metadata" is reserved by SQLAlchemy's DeclarativeBase; mapped to "metadata" column via alias
    log_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
