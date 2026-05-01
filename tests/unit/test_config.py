"""Unit tests for src/config.py — no database required."""

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_valid_settings():
    """Settings loads successfully with pytest-env values."""
    s = Settings()
    assert s.environment == "test"
    assert s.storage_mode == "local"
    assert s.timezone == "UTC"
    assert s.anthropic_api_key == "test-key"


def test_post_slots_list():
    """'09:00,13:00,18:00' parses to three time objects."""
    slots = Settings().post_slots_list
    assert len(slots) == 3
    assert (slots[0].hour, slots[0].minute) == (9, 0)
    assert (slots[1].hour, slots[1].minute) == (13, 0)
    assert (slots[2].hour, slots[2].minute) == (18, 0)


def test_async_database_url_uses_asyncpg():
    """async_database_url converts to the asyncpg driver."""
    url = Settings().async_database_url
    assert "asyncpg" in url
    assert url.startswith("postgresql+asyncpg://")


def test_invalid_storage_mode():
    """STORAGE_MODE must be local|s3|gcs — anything else raises."""
    with pytest.raises(ValidationError, match="STORAGE_MODE"):
        Settings(storage_mode="redis")


def test_invalid_timezone():
    """TIMEZONE must be a valid pytz timezone string."""
    with pytest.raises(ValidationError):
        Settings(timezone="Not/A/Real/Zone")


def test_invalid_post_slots_format():
    """POST_SLOTS with non-HH:MM entries raises ValidationError."""
    with pytest.raises(ValidationError):
        Settings(post_slots="9am,1pm,6pm")


def test_valid_storage_mode_s3():
    assert Settings(storage_mode="s3").storage_mode == "s3"


def test_valid_storage_mode_gcs():
    assert Settings(storage_mode="gcs").storage_mode == "gcs"
