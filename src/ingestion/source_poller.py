"""Poll configured content sources (Google Drive folders) for new post files.

For each new file: write it into the local content dir, create a
``content_uploads`` row (status ``pending``, ``external_id`` = the Drive file
id), and let the existing pending-upload poller pick it up and run it through
the pipeline on the configured schedule.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.models.content_source import ContentSource
from src.models.content_upload import ContentUpload

_log = logging.getLogger("pipeline")

_MD_EXT = {".md", ".markdown"}


def _file_type(name: str, mime: str | None) -> str:
    ext = Path(name).suffix.lower()
    if ext in _MD_EXT:
        return "markdown"
    if ext in (".pdf",) or mime == "application/pdf":
        return "document"
    if ext in (".doc", ".docx") or (mime and "word" in mime):
        return "document"
    return "text"


async def poll_sources() -> int:
    """One poll cycle across all enabled sources. Returns files imported."""
    settings = get_settings()
    imported = 0

    async with AsyncSessionLocal() as session:
        sources = list(
            (await session.execute(select(ContentSource).where(ContentSource.enabled.is_(True)))).scalars()
        )

    for src in sources:
        try:
            if src.kind == "gdrive":
                n = await _poll_gdrive(src, settings)
            else:
                continue  # s3 / local handled elsewhere
            imported += n
            await _mark_source(src.id, error=None)
        except Exception as exc:  # noqa: BLE001 — one bad source must not stop the rest
            _log.warning("[source-poller] %s (%s) failed: %s", src.name, src.kind, exc)
            await _mark_source(src.id, error=str(exc)[:500])

    return imported


async def _poll_gdrive(src: ContentSource, settings) -> int:
    from src.ingestion.gdrive_source import GDriveSource  # noqa: PLC0415

    creds = getattr(settings, "google_drive_credentials_file", None) or settings.google_sheets_credentials_file
    if not Path(creds).is_file():
        raise FileNotFoundError(f"Google credentials file not found: {creds}")

    drive = GDriveSource(src.location, creds)

    async with AsyncSessionLocal() as session:
        known = {
            row[0]
            for row in (
                await session.execute(
                    select(ContentUpload.external_id).where(ContentUpload.external_id.is_not(None))
                )
            ).all()
            if row[0]
        }

    new_files = await _to_thread(drive.fetch_new, known)
    if not new_files:
        return 0

    content_dir = Path(settings.local_content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for f in new_files:
        content_hash = hashlib.sha256(f.data).hexdigest()
        safe_name = f"gdrive-{Path(f.name).name}"
        dest = content_dir / safe_name
        mime = f.mime_type or mimetypes.guess_type(safe_name)[0] or "text/plain"

        async with AsyncSessionLocal() as session:
            dup = (
                await session.execute(
                    select(ContentUpload).where(
                        (ContentUpload.external_id == f.file_id)
                        | (ContentUpload.content_hash == content_hash)
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                continue
            session.add(
                ContentUpload(
                    file_name=safe_name,
                    storage_path=str(dest),
                    storage_type="local",
                    mime_type=mime,
                    file_type=_file_type(safe_name, mime),
                    content_hash=content_hash,
                    external_id=f.file_id,
                    source_id=src.id,
                    file_size_bytes=len(f.data),
                    status="pending",
                )
            )
            await session.commit()
        dest.write_bytes(f.data)
        count += 1
        _log.info("[source-poller] imported %s from Drive folder %s", safe_name, src.location)

    return count


async def _mark_source(source_id: uuid.UUID, *, error: str | None) -> None:
    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(select(ContentSource).where(ContentSource.id == source_id))
            ).scalar_one_or_none()
            if row is not None:
                row.last_polled_at = datetime.now(UTC)
                row.last_error = error
                await session.commit()
    except Exception:
        pass


async def _to_thread(fn, *args):
    import asyncio  # noqa: PLC0415

    return await asyncio.to_thread(fn, *args)
