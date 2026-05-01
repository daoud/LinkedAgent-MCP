from __future__ import annotations

import os
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()

_DEFAULT_URL = "postgresql://pipeline:pipeline@localhost:5433/pipeline"


def _async_url() -> str:
    raw = os.getenv("DATABASE_URL", _DEFAULT_URL)
    for prefix in ("postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if raw.startswith(prefix):
            return "postgresql+asyncpg://" + raw[len(prefix):]
    return raw


engine: AsyncEngine = create_async_engine(_async_url(), pool_size=5, max_overflow=10, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
