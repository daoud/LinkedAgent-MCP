from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.models.post import Post


class PostScheduler:
    """Assigns posts to the next available daily slot in the configured timezone."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._tz = pytz.timezone(self._settings.timezone)

    def _today_local(self) -> date:
        return datetime.now(self._tz).date()

    async def assign_slot(self, post: Post, session: AsyncSession) -> tuple[date, time]:
        """Find the next free (date, slot) and write it onto *post*."""
        target_date = self._today_local()
        for _ in range(365):
            slot = await self._first_free_slot(target_date, session)
            if slot is not None:
                post.scheduled_date = target_date
                post.scheduled_slot = slot
                return target_date, slot
            target_date += timedelta(days=1)
        raise RuntimeError("No available scheduling slot found within one year")

    async def _first_free_slot(self, target_date: date, session: AsyncSession) -> time | None:
        occupied = await self._occupied_slots(target_date, session)
        if len(occupied) >= self._settings.daily_post_limit:
            return None
        slots = self._settings.post_slots_list
        available = [s for s in slots if s not in occupied]
        return available[0] if available else None

    async def _occupied_slots(self, target_date: date, session: AsyncSession) -> list[time]:
        result = await session.execute(
            select(Post.scheduled_slot)
            .where(Post.scheduled_date == target_date)
            .where(Post.scheduled_slot.is_not(None))
            .where(Post.status.notin_(["rejected", "failed"]))
        )
        return [row[0] for row in result.fetchall() if row[0] is not None]

    def next_run_time(self, scheduled_date: date, scheduled_slot: time) -> datetime:
        """Return timezone-aware datetime for when a post should publish."""
        naive = datetime.combine(scheduled_date, scheduled_slot)
        return self._tz.localize(naive)
