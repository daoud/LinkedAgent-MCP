from __future__ import annotations

from src.database import AsyncSessionLocal
from src.ingestion.content_reader import read_content
from src.ingestion.storage_client import get_storage_client
from src.config import get_settings
from src.models.post import Post
from src.pipeline.state import PipelineState


async def extract_node(state: PipelineState) -> dict:
    upload_id = state["upload_id"]
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        post = Post(upload_id=upload_id, status="processing")
        session.add(post)
        await session.flush()
        post_id = post.id

        storage_client = get_storage_client(settings)
        text, _image_refs = await read_content(upload_id, session, storage_client)

        post.raw_content = text
        await session.commit()

    return {"post_id": post_id, "raw_content": text}
