from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.content_extractor import detect_mime, extract_from_bytes
from src.ingestion.storage_client import StorageClient
from src.models.content_upload import ContentUpload


async def read_content(
    upload_id: uuid.UUID,
    session: AsyncSession,
    storage_client: Optional[StorageClient] = None,
) -> tuple[str, list[str]]:
    """Download + extract content for an existing ContentUpload record.

    Updates content_hash, mime_type, and processed_at on the DB row.
    Returns (extracted_text, image_refs).
    """
    result = await session.execute(
        select(ContentUpload).where(ContentUpload.id == upload_id)
    )
    upload = result.scalar_one()

    if storage_client is None:
        from src.config import get_settings  # noqa: PLC0415
        from src.ingestion.storage_client import get_storage_client  # noqa: PLC0415

        storage_client = get_storage_client(get_settings())

    file_bytes = storage_client.download(upload.storage_path)

    mime_type = upload.mime_type
    if not mime_type:
        if upload.storage_type == "local":
            mime_type = detect_mime(Path(upload.storage_path))
        else:
            mime_type, _ = mimetypes.guess_type(upload.file_name)
            mime_type = mime_type or "application/octet-stream"

    text, image_refs = extract_from_bytes(file_bytes, mime_type, filename=upload.file_name)

    upload.content_hash = hashlib.sha256(file_bytes).hexdigest()
    upload.mime_type = mime_type
    upload.processed_at = datetime.now(timezone.utc)
    await session.commit()

    return text, image_refs
