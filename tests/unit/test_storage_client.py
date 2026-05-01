"""Unit tests for src/ingestion/storage_client.py — no DB, no AWS required."""

import pytest

from src.ingestion.storage_client import LocalStorageClient


def test_upload_copies_file(tmp_path):
    src = tmp_path / "src" / "doc.txt"
    src.parent.mkdir()
    src.write_text("hello content")

    store = tmp_path / "storage"
    client = LocalStorageClient(str(store))
    path = client.upload(src)

    assert (store / "doc.txt").exists()
    assert (store / "doc.txt").read_text() == "hello content"
    assert path == str((store / "doc.txt").resolve())


def test_upload_same_directory_no_copy(tmp_path):
    """Uploading a file already in base_dir is a no-op."""
    client = LocalStorageClient(str(tmp_path))
    f = tmp_path / "existing.txt"
    f.write_text("data")
    path = client.upload(f)
    assert path == str(f.resolve())


def test_download_returns_bytes(tmp_path):
    f = tmp_path / "file.bin"
    f.write_bytes(b"\x00\x01\x02\x03")
    client = LocalStorageClient(str(tmp_path))
    assert client.download(str(f)) == b"\x00\x01\x02\x03"


def test_exists_true(tmp_path):
    f = tmp_path / "yes.txt"
    f.write_text("x")
    client = LocalStorageClient(str(tmp_path))
    assert client.exists(str(f)) is True


def test_exists_false(tmp_path):
    client = LocalStorageClient(str(tmp_path))
    assert client.exists(str(tmp_path / "no.txt")) is False


def test_delete_removes_file(tmp_path):
    f = tmp_path / "bye.txt"
    f.write_text("gone")
    client = LocalStorageClient(str(tmp_path))
    client.delete(str(f))
    assert not f.exists()


def test_delete_missing_is_noop(tmp_path):
    client = LocalStorageClient(str(tmp_path))
    client.delete(str(tmp_path / "ghost.txt"))  # must not raise


def test_base_dir_created_automatically(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    client = LocalStorageClient(str(nested))
    assert nested.exists()


def test_upload_then_download_roundtrip(tmp_path):
    src = tmp_path / "in" / "roundtrip.txt"
    src.parent.mkdir()
    src.write_bytes(b"roundtrip bytes")

    store = tmp_path / "out"
    client = LocalStorageClient(str(store))
    stored_path = client.upload(src)
    data = client.download(stored_path)
    assert data == b"roundtrip bytes"
