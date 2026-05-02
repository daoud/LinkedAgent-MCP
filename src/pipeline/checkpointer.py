from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.config import get_settings


def _psycopg3_url(database_url: str) -> str:
    """Convert any PostgreSQL URL to a bare psycopg3 conninfo string."""
    for prefix in (
        "postgresql+asyncpg://",
        "postgresql+psycopg3://",
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
    ):
        if database_url.startswith(prefix):
            return "postgresql://" + database_url[len(prefix):]
    return database_url


@asynccontextmanager
async def make_checkpointer() -> AsyncGenerator[AsyncPostgresSaver, None]:
    """Yield an initialised AsyncPostgresSaver backed by the configured DB."""
    conninfo = _psycopg3_url(get_settings().database_url)
    async with AsyncPostgresSaver.from_conn_string(conninfo) as saver:
        await saver.setup()
        yield saver
