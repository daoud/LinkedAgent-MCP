from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from src.api.middleware import APIKeyMiddleware
from src.api.routes import health, pipeline
from src.config import get_settings
from src.database import AsyncSessionLocal
from src.ingestion.local_watcher import start_watcher
from src.models.content_upload import ContentUpload
from src.pipeline.checkpointer import make_checkpointer
from src.pipeline.graph import build_graph
from src.pipeline.state import PipelineState


async def _run_pipeline_task(graph, upload_id: uuid.UUID, dry_run: bool, thread_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    state: PipelineState = {"upload_id": upload_id, "dry_run": dry_run}
    try:
        async for _ in graph.astream(state, config=config):
            pass
    except Exception as exc:
        print(f"[scheduler] Pipeline error for upload {upload_id}: {exc}")


async def _poll_pending_uploads(app: FastAPI) -> None:
    """Pick up ContentUploads in 'pending' state and trigger the pipeline for each."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ContentUpload).where(ContentUpload.status == "pending").limit(5)
        )
        uploads = list(result.scalars().all())
        for upload in uploads:
            upload.status = "processing"
            await session.flush()
            thread_id = f"upload-{upload.id}"
            asyncio.create_task(
                _run_pipeline_task(app.state.graph, upload.id, False, thread_id)
            )
        if uploads:
            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    async with make_checkpointer() as checkpointer:
        app.state.graph = build_graph(checkpointer=checkpointer)
        app.state.checkpointer = checkpointer

        observer = None
        if settings.storage_mode == "local":
            observer = start_watcher(settings.local_content_dir)

        scheduler = AsyncIOScheduler(timezone=settings.timezone)
        scheduler.add_job(
            _poll_pending_uploads,
            "interval",
            seconds=settings.scheduler_poll_interval_s,
            args=[app],
        )
        scheduler.start()

        yield

        scheduler.shutdown(wait=False)
        if observer:
            observer.stop()
            observer.join()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LinkedIn Auto-Publisher",
        version="0.1.0",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins != ["*"] else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(APIKeyMiddleware, api_key=settings.api_key)

    app.include_router(health.router)
    app.include_router(pipeline.router)

    return app


app = create_app()
