from __future__ import annotations

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.linkedin.auth import LinkedInAuth
from src.linkedin.client import LinkedInClient
from src.models.post import Post
from src.pipeline.state import PipelineState


async def preview_node(state: PipelineState) -> dict:
    settings = get_settings()

    # Read the text off the row, not graph state — a reviewer may have edited
    # posts.transformed_text while the graph was paused for approval, and the
    # preview should reflect exactly what publish_node will send.
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == state["post_id"]))
        post = r.scalar_one_or_none()
    text = (post.transformed_text if post else None) or state["transformed_text"]

    if not settings.linkedin_profile_urn:
        preview = {"dry_run": True, "preview": text[:150], "char_count": len(text)}
        return {"preview_result": preview, "transformed_text": text}

    auth = LinkedInAuth.from_settings(settings)
    client = LinkedInClient(auth=auth, profile_urn=settings.linkedin_profile_urn)
    preview = client.publish(text, dry_run=True)

    return {"preview_result": preview, "transformed_text": text}
