"""Integration tests for the ingestion layer.

These tests exercise the full upload → download → extract flow using the
local filesystem. No AWS or external services needed.
"""

from pathlib import Path

from src.ingestion.content_extractor import extract_content
from src.ingestion.storage_client import LocalStorageClient


def test_ingest_txt_file(tmp_path):
    content = "LinkedIn post draft: AI is reshaping every industry in 2026."
    src = tmp_path / "draft.txt"
    src.write_text(content)

    store = tmp_path / "storage"
    client = LocalStorageClient(str(store))
    stored = client.upload(src)

    assert client.exists(stored)
    data = client.download(stored)
    text, images = extract_content(Path(stored))

    assert content in text
    assert images == []


def test_ingest_markdown_file(tmp_path):
    content = "# Leadership in AI\n\nThe best leaders adapt quickly.\n\n#AI #Leadership"
    src = tmp_path / "post.md"
    src.write_text(content)

    store = tmp_path / "storage"
    client = LocalStorageClient(str(store))
    stored = client.upload(src)
    text, images = extract_content(Path(stored))

    assert "Leadership in AI" in text
    assert "#AI" in text


def test_ingest_sample_post(tmp_path):
    """Ingest the real sample_post.md from test_content/."""
    sample = Path("test_content/sample_post.md")
    if not sample.exists() or sample.stat().st_size == 0:
        return  # sample not populated yet

    store = tmp_path / "storage"
    client = LocalStorageClient(str(store))
    stored = client.upload(sample)
    text, _ = extract_content(Path(stored))
    assert len(text) > 10


def test_ingest_sample_document(tmp_path):
    """Ingest the real sample_document.txt from test_content/."""
    sample = Path("test_content/sample_document.txt")
    if not sample.exists() or sample.stat().st_size == 0:
        return

    store = tmp_path / "storage"
    client = LocalStorageClient(str(store))
    stored = client.upload(sample)
    text, _ = extract_content(Path(stored))
    assert len(text) > 10


def test_storage_delete(tmp_path):
    f = tmp_path / "temp.txt"
    f.write_text("temporary")
    client = LocalStorageClient(str(tmp_path))
    stored = client.upload(f)
    client.delete(stored)
    assert not client.exists(stored)
