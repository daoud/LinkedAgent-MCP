from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.linkedin.auth import LinkedInAuth
from src.linkedin.client import LinkedInClient
from src.linkedin.rate_limiter import RateLimiter
from src.models.post import Post
from src.observability.log_store import log_event
from src.pipeline.state import PipelineState

# One rate limiter per process, shared across every publish_node invocation —
# a fresh RateLimiter() per call (the previous behavior) resets the sliding
# window on every single post and enforces nothing.
_RATE_LIMITER = RateLimiter()

_IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _upload_image_blocking(client: LinkedInClient, image_path: str) -> str:
    """Register + upload an image, returning its asset URN. Runs in a thread."""
    data = Path(image_path).read_bytes()
    return client.upload_image(data, filename=Path(image_path).name)


async def publish_node(state: PipelineState) -> dict:
    post_id = state["post_id"]
    dry_run = state.get("dry_run", True)
    settings = get_settings()
    image_warning: str | None = None

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()

        # Publish whatever text is on the row now, not the copy captured in
        # graph state at transform time — this is what lets a reviewer edit
        # posts.transformed_text while the graph is paused for approval and
        # have that edit actually go live.
        text = post.transformed_text or state["transformed_text"]
        image_path = post.image_path or state.get("image_path")
        existing_asset = post.image_asset_urn

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

    # ---- optional image ---------------------------------------------------
    media_urns: list[str] = []
    asset_urn: str | None = existing_asset
    if image_path and Path(image_path).is_file():
        suffix = Path(image_path).suffix.lower()
        if suffix not in _IMAGE_CONTENT_TYPES:
            image_warning = f"Unsupported image type {suffix!r} — publishing text only."
        elif dry_run:
            image_warning = None  # dry run: don't touch the asset API
        elif asset_urn:
            media_urns = [asset_urn]
        else:
            try:
                asset_urn = await asyncio.to_thread(_upload_image_blocking, client, image_path)
                media_urns = [asset_urn]
                async with AsyncSessionLocal() as session:
                    r = await session.execute(select(Post).where(Post.id == post_id))
                    p = r.scalar_one()
                    p.image_asset_urn = asset_urn
                    await session.commit()
            except Exception as exc:  # image failure must NOT fail the post
                image_warning = f"Image upload failed ({exc}) — publishing text only."

    if image_warning:
        await log_event("warning", image_warning, node="publish", post_id=post_id)

    # ---- publish --------------------------------------------------------
    try:
        result = await asyncio.to_thread(
            client.publish, text, media_urns or None, dry_run
        )
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            r = await session.execute(select(Post).where(Post.id == post_id))
            post = r.scalar_one()
            post.status = "failed"
            post.last_error = str(exc)
            post.failed_at_node = "publish"
            await session.commit()
        await log_event("error", f"Publish failed: {exc}", node="publish", post_id=post_id)
        return {"error": str(exc), "failed_node": "publish", "image_warning": image_warning}

    linkedin_post_id = result.get("linkedin_post_id")

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one()
        if linkedin_post_id:
            post.linkedin_post_id = linkedin_post_id
        if not dry_run:
            post.published_at = datetime.now(UTC)
        await session.commit()

    await log_event(
        "info",
        f"{'Dry-run preview built' if dry_run else 'Published to LinkedIn'}"
        f"{' with image' if media_urns else ''}"
        f"{f' ({linkedin_post_id})' if linkedin_post_id else ''}",
        node="publish",
        post_id=post_id,
    )

    return {
        "linkedin_post_id": linkedin_post_id,
        "image_asset_urn": asset_urn,
        "image_warning": image_warning,
    }
