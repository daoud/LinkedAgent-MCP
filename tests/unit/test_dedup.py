"""Unit tests for src/scheduling/dedup.py — no DB required."""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.post import Post
from src.scheduling.dedup import compute_hash, is_duplicate, set_content_hash


# ---------------------------------------------------------------------------
# compute_hash
# ---------------------------------------------------------------------------

def test_compute_hash_deterministic():
    assert compute_hash("Hello World") == compute_hash("Hello World")


def test_compute_hash_unique_per_content():
    assert compute_hash("foo") != compute_hash("bar")


def test_compute_hash_matches_sha256():
    content = "test content"
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert compute_hash(content) == expected


def test_compute_hash_whitespace_sensitive():
    assert compute_hash("foo") != compute_hash("foo ")
    assert compute_hash("foo") != compute_hash("foo\n")


def test_compute_hash_unicode():
    h = compute_hash("こんにちは")
    assert len(h) == 64  # SHA-256 hex is always 64 chars


def test_compute_hash_empty_string():
    h = compute_hash("")
    assert len(h) == 64


# ---------------------------------------------------------------------------
# set_content_hash
# ---------------------------------------------------------------------------

def test_set_content_hash_assigns_to_post():
    post = Post()
    h = set_content_hash(post, "my content")
    assert post.post_hash == h
    assert h == compute_hash("my content")


def test_set_content_hash_returns_hash():
    post = Post()
    h = set_content_hash(post, "content")
    assert h == compute_hash("content")


def test_set_content_hash_overwrites_previous():
    post = Post()
    set_content_hash(post, "first")
    set_content_hash(post, "second")
    assert post.post_hash == compute_hash("second")


# ---------------------------------------------------------------------------
# is_duplicate (async, mocked session)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_duplicate_returns_true_when_hash_exists():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = "some-uuid"
    session.execute.return_value = result
    assert await is_duplicate("abc123", session) is True


@pytest.mark.asyncio
async def test_is_duplicate_returns_false_when_hash_absent():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    assert await is_duplicate("abc123", session) is False


@pytest.mark.asyncio
async def test_is_duplicate_calls_session_once():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    await is_duplicate("abc123", session)
    session.execute.assert_called_once()
