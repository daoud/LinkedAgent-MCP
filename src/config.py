from __future__ import annotations

from datetime import time
from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General
    environment: str = "development"
    timezone: str = "UTC"
    log_level: str = "INFO"
    enable_metrics: bool = True

    # Storage
    storage_mode: str = "local"
    local_content_dir: str = "./test_content/"
    aws_s3_bucket: Optional[str] = None
    aws_region: str = "us-east-1"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None

    # Database
    database_url: str = "postgresql://pipeline:pipeline@localhost:5433/pipeline"

    # LinkedIn
    linkedin_client_id: Optional[str] = None
    linkedin_client_secret: Optional[str] = None
    linkedin_access_token: Optional[str] = None
    linkedin_refresh_token: Optional[str] = None
    linkedin_token_expires_at: Optional[str] = None
    linkedin_profile_urn: Optional[str] = None

    # LLM
    anthropic_api_key: str
    llm_model: str = "claude-opus-5"
    llm_monthly_budget: float = 20.0

    # Scheduling
    daily_post_limit: int = 3
    post_slots: str = "09:00,13:00,18:00"
    approval_timeout_h: int = 24
    approval_required: bool = True

    # Auto-publish (folder watcher -> APScheduler pickup, no explicit trigger)
    # Must be explicitly set to false to let the background poller publish for real.
    auto_publish_dry_run: bool = True

    # Approval integrations
    google_sheets_credentials_file: str = "./credentials.json"
    google_sheet_id: Optional[str] = None
    slack_webhook_url: Optional[str] = None

    # API / FastAPI
    api_key: Optional[str] = None
    cors_origins: str = "*"
    scheduler_poll_interval_s: int = 60

    # ---- Validators --------------------------------------------------------

    @field_validator("storage_mode")
    @classmethod
    def validate_storage_mode(cls, v: str) -> str:
        if v not in ("local", "s3", "gcs"):
            raise ValueError(f"STORAGE_MODE must be local|s3|gcs, got: {v!r}")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            import pytz  # noqa: PLC0415

            pytz.timezone(v)
        except Exception:
            raise ValueError(f"Invalid timezone: {v!r}")
        return v

    @field_validator("post_slots")
    @classmethod
    def validate_post_slots(cls, v: str) -> str:
        for entry in v.split(","):
            parts = entry.strip().split(":")
            if len(parts) != 2:
                raise ValueError(f"Invalid POST_SLOTS entry {entry!r} — expected HH:MM")
            h, m = parts
            if not (h.isdigit() and m.isdigit()):
                raise ValueError(f"Non-numeric time in POST_SLOTS: {entry!r}")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                raise ValueError(f"Out-of-range time in POST_SLOTS: {entry!r}")
        return v

    # ---- Computed helpers --------------------------------------------------

    @property
    def post_slots_list(self) -> list[time]:
        return [time(*map(int, s.strip().split(":"))) for s in self.post_slots.split(",")]

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        for prefix in ("postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url

    @property
    def sync_database_url(self) -> str:
        url = self.database_url
        for prefix in ("postgresql+asyncpg://", "postgresql+psycopg3://"):
            if url.startswith(prefix):
                return "postgresql://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
