"""Unit tests for src/scheduling/scheduler.py — no DB required."""
from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from src.config import Settings
from src.models.post import Post
from src.scheduling.scheduler import PostScheduler


@pytest.fixture
def settings():
    return Settings(
        timezone="America/Halifax",
        post_slots="09:00,13:00,18:00",
        daily_post_limit=3,
        database_url="postgresql://pipeline:pipeline@localhost:5433/pipeline",
        anthropic_api_key="test-key",
    )


@pytest.fixture
def scheduler(settings):
    return PostScheduler(settings=settings)


def _mock_session(occupied: list[time]) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = [(s,) for s in occupied]
    session.execute.return_value = result
    return session


def _clock(scheduler, when: datetime):
    """Patch the scheduler's clock (tz-aware). _today_local() derives from it."""
    tz = pytz.timezone("America/Halifax")
    return patch.object(scheduler, "_now_local", return_value=tz.localize(when))


# ---------------------------------------------------------------------------
# Slot assignment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_slot_when_day_empty(scheduler):
    session = _mock_session([])
    post = Post()
    with _clock(scheduler, datetime(2026, 5, 1, 6, 0)):
        d, slot = await scheduler.assign_slot(post, session)
    assert d == date(2026, 5, 1)
    assert slot == time(9, 0)
    assert post.scheduled_date == date(2026, 5, 1)
    assert post.scheduled_slot == time(9, 0)


@pytest.mark.asyncio
async def test_second_slot_when_first_taken(scheduler):
    session = _mock_session([time(9, 0)])
    post = Post()
    with _clock(scheduler, datetime(2026, 5, 1, 6, 0)):
        d, slot = await scheduler.assign_slot(post, session)
    assert slot == time(13, 0)


@pytest.mark.asyncio
async def test_third_slot_when_two_taken(scheduler):
    session = _mock_session([time(9, 0), time(13, 0)])
    post = Post()
    with _clock(scheduler, datetime(2026, 5, 1, 6, 0)):
        d, slot = await scheduler.assign_slot(post, session)
    assert slot == time(18, 0)


@pytest.mark.asyncio
async def test_rolls_over_to_next_day_when_all_slots_full(scheduler):
    """When today's slots are all taken, the post is assigned to tomorrow."""
    today = date(2026, 5, 1)
    tomorrow = date(2026, 5, 2)
    call_count = 0

    async def mock_execute(*args, **kwargs):
        nonlocal call_count
        result = MagicMock()
        if call_count == 0:
            result.fetchall.return_value = [(time(9, 0),), (time(13, 0),), (time(18, 0),)]
        else:
            result.fetchall.return_value = []
        call_count += 1
        return result

    session = AsyncMock()
    session.execute = mock_execute

    post = Post()
    with _clock(scheduler, datetime(today.year, today.month, today.day, 6, 0)):
        d, slot = await scheduler.assign_slot(post, session)

    assert d == tomorrow
    assert slot == time(9, 0)


@pytest.mark.asyncio
async def test_daily_post_limit_respected():
    """When daily_post_limit=2, the third slot is not offered even if free."""
    scheduler = PostScheduler(
        settings=Settings(
            timezone="America/Halifax",
            post_slots="09:00,13:00,18:00",
            daily_post_limit=2,
            database_url="postgresql://pipeline:pipeline@localhost:5433/pipeline",
            anthropic_api_key="test-key",
        )
    )
    today = date(2026, 5, 1)
    call_count = 0

    async def mock_execute(*args, **kwargs):
        nonlocal call_count
        result = MagicMock()
        if call_count == 0:
            result.fetchall.return_value = [(time(9, 0),), (time(13, 0),)]
        else:
            result.fetchall.return_value = []
        call_count += 1
        return result

    session = AsyncMock()
    session.execute = mock_execute

    post = Post()
    with _clock(scheduler, datetime(today.year, today.month, today.day, 6, 0)):
        d, slot = await scheduler.assign_slot(post, session)

    # Today has 2 posts (= limit), so we roll to tomorrow
    assert d == date(2026, 5, 2)
    assert slot == time(9, 0)


# ---------------------------------------------------------------------------
# forward-only spacing + weekdays + date window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skips_slots_earlier_than_now_today(scheduler):
    """A batch dropped mid-afternoon should NOT be assigned the 09:00/13:00 slots."""
    session = _mock_session([])
    post = Post()
    with _clock(scheduler, datetime(2026, 5, 1, 14, 30)):  # 14:30 local
        d, slot = await scheduler.assign_slot(post, session)
    assert d == date(2026, 5, 1)
    assert slot == time(18, 0)  # the only slot still in the future today


@pytest.mark.asyncio
async def test_rolls_to_tomorrow_when_no_future_slot_today(scheduler):
    session = _mock_session([])
    post = Post()
    with _clock(scheduler, datetime(2026, 5, 1, 20, 0)):  # after the last slot
        d, slot = await scheduler.assign_slot(post, session)
    assert d == date(2026, 5, 2)
    assert slot == time(9, 0)


@pytest.mark.asyncio
async def test_skips_inactive_weekdays():
    # weekdays = Mon..Fri only; 2026-05-02 is a Saturday, 05-03 a Sunday
    sched = PostScheduler(
        settings=Settings(
            timezone="America/Halifax", post_slots="09:00", daily_post_limit=5,
            database_url="postgresql://pipeline:pipeline@localhost:5433/pipeline",
            anthropic_api_key="test-key",
        ),
        slots=[time(9, 0)], daily_limit=5, weekdays=[0, 1, 2, 3, 4],
    )
    session = _mock_session([])
    post = Post()
    with _clock(sched, datetime(2026, 5, 1, 20, 0)):  # Fri evening -> next is Mon
        d, slot = await sched.assign_slot(post, session)
    assert d == date(2026, 5, 4)  # Monday


@pytest.mark.asyncio
async def test_respects_active_until():
    sched = PostScheduler(
        settings=Settings(
            timezone="America/Halifax", post_slots="09:00", daily_post_limit=1,
            database_url="postgresql://pipeline:pipeline@localhost:5433/pipeline",
            anthropic_api_key="test-key",
        ),
        slots=[time(9, 0)], daily_limit=1, active_until=date(2026, 5, 1),
    )
    session = _mock_session([time(9, 0)])  # today's only slot is taken
    post = Post()
    with _clock(sched, datetime(2026, 5, 1, 6, 0)):
        with pytest.raises(RuntimeError):
            await sched.assign_slot(post, session)


# ---------------------------------------------------------------------------
# next_run_time
# ---------------------------------------------------------------------------

def test_next_run_time_is_timezone_aware(scheduler):
    dt = scheduler.next_run_time(date(2026, 5, 1), time(9, 0))
    assert dt.tzinfo is not None


def test_next_run_time_correct_local_time(scheduler):
    d = date(2026, 5, 1)
    s = time(9, 0)
    dt = scheduler.next_run_time(d, s)
    assert dt.hour == 9
    assert dt.minute == 0


def test_next_run_time_utc_conversion(scheduler):
    """9:00 America/Halifax in May (ADT = UTC-3) should be 12:00 UTC."""
    dt = scheduler.next_run_time(date(2026, 5, 1), time(9, 0))
    utc_dt = dt.astimezone(pytz.utc)
    assert utc_dt.hour == 12
    assert utc_dt.minute == 0


def test_next_run_time_utc_scheduler():
    utc_sched = PostScheduler(settings=Settings(
        timezone="UTC",
        post_slots="09:00",
        daily_post_limit=1,
        database_url="postgresql://pipeline:pipeline@localhost:5433/pipeline",
        anthropic_api_key="test-key",
    ))
    dt = utc_sched.next_run_time(date(2026, 5, 1), time(9, 0))
    utc_dt = dt.astimezone(pytz.utc)
    assert utc_dt.hour == 9
