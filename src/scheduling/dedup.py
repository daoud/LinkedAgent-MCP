from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.post import Post


def compute_hash(content: str) -> str:
    """Return SHA-256 hex digest of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def is_duplicate(content_hash: str, session: AsyncSession) -> bool:
    """Return True if a non-rejected/failed post with this hash already exists."""
    result = await session.execute(
        select(Post.id)
        .where(Post.post_hash == content_hash)
        .where(Post.status.notin_(["rejected", "failed"]))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def set_content_hash(post: Post, content: str) -> str:
    """Compute and assign the content hash to a post; returns the hash."""
    h = compute_hash(content)
    post.post_hash = h
    return h
