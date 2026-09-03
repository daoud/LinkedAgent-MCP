from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class ScheduleConfig(Base):
    """Single editable row driving how many posts go out and when."""

    __tablename__ = "schedule_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slots: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    weekdays: Mapped[list] = mapped_column(JSONB, nullable=False, default=lambda: [0, 1, 2, 3, 4, 5, 6])
    active_from: Mapped[date | None] = mapped_column(Date)
    active_until: Mapped[date | None] = mapped_column(Date)
    auto_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
