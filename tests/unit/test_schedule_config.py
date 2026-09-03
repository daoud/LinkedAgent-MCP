"""Pure-function tests for the runtime schedule config helpers."""
from __future__ import annotations

from datetime import time

from src.scheduling.config import _as_date, _parse_slots


def test_parse_slots_valid():
    assert _parse_slots(["09:00", "13:30", "18:00"]) == [time(9, 0), time(13, 30), time(18, 0)]


def test_parse_slots_sorts_and_dedupes():
    assert _parse_slots(["18:00", "09:00", "09:00"]) == [time(9, 0), time(18, 0)]


def test_parse_slots_drops_garbage():
    assert _parse_slots(["09:00", "nope", "25:00", "12:99", None, ""]) == [time(9, 0)]


def test_parse_slots_empty():
    assert _parse_slots([]) == []
    assert _parse_slots(None) == []


def test_as_date():
    from datetime import date

    assert _as_date(None) is None
    assert _as_date("2026-09-04") == date(2026, 9, 4)
    assert _as_date("garbage") is None
    assert _as_date(date(2026, 1, 1)) == date(2026, 1, 1)


def test_dashboard_valid_slot():
    from src.api.routes.dashboard import _valid_slot

    assert _valid_slot("09:00")
    assert _valid_slot("23:59")
    assert not _valid_slot("24:00")
    assert not _valid_slot("9am")
    assert not _valid_slot("")
