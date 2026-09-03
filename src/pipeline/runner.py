"""Shared, crash-safe entry point for running the LangGraph pipeline.

Every code path that starts or resumes the graph goes through here so that:
  * a single place owns the thread_id conventions,
  * any exception is caught, logged to the ring + the logs table, and the
    post row is marked failed — the background task never bubbles an error,
  * compose-time extras (tone, image, source, title) are injected into the
    initial state uniformly.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.post import Post
from src.observability.log_store import RING, log_event
from src.pipeline.state import PipelineState


async def run_pipeline(
    graph,
    upload_id: uuid.UUID,
    *,
    dry_run: bool = True,
    thread_id: str | None = None,
    post_id: uuid.UUID | None = None,
    extra_state: dict[str, Any] | None = None,
) -> None:
    """Start a fresh pipeline run. Safe to call as a background task."""
    thread_id = thread_id or f"upload-{upload_id}"
    state: PipelineState = {"upload_id": upload_id, "dry_run": dry_run}
    if post_id is not None:
        state["post_id"] = post_id
    if extra_state:
        state.update({k: v for k, v in extra_state.items() if v is not None})

    config = {"configurable": {"thread_id": thread_id}}
    try:
        async for _ in graph.astream(state, config=config):
            pass
    except Exception as exc:  # never let a background task crash silently
        await _mark_failed(post_id, upload_id, exc, phase="run")


async def resume_thread(graph, thread_id: str, resume_value: Any = True) -> None:
    """Resume a graph paused at an interrupt(). Safe to call as a background task."""
    from langgraph.types import Command  # noqa: PLC0415

    config = {"configurable": {"thread_id": thread_id}}
    try:
        async for _ in graph.astream(Command(resume=resume_value), config=config):
            pass
    except Exception as exc:
        await _mark_failed(None, None, exc, phase="resume", thread_id=thread_id)


async def _mark_failed(
    post_id: uuid.UUID | None,
    upload_id: uuid.UUID | None,
    exc: Exception,
    *,
    phase: str,
    thread_id: str | None = None,
) -> None:
    detail = f"{type(exc).__name__}: {exc}"
    try:
        if post_id is None and thread_id and thread_id.startswith("upload-"):
            # best-effort: recover the post from the upload id in the thread
            try:
                upload_id = uuid.UUID(thread_id.removeprefix("upload-"))
            except ValueError:
                upload_id = None
        async with AsyncSessionLocal() as session:
            post = None
            if post_id is not None:
                post = (
                    await session.execute(select(Post).where(Post.id == post_id))
                ).scalar_one_or_none()
            elif upload_id is not None:
                post = (
                    await session.execute(
                        select(Post)
                        .where(Post.upload_id == upload_id)
                        .order_by(Post.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if post is not None and post.status not in ("published", "rejected"):
                post.status = "failed"
                post.last_error = detail
                post.failed_at_node = post.failed_at_node or f"pipeline:{phase}"
                await session.commit()
                post_id = post.id
    except Exception:
        pass

    try:
        await log_event(
            "error",
            f"Pipeline {phase} crashed: {detail}",
            node="pipeline",
            post_id=post_id,
            upload_id=upload_id,
        )
    except Exception:
        RING.add(
            {
                "ts": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "level": "error",
                "logger": "pipeline",
                "message": f"Pipeline {phase} crashed: {detail}",
            }
        )
