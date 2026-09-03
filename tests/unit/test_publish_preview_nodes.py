"""Unit tests for preview_node / publish_node reading the edited draft from the row."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.post import Post
from src.pipeline.nodes.preview import preview_node
from src.pipeline.nodes.publish import publish_node


def _session_cm(post: Post):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = post
    result.scalar_one_or_none.return_value = post
    session.execute.return_value = result
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_preview_uses_edited_row_text_over_state():
    post = Post()
    post.id = uuid.uuid4()
    post.transformed_text = "REVIEWER EDITED VERSION"

    settings = MagicMock()
    settings.linkedin_profile_urn = None  # take the no-URN branch, no HTTP

    with (
        patch("src.pipeline.nodes.preview.AsyncSessionLocal", return_value=_session_cm(post)),
        patch("src.pipeline.nodes.preview.get_settings", return_value=settings),
    ):
        out = await preview_node(
            {"post_id": post.id, "transformed_text": "stale llm draft"}
        )

    assert "REVIEWER EDITED VERSION" in out["preview_result"]["preview"]
    assert out["transformed_text"] == "REVIEWER EDITED VERSION"


@pytest.mark.asyncio
async def test_publish_dry_run_uses_edited_row_text():
    post = Post()
    post.id = uuid.uuid4()
    post.status = "approved"
    post.linkedin_post_id = None
    post.transformed_text = "REVIEWER EDITED VERSION"

    settings = MagicMock()
    settings.linkedin_profile_urn = "urn:li:person:abc"

    fake_client = MagicMock()
    fake_client.publish.return_value = {"dry_run": True, "linkedin_post_id": None}

    with (
        patch("src.pipeline.nodes.publish.AsyncSessionLocal", return_value=_session_cm(post)),
        patch("src.pipeline.nodes.publish.get_settings", return_value=settings),
        patch("src.pipeline.nodes.publish.LinkedInAuth", MagicMock()),
        patch("src.pipeline.nodes.publish.LinkedInClient", return_value=fake_client),
    ):
        await publish_node(
            {"post_id": post.id, "transformed_text": "stale llm draft", "dry_run": True}
        )

    sent_text = fake_client.publish.call_args[0][0]
    assert sent_text == "REVIEWER EDITED VERSION"
