"""Unit tests for Phase 8 — FastAPI API (middleware, health, pipeline routes)."""
from __future__ import annotations

import io
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from src.api.middleware import APIKeyMiddleware
from src.api.routes import health, pipeline
from src.database import get_db
from src.models.approval import Approval
from src.models.content_upload import ContentUpload
from src.models.post import Post


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_session(scalar=None, fetchall=None, scalars_all=None):
    """Return a mock AsyncSession whose execute() results are configurable."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalar_one.return_value = scalar
    result.fetchall.return_value = fetchall or []
    result.scalars.return_value.all.return_value = scalars_all or []
    session.execute.return_value = result
    return session


def _build_app(graph=None, api_key=None):
    """Build a test FastAPI app with a no-op lifespan (no real DB / scheduler)."""
    mock_graph = graph if graph is not None else AsyncMock()

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        app.state.graph = mock_graph
        app.state.checkpointer = MagicMock()
        yield

    app = FastAPI(lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    if api_key is not None:
        app.add_middleware(APIKeyMiddleware, api_key=api_key)
    app.include_router(health.router)
    app.include_router(pipeline.router)
    return app, mock_graph


# ---------------------------------------------------------------------------
# APIKeyMiddleware
# ---------------------------------------------------------------------------

class TestAPIKeyMiddleware:
    def test_no_api_key_configured_allows_all_requests(self):
        app, _ = _build_app(api_key=None)
        session = _mock_session()

        async def _override():
            yield session

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as client:
            r = client.get("/health")
        assert r.status_code == 200

    def test_wrong_key_is_rejected(self):
        app, _ = _build_app(api_key="secret")
        with TestClient(app) as client:
            r = client.post("/pipeline/trigger", json={"upload_id": str(uuid.uuid4())})
        assert r.status_code == 401

    def test_correct_key_is_accepted(self):
        app, mock_graph = _build_app(api_key="secret")
        mock_graph.astream.return_value = _async_iter([])

        async def _override():
            yield _mock_session()

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as client:
            r = client.post(
                "/pipeline/trigger",
                json={"upload_id": str(uuid.uuid4()), "dry_run": True},
                headers={"X-API-Key": "secret"},
            )
        assert r.status_code == 200

    def test_public_paths_bypass_auth(self):
        app, _ = _build_app(api_key="secret")
        session = _mock_session()

        async def _override():
            yield session

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as client:
            r = client.get("/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_ok_when_db_responds(self):
        app, _ = _build_app()
        session = _mock_session()

        async def _override():
            yield session

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as client:
            r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"

    def test_returns_degraded_when_db_raises(self):
        app, _ = _build_app()
        session = AsyncMock()
        session.execute.side_effect = Exception("connection refused")

        async def _override():
            yield session

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as client:
            r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "degraded"


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    def test_returns_post_counts_and_cost(self):
        app, _ = _build_app()
        session = AsyncMock()

        # First call: post counts; second call: total cost
        counts_result = MagicMock()
        counts_result.fetchall.return_value = [
            MagicMock(status="pending", count=2),
            MagicMock(status="published", count=5),
        ]
        cost_result = MagicMock()
        cost_result.scalar_one_or_none.return_value = Decimal("1.234567")
        session.execute.side_effect = [counts_result, cost_result]

        async def _override():
            yield session

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as client:
            r = client.get("/metrics")
        assert r.status_code == 200
        body = r.json()
        assert body["posts"]["pending"] == 2
        assert body["posts"]["published"] == 5
        assert body["total_llm_cost_usd"] == pytest.approx(1.234567)

    def test_returns_zero_cost_when_no_llm_records(self):
        app, _ = _build_app()
        session = AsyncMock()
        counts_result = MagicMock()
        counts_result.fetchall.return_value = []
        cost_result = MagicMock()
        cost_result.scalar_one_or_none.return_value = None
        session.execute.side_effect = [counts_result, cost_result]

        async def _override():
            yield session

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as client:
            r = client.get("/metrics")
        assert r.json()["total_llm_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# POST /pipeline/trigger
# ---------------------------------------------------------------------------

class TestPipelineTrigger:
    def test_returns_accepted_with_thread_id(self):
        upload_id = uuid.uuid4()
        app, mock_graph = _build_app()
        mock_graph.astream.return_value = _async_iter([])
        with TestClient(app) as client:
            r = client.post(
                "/pipeline/trigger", json={"upload_id": str(upload_id), "dry_run": True}
            )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert body["upload_id"] == str(upload_id)
        assert body["thread_id"] == f"upload-{upload_id}"

    def test_thread_id_matches_upload_id(self):
        upload_id = uuid.uuid4()
        app, mock_graph = _build_app()
        mock_graph.astream.return_value = _async_iter([])
        with TestClient(app) as client:
            r = client.post(
                "/pipeline/trigger", json={"upload_id": str(upload_id), "dry_run": False}
            )
        assert r.json()["thread_id"] == f"upload-{upload_id}"


# ---------------------------------------------------------------------------
# GET /pipeline/status/{post_id}
# ---------------------------------------------------------------------------

class TestPipelineStatus:
    def _make_post(self, status: str = "processing") -> Post:
        post = Post()
        post.id = uuid.uuid4()
        post.upload_id = uuid.uuid4()
        post.status = status
        post.scheduled_date = None
        post.scheduled_slot = None
        post.linkedin_post_id = None
        post.last_error = None
        post.failed_at_node = None
        post.retry_count = 0
        post.tokens_used = None
        post.cost_usd = None
        post.created_at = None
        post.published_at = None
        return post

    def test_returns_post_status(self):
        post = self._make_post("published")
        app, _ = _build_app()

        async def _override():
            yield _mock_session(scalar=post)

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as client:
            r = client.get(f"/pipeline/status/{post.id}")
        assert r.status_code == 200
        assert r.json()["status"] == "published"

    def test_returns_404_when_not_found(self):
        app, _ = _build_app()

        async def _override():
            yield _mock_session(scalar=None)

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as client:
            r = client.get(f"/pipeline/status/{uuid.uuid4()}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /pipeline/upload
# ---------------------------------------------------------------------------

class TestPipelineUpload:
    def test_accepts_text_file_and_returns_upload_id(self, tmp_path):
        app, mock_graph = _build_app()
        mock_graph.astream.return_value = _async_iter([])

        with (
            patch("src.api.routes.pipeline.AsyncSessionLocal") as mock_session_factory,
            patch("src.config.get_settings") as mock_settings,
        ):
            settings = MagicMock()
            settings.local_content_dir = str(tmp_path)
            mock_settings.return_value = settings

            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = None  # no duplicate
            session.execute.return_value = result
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            mock_session_factory.return_value = session

            with TestClient(app) as client:
                r = client.post(
                    "/pipeline/upload",
                    files={"file": ("test.txt", b"hello world", "text/plain")},
                    params={"dry_run": "true"},
                )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert "upload_id" in body

    def test_rejects_duplicate_content(self, tmp_path):
        app, _ = _build_app()
        existing_upload = ContentUpload()
        existing_upload.id = uuid.uuid4()

        with (
            patch("src.api.routes.pipeline.AsyncSessionLocal") as mock_session_factory,
            patch("src.config.get_settings") as mock_settings,
        ):
            settings = MagicMock()
            settings.local_content_dir = str(tmp_path)
            mock_settings.return_value = settings

            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing_upload  # duplicate found
            session.execute.return_value = result
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            mock_session_factory.return_value = session

            with TestClient(app) as client:
                r = client.post(
                    "/pipeline/upload",
                    files={"file": ("test.txt", b"duplicate content", "text/plain")},
                )
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# POST /pipeline/retry/{post_id}
# ---------------------------------------------------------------------------

class TestPipelineRetry:
    def test_returns_accepted_and_new_thread_id(self):
        post = Post()
        post.id = uuid.uuid4()
        post.upload_id = uuid.uuid4()
        post.status = "failed"
        post.retry_count = 1
        post.last_error = "something broke"
        post.failed_at_node = "transform"

        app, mock_graph = _build_app()
        mock_graph.astream.return_value = _async_iter([])

        with patch("src.api.routes.pipeline.AsyncSessionLocal") as mock_session_factory:
            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = post
            session.execute.return_value = result
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            mock_session_factory.return_value = session

            with TestClient(app) as client:
                r = client.post(f"/pipeline/retry/{post.id}?dry_run=true")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        # retry thread_id is fresh (not upload- prefix)
        assert body["thread_id"].startswith("retry-")

    def test_returns_404_for_missing_post(self):
        app, _ = _build_app()

        with patch("src.api.routes.pipeline.AsyncSessionLocal") as mock_session_factory:
            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            session.execute.return_value = result
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            mock_session_factory.return_value = session

            with TestClient(app) as client:
                r = client.post(f"/pipeline/retry/{uuid.uuid4()}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /pipeline/approve/{approval_id}
# ---------------------------------------------------------------------------

class TestPipelineApprove:
    def _make_approval_and_post(self):
        approval = Approval()
        approval.id = uuid.uuid4()
        post = Post()
        post.id = uuid.uuid4()
        post.upload_id = uuid.uuid4()
        approval.post_id = post.id
        return approval, post

    def test_accepted_with_valid_decision(self):
        approval, post = self._make_approval_and_post()
        app, mock_graph = _build_app()
        mock_graph.astream.return_value = _async_iter([])

        with patch("src.api.routes.pipeline.AsyncSessionLocal") as mock_session_factory:
            session = AsyncMock()
            # First execute: approval lookup; second: post lookup
            result1 = MagicMock()
            result1.scalar_one_or_none.return_value = approval
            result2 = MagicMock()
            result2.scalar_one.return_value = post
            session.execute.side_effect = [result1, result2]
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            mock_session_factory.return_value = session

            with TestClient(app) as client:
                r = client.post(
                    f"/pipeline/approve/{approval.id}",
                    json={"decision": "approved", "decided_by": "api"},
                )
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"

    def test_rejects_invalid_decision(self):
        approval, post = self._make_approval_and_post()
        app, _ = _build_app()

        with patch("src.api.routes.pipeline.AsyncSessionLocal") as mock_session_factory:
            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = approval
            result.scalar_one.return_value = post
            session.execute.side_effect = [result, result]
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            mock_session_factory.return_value = session

            with TestClient(app) as client:
                r = client.post(
                    f"/pipeline/approve/{approval.id}",
                    json={"decision": "maybe"},
                )
        assert r.status_code == 400

    def test_returns_404_for_missing_approval(self):
        app, _ = _build_app()

        with patch("src.api.routes.pipeline.AsyncSessionLocal") as mock_session_factory:
            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            session.execute.return_value = result
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            mock_session_factory.return_value = session

            with TestClient(app) as client:
                r = client.post(
                    f"/pipeline/approve/{uuid.uuid4()}",
                    json={"decision": "approved"},
                )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# _classify_file_type (pure function)
# ---------------------------------------------------------------------------

from src.api.routes.pipeline import _classify_file_type


class TestClassifyFileType:
    def test_pdf_mime(self):
        assert _classify_file_type("application/pdf", ".pdf") == "document"

    def test_markdown_mime(self):
        assert _classify_file_type("text/markdown", ".md") == "markdown"

    def test_image_mime(self):
        assert _classify_file_type("image/png", ".png") == "image"

    def test_text_mime(self):
        assert _classify_file_type("text/plain", ".txt") == "text"

    def test_fallback_by_extension(self):
        assert _classify_file_type(None, ".docx") == "document"
        assert _classify_file_type(None, ".md") == "markdown"
        assert _classify_file_type(None, ".jpg") == "image"
        assert _classify_file_type(None, ".csv") == "text"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

async def _async_iter_gen(items):
    for item in items:
        yield item


def _async_iter(items):
    return _async_iter_gen(items)
