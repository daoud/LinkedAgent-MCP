"""Runtime schedule configuration — a single DB row, editable from the UI.

On first read the row is seeded from the env ``Settings`` (POST_SLOTS,
DAILY_POST_LIMIT, APPROVAL_REQUIRED, AUTO_PUBLISH_DRY_RUN) so behaviour is
unchanged until someone edits it in the dashboard.

`cached()` returns the last-loaded values without a DB round-trip — used by
the graph's sync routing helper and by anything on a hot path. A scheduler
job refreshes it every poll interval; the API refreshes it on every write.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.schedule_config import ScheduleConfig

_CACHE: dict[str, Any] = {}


def _defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "slots": [t.strip() for t in s.post_slots.split(",") if t.strip()],
        "daily_limit": s.daily_post_limit,
        "weekdays": [0, 1, 2, 3, 4, 5, 6],
        "active_from": None,
        "active_until": None,
        "auto_publish": not s.auto_publish_dry_run,
        "require_approval": s.approval_required,
        "enabled": True,
    }


def _parse_slots(raw: list) -> list[time]:
    out = []
    for s in raw or []:
        try:
            h, m = str(s).strip().split(":")
            hh, mm = int(h), int(m)
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                out.append(time(hh, mm))
        except (ValueError, AttributeError):
            continue
    return sorted(set(out))


def _row_to_dict(row: ScheduleConfig) -> dict[str, Any]:
    return {
        "slots": list(row.slots or []),
        "daily_limit": int(row.daily_limit),
        "weekdays": list(row.weekdays or [0, 1, 2, 3, 4, 5, 6]),
        "active_from": row.active_from,
        "active_until": row.active_until,
        "auto_publish": bool(row.auto_publish),
        "require_approval": bool(row.require_approval),
        "enabled": bool(row.enabled),
    }


async def get_row(session: AsyncSession) -> ScheduleConfig:
    row = (await session.execute(select(ScheduleConfig).limit(1))).scalar_one_or_none()
    if row is None:
        d = _defaults()
        row = ScheduleConfig(
            id=1, slots=d["slots"], daily_limit=d["daily_limit"], weekdays=d["weekdays"],
            auto_publish=d["auto_publish"], require_approval=d["require_approval"], enabled=True,
        )
        session.add(row)
        await session.flush()
    _CACHE.update(_row_to_dict(row))
    return row


async def refresh(session: AsyncSession) -> dict[str, Any]:
    await get_row(session)
    return dict(_CACHE)


def cached() -> dict[str, Any]:
    """Never touches the DB. Falls back to env defaults before the first load."""
    if not _CACHE:
        return _defaults()
    return dict(_CACHE)


async def scheduler_kwargs(session: AsyncSession) -> dict[str, Any]:
    """kwargs for PostScheduler() built from the current config."""
    cfg = await refresh(session)
    return {
        "slots": _parse_slots(cfg["slots"]),
        "daily_limit": cfg["daily_limit"],
        "weekdays": cfg["weekdays"],
        "active_from": _as_date(cfg["active_from"]),
        "active_until": _as_date(cfg["active_until"]),
    }


def _as_date(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return None
