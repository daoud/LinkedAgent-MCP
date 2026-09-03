from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class ContentSource(Base):
    """A place new post files are pulled from (Google Drive folder, S3 prefix, ...)."""

    __tablename__ = "content_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # gdrive | s3 | local
    name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
