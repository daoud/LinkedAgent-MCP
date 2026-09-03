from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

load_dotenv()

_DEFAULT_URL = "postgresql://pipeline:pipeline@localhost:5433/pipeline"


def _async_url() -> str:
    raw = os.getenv("DATABASE_URL", _DEFAULT_URL)
    for prefix in ("postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if raw.startswith(prefix):
            return "postgresql+asyncpg://" + raw[len(prefix):]
    return raw


if os.getenv("ENVIRONMENT", "").lower() == "test":
    # Tests fire background tasks (pipeline runs, log writes) on transient
    # per-request event loops; a pooled asyncpg connection reused across two
    # loops raises "another operation is in progress". NullPool opens and
    # closes a fresh connection per session, which is safe under that churn.
    engine: AsyncEngine = create_async_engine(_async_url(), poolclass=NullPool, echo=False)
else:
    engine = create_async_engine(_async_url(), pool_size=5, max_overflow=10, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
