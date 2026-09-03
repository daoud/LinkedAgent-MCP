"""Unit tests for the dashboard API — helpers + defensive-error behaviour."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import dashboard
from src.models.post import Post


def _app():
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        app.state.graph = AsyncMock()
        yield

    app = FastAPI(lifespan=_lifespan)
    app.include_router(dashboard.router)
    return app


def test_bool_helper():
    assert dashboard._bool("true") is True
    assert dashboard._bool("1") is True
    assert dashboard._bool("on") is True
    assert dashboard._bool("false") is False
    assert dashboard._bool(None, default=True) is True
    assert dashboard._bool("nonsense") is False


def test_post_dict_shapes_a_row():
    p = Post()
    p.id = uuid.uuid4()
    p.status = "published"
    p.source = "compose"
    p.linkedin_post_id = "urn:li:share:123"
    p.retry_count = 0
    d = dashboard._post_dict(p)
    assert d["status"] == "published"
    assert d["linkedin_url"].endswith("urn:li:share:123")
    assert "raw_content" not in d
    assert "raw_content" in dashboard._post_dict(p, full=True)


def test_compose_requires_content():
    with TestClient(_app()) as c:
        r = c.post("/api/compose", data={"dry_run": "true"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_unknown_op_is_404_not_crash():
    with TestClient(_app()) as c:
        r = c.post("/api/ops/rm-rf")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_overview_survives_db_failure():
    with patch("src.api.routes.dashboard.AsyncSessionLocal") as f:
        sess = AsyncMock()
        from sqlalchemy.exc import OperationalError

        sess.execute.side_effect = OperationalError("x", {}, Exception("down"))
        sess.__aenter__ = AsyncMock(return_value=sess)
        sess.__aexit__ = AsyncMock(return_value=None)
        f.return_value = sess
        with TestClient(_app()) as c:
            r = c.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "database" in body["error"]


def test_logs_endpoint_reads_ring():
    dashboard.RING.add({"ts": "2026-01-01T00:00:00Z", "level": "info", "logger": "t", "message": "hello ring"})
    with TestClient(_app()) as c:
        r = c.get("/api/logs?limit=50")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert any("hello ring" in x["message"] for x in body["logs"])
