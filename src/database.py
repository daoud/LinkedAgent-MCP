from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def _make_engine() -> AsyncEngine:
    from src.config import get_settings

    return create_async_engine(
        get_settings().async_database_url,
        pool_size=5,
        max_overflow=10,
        echo=False,
    )


engine: AsyncEngine = _make_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
