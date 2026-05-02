from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.linkedin.auth import LinkedInAuth
from src.linkedin.client import LinkedInClient
from src.models.post import Post
from src.pipeline.state import PipelineState


async def publish_node(state: PipelineState) -> dict:
    text = state["transformed_text"]
    post_id = state["post_id"]
    dry_run = state.get("dry_run", True)
    settings = get_settings()

    auth = LinkedInAuth.from_settings(settings)
    profile_urn = settings.linkedin_profile_urn or "urn:li:person:unknown"
    client = LinkedInClient(auth=auth, profile_urn=profile_urn)

    result = client.publish(text, dry_run=dry_run)
    linkedin_post_id = result.get("linkedin_post_id")

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()
        if linkedin_post_id:
            post.linkedin_post_id = linkedin_post_id
        if not dry_run:
            post.status = "publishing"
            post.published_at = datetime.now(timezone.utc)
        await session.commit()

    return {"linkedin_post_id": linkedin_post_id}
