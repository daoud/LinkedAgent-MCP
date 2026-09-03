from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.linkedin.auth import LinkedInAuth
from src.linkedin.client import LinkedInClient
from src.linkedin.rate_limiter import RateLimiter
from src.models.post import Post
from src.pipeline.state import PipelineState

# One rate limiter per process, shared across every publish_node invocation —
# a fresh RateLimiter() per call (the previous behavior) resets the sliding
# window on every single post and enforces nothing.
_RATE_LIMITER = RateLimiter()


async def publish_node(state: PipelineState) -> dict:
    post_id = state["post_id"]
    dry_run = state.get("dry_run", True)
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()

        # Publish whatever text is on the row now, not the copy captured in
        # graph state at transform time — this is what lets a reviewer edit
        # posts.transformed_text while the graph is paused for approval and
        # have that edit actually go live.
        text = post.transformed_text or state["transformed_text"]

        if not dry_run and post.linkedin_post_id:
            # A prior run of this thread already published successfully (e.g.
            # this node is being re-entered after a resume). Skip the API
            # call so we never post the same content twice.
            return {"linkedin_post_id": post.linkedin_post_id}

        if not dry_run and post.status == "publishing":
            # A previous attempt reached the point of calling the LinkedIn
            # API but the process died before we could record whether it
            # succeeded. We cannot tell if that post landed on LinkedIn, so
            # fail closed instead of risking a duplicate — this needs a
            # human to check LinkedIn before a retry is safe.
            post.status = "failed"
            post.last_error = (
                "Publish was interrupted after the LinkedIn API call may "
                "have been made — verify on LinkedIn before retrying to "
                "avoid a duplicate post."
            )
            post.failed_at_node = "publish"
            await session.commit()
            return {"error": post.last_error, "failed_node": "publish"}

        if not dry_run:
            post.status = "publishing"
            await session.commit()

    auth = LinkedInAuth.from_settings(settings)
    profile_urn = settings.linkedin_profile_urn or "urn:li:person:unknown"
    client = LinkedInClient(auth=auth, profile_urn=profile_urn, rate_limiter=_RATE_LIMITER)

    try:
        result = await asyncio.to_thread(client.publish, text, dry_run=dry_run)
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            r = await session.execute(select(Post).where(Post.id == post_id))
            post = r.scalar_one()
            post.status = "failed"
            post.last_error = str(exc)
            post.failed_at_node = "publish"
            await session.commit()
        return {"error": str(exc), "failed_node": "publish"}

    linkedin_post_id = result.get("linkedin_post_id")

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()
        if linkedin_post_id:
            post.linkedin_post_id = linkedin_post_id
        if not dry_run:
            post.published_at = datetime.now(timezone.utc)
        await session.commit()

    return {"linkedin_post_id": linkedin_post_id}
