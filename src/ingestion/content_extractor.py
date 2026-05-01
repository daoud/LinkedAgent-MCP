from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional, Union

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class ExtractionError(Exception):
    pass


def detect_mime(file_path: Union[str, Path]) -> str:
    """Detect MIME type via stdlib mimetypes with magic-byte fallback."""
    fp = Path(file_path)
    mime, _ = mimetypes.guess_type(fp.name)
    if mime:
        return mime
    try:
        with fp.open("rb") as f:
            header = f.read(8)
    except OSError:
        return "application/octet-stream"
    if header[:4] == b"%PDF":
        return "application/pdf"
    if header[:2] == b"PK":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "text/plain"


def extract_content(
    file_path: Union[str, Path],
    mime_type: Optional[str] = None,
) -> tuple[str, list[str]]:
    """Read a file and extract its text. Returns (text, image_refs).

    Raises ExtractionError if the file exceeds MAX_FILE_SIZE.
    """
    fp = Path(file_path)
    if not fp.exists():
        raise FileNotFoundError(f"File not found: {fp}")

    size = fp.stat().st_size
    if size > MAX_FILE_SIZE:
        raise ExtractionError(f"File too large: {size:,} bytes (max {MAX_FILE_SIZE:,})")

    if mime_type is None:
        mime_type = detect_mime(fp)

    data = fp.read_bytes()
    return extract_from_bytes(data, mime_type, filename=fp.name)


def extract_from_bytes(
    data: bytes,
    mime_type: str,
    filename: str = "",
) -> tuple[str, list[str]]:
    """Extract text from raw bytes. Returns (text, image_refs).

    image_refs is populated with filename when mime_type is image/*.
    """
    if not data:
        return "", []

    if mime_type.startswith("image/"):
        return "", [filename] if filename else []

    if mime_type == "application/pdf":
        return _extract_pdf(data), []

    if (
        "wordprocessingml" in mime_type
        or mime_type == "application/msword"
        or mime_type == "application/vnd.oasis.opendocument.text"
    ):
        return _extract_docx(data), []

    # text/* and anything else → decode as text
    return _extract_text(data), []


# ---- private helpers -------------------------------------------------------


def _extract_text(data: bytes) -> str:
    try:
        import chardet  # noqa: PLC0415

        detected = chardet.detect(data)
        encoding = detected.get("encoding") or "utf-8"
    except ImportError:
        encoding = "utf-8"
    return data.decode(encoding, errors="replace")


def _extract_pdf(data: bytes) -> str:
    from io import BytesIO  # noqa: PLC0415

    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(t for t in pages if t.strip())


def _extract_docx(data: bytes) -> str:
    from io import BytesIO  # noqa: PLC0415

    from docx import Document  # noqa: PLC0415

    doc = Document(BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
