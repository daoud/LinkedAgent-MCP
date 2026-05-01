"""Unit tests for src/ingestion/content_extractor.py — no DB required."""

import pytest

from src.ingestion.content_extractor import (
    MAX_FILE_SIZE,
    ExtractionError,
    detect_mime,
    extract_content,
    extract_from_bytes,
)


# ---- detect_mime -----------------------------------------------------------


def test_detect_mime_txt(tmp_path):
    f = tmp_path / "readme.txt"
    f.write_text("hello")
    assert detect_mime(f) == "text/plain"


def test_detect_mime_markdown(tmp_path):
    f = tmp_path / "post.md"
    f.write_text("# Title")
    mime = detect_mime(f)
    assert "markdown" in mime or mime == "text/plain"


def test_detect_mime_pdf_by_magic(tmp_path):
    f = tmp_path / "nodot"
    f.write_bytes(b"%PDF-1.4 fake pdf content")
    assert detect_mime(f) == "application/pdf"


def test_detect_mime_docx_by_magic(tmp_path):
    f = tmp_path / "nodot"
    f.write_bytes(b"PK\x03\x04 fake docx zip header")
    assert "wordprocessingml" in detect_mime(f)


# ---- extract_from_bytes ----------------------------------------------------


def test_extract_plain_text():
    data = b"Hello, LinkedIn!"
    text, images = extract_from_bytes(data, "text/plain")
    assert text == "Hello, LinkedIn!"
    assert images == []


def test_extract_markdown():
    data = b"# Title\n\nSome content here."
    text, images = extract_from_bytes(data, "text/markdown")
    assert "Title" in text
    assert images == []


def test_extract_image_returns_ref():
    data = b"\xff\xd8\xff\xe0"  # JPEG header
    text, images = extract_from_bytes(data, "image/jpeg", filename="photo.jpg")
    assert text == ""
    assert "photo.jpg" in images


def test_extract_image_no_filename():
    text, images = extract_from_bytes(b"\x89PNG", "image/png")
    assert text == ""
    assert images == []


def test_extract_pdf():
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    text, images = extract_from_bytes(buf.getvalue(), "application/pdf")
    assert isinstance(text, str)
    assert images == []


def test_extract_empty_bytes():
    text, images = extract_from_bytes(b"", "text/plain")
    assert text == ""
    assert images == []


def test_extract_unknown_mime_falls_back_to_text():
    data = b"just some bytes"
    text, images = extract_from_bytes(data, "application/octet-stream")
    assert "just some bytes" in text


# ---- extract_content (file-level) ------------------------------------------


def test_extract_content_txt_file(tmp_path):
    f = tmp_path / "draft.txt"
    f.write_text("Phase 2 content test.", encoding="utf-8")
    text, images = extract_content(f)
    assert "Phase 2" in text
    assert images == []


def test_extract_content_md_file(tmp_path):
    f = tmp_path / "draft.md"
    f.write_text("# AI Trends\nMachine learning is transforming industries.")
    text, images = extract_content(f)
    assert "AI Trends" in text


def test_extract_content_file_not_found():
    with pytest.raises(FileNotFoundError):
        extract_content("/nonexistent/path/file.txt")


def test_extract_content_too_large(tmp_path):
    f = tmp_path / "huge.txt"
    f.write_bytes(b"x" * (MAX_FILE_SIZE + 1))
    with pytest.raises(ExtractionError, match="too large"):
        extract_content(f)


def test_extract_content_explicit_mime(tmp_path):
    f = tmp_path / "data.bin"
    f.write_text("plain content")
    text, _ = extract_content(f, mime_type="text/plain")
    assert "plain content" in text
