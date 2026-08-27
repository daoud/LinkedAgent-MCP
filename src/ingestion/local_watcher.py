from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop

_IGNORED_PREFIXES = (".", "_", "~")
_IGNORED_SUFFIXES = frozenset((".tmp", ".part", ".swp", ".crdownload", ".ds_store"))


def _classify_file_type(mime_type: Optional[str], suffix: str) -> str:
    if mime_type:
        if mime_type == "application/pdf":
            return "document"
        if "wordprocessingml" in mime_type or "opendocument" in mime_type:
            return "document"
        if mime_type in ("text/markdown", "text/x-markdown"):
            return "markdown"
        if mime_type.startswith("text/"):
            return "text"
        if mime_type.startswith("image/"):
            return "image"
    ext = suffix.lower()
    if ext in (".pdf", ".docx", ".doc", ".odt"):
        return "document"
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        return "image"
    return "text"


class ContentUploadHandler(FileSystemEventHandler):
    def __init__(self, content_dir: str) -> None:
        self.content_dir = Path(content_dir)
        self._seen: set[str] = set()

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.name.startswith(_IGNORED_PREFIXES):
            return
        if path.suffix.lower() in _IGNORED_SUFFIXES:
            return
        key = str(path.resolve())
        if key in self._seen:
            return
        self._seen.add(key)
        if _main_loop and _main_loop.is_running():
            asyncio.run_coroutine_threadsafe(self._register(path), _main_loop)
        else:
            asyncio.run(self._register(path))

    async def _register(self, file_path: Path) -> None:
        from sqlalchemy import select  # noqa: PLC0415

        from src.database import AsyncSessionLocal  # noqa: PLC0415
        from src.models.content_upload import ContentUpload  # noqa: PLC0415

        mime_type, _ = mimetypes.guess_type(str(file_path))
        file_type = _classify_file_type(mime_type, file_path.suffix)

        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                select(ContentUpload).where(ContentUpload.file_name == file_path.name)
            )
            if existing.scalar_one_or_none() is not None:
                return  # idempotent — file already registered

            try:
                file_bytes = file_path.read_bytes()
                content_hash = hashlib.sha256(file_bytes).hexdigest()
                file_size = file_path.stat().st_size
            except OSError:
                return

            upload = ContentUpload(
                file_name=file_path.name,
                storage_path=str(file_path.resolve()),
                storage_type="local",
                mime_type=mime_type,
                file_type=file_type,
                content_hash=content_hash,
                file_size_bytes=file_size,
                status="pending",
            )
            session.add(upload)
            await session.commit()
            print(f"[watcher] Registered: {file_path.name} (upload_id={upload.id})")


def start_watcher(content_dir: str) -> Observer:
    """Start watching content_dir for new files. Returns the running Observer."""
    observer = Observer()
    handler = ContentUploadHandler(content_dir)
    observer.schedule(handler, str(content_dir), recursive=False)
    observer.start()
    print(f"[watcher] Watching: {content_dir}")
    return observer
