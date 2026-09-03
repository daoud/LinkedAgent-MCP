from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.models.post import Post

_ALL_WEEKDAYS = [0, 1, 2, 3, 4, 5, 6]


class PostScheduler:
    """Assigns posts to the next available publish slot in the configured timezone.

    Slots / daily limit / active weekdays / date window come from the runtime
    ``schedule_config`` row when the caller passes them in; otherwise they fall
    back to the env ``Settings`` (POST_SLOTS, DAILY_POST_LIMIT).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        slots: list[time] | None = None,
        daily_limit: int | None = None,
        weekdays: list[int] | None = None,
        active_from: date | None = None,
        active_until: date | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._tz = pytz.timezone(self._settings.timezone)
        self._slots = sorted(set(slots)) if slots is not None else self._settings.post_slots_list
        self._daily_limit = daily_limit if daily_limit is not None else self._settings.daily_post_limit
        self._weekdays = weekdays if weekdays else _ALL_WEEKDAYS
        self._active_from = active_from
        self._active_until = active_until

    def _now_local(self) -> datetime:
        return datetime.now(self._tz)

    def _today_local(self) -> date:
        return self._now_local().date()

    async def assign_slot(self, post: Post, session: AsyncSession) -> tuple[date, time]:
        """Find the next free (date, slot) and write it onto *post*."""
        today = self._today_local()
        target_date = today
        for _ in range(400):
            if self._date_is_active(target_date):
                slot = await self._first_free_slot(target_date, session, is_today=target_date == today)
                if slot is not None:
                    post.scheduled_date = target_date
                    post.scheduled_slot = slot
                    return target_date, slot
            target_date += timedelta(days=1)
        raise RuntimeError("No available scheduling slot found within ~13 months")

    def _date_is_active(self, d: date) -> bool:
        if d.weekday() not in self._weekdays:
            return False
        if self._active_from and d < self._active_from:
            return False
        if self._active_until and d > self._active_until:
            return False
        return True

    async def _first_free_slot(
        self, target_date: date, session: AsyncSession, *, is_today: bool
    ) -> time | None:
        occupied = await self._occupied_slots(target_date, session)
        if len(occupied) >= self._daily_limit:
            return None
        now_t = self._now_local().time() if is_today else None
        available = [
            s for s in self._slots
            if s not in occupied and (now_t is None or s > now_t)
        ]
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
