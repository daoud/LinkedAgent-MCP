from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class ContentUpload(Base):
    __tablename__ = "content_uploads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    storage_type: Mapped[str] = mapped_column(String(16), nullable=False)  # cloud | local
    mime_type: Mapped[Optional[str]] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)  # document|image|markdown|text
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )  # pending|processing|published|failed|skipped
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
