from __future__ import annotations

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.ingestion.content_reader import read_content
from src.ingestion.storage_client import get_storage_client
from src.models.post import Post
from src.pipeline.state import PipelineState


async def extract_node(state: PipelineState) -> dict:
    upload_id = state["upload_id"]
    existing_post_id = state.get("post_id")
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        if existing_post_id is not None:
            # Retry path: reuse the same Post row rather than creating a new
            # one. A fresh row would collide with this one on the post_hash
            # UNIQUE column and be flagged as "Duplicate content" by the
            # dedup node. Reset every field a prior (failed) run may have
            # written so the pipeline starts clean.
            r = await session.execute(select(Post).where(Post.id == existing_post_id))
            post = r.scalar_one()
            post.status = "processing"
            post.transformed_text = None
            post.post_hash = None
            post.linkedin_post_id = None
            post.scheduled_slot = None
            post.scheduled_date = None
            post.last_error = None
            post.failed_at_node = None
        else:
            post = Post(upload_id=upload_id, status="processing")
            session.add(post)
            await session.flush()

        post_id = post.id

        storage_client = get_storage_client(settings)
        text, _image_refs = await read_content(upload_id, session, storage_client)

        post.raw_content = text
        await session.commit()

    return {"post_id": post_id, "raw_content": text}
