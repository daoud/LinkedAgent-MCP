"""Unit tests for src/pipeline/nodes/extract.py — mocked session, no DB."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.post import Post
from src.pipeline.nodes import extract as extract_mod
from src.pipeline.nodes.extract import extract_node


@pytest.fixture(autouse=True)
def _no_db_logging(monkeypatch):
    """extract_node calls log_event(); stub it so tests never touch a real DB."""
    monkeypatch.setattr(extract_mod, "log_event", AsyncMock())


def _patched_session(existing_post: Post | None = None):
    """A mock AsyncSessionLocal() context manager.

    execute().scalar_one() returns *existing_post* (the retry lookup).
    """
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = existing_post
    session.execute.return_value = result
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_extract_creates_new_post_when_no_post_id():
    upload_id = uuid.uuid4()
    session = _patched_session()

    with (
        patch("src.pipeline.nodes.extract.AsyncSessionLocal", return_value=session),
        patch("src.pipeline.nodes.extract.get_settings", return_value=MagicMock()),
        patch("src.pipeline.nodes.extract.get_storage_client", return_value=MagicMock()),
        patch(
            "src.pipeline.nodes.extract.read_content",
            new=AsyncMock(return_value=("hello body", [])),
        ),
    ):
        out = await extract_node({"upload_id": upload_id, "dry_run": True})

    session.add.assert_called_once()
    added_post = session.add.call_args[0][0]
    assert isinstance(added_post, Post)
    assert added_post.upload_id == upload_id
    assert out["raw_content"] == "hello body"


@pytest.mark.asyncio
async def test_extract_reuses_and_resets_post_on_retry():
    upload_id = uuid.uuid4()
    post = Post()
    post.id = uuid.uuid4()
    post.upload_id = upload_id
    post.status = "failed"
    post.post_hash = "stale-hash"
    post.transformed_text = "old draft"
    post.linkedin_post_id = "urn:li:share:123"
    post.last_error = "boom"
    post.failed_at_node = "transform"

    session = _patched_session(existing_post=post)

    with (
        patch("src.pipeline.nodes.extract.AsyncSessionLocal", return_value=session),
        patch("src.pipeline.nodes.extract.get_settings", return_value=MagicMock()),
        patch("src.pipeline.nodes.extract.get_storage_client", return_value=MagicMock()),
        patch(
            "src.pipeline.nodes.extract.read_content",
            new=AsyncMock(return_value=("fresh body", [])),
        ),
    ):
        out = await extract_node(
            {"upload_id": upload_id, "dry_run": False, "post_id": post.id}
        )

    # Same row, not a new one
    session.add.assert_not_called()
    assert out["post_id"] == post.id
    # Every field a prior failed run may have written is cleared
    assert post.status == "processing"
    assert post.post_hash is None
    assert post.transformed_text is None
    assert post.linkedin_post_id is None
    assert post.scheduled_slot is None
    assert post.scheduled_date is None
    assert post.last_error is None
    assert post.failed_at_node is None
    assert post.raw_content == "fresh body"
