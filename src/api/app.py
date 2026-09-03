from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from src.api.middleware import APIKeyMiddleware
from src.api.routes import dashboard, health, pipeline, ui
from src.approval.poller import ApprovalPoller
from src.approval.sheets_client import SheetsClient
from src.approval.slack_notifier import SlackNotifier
from src.config import get_settings
from src.database import AsyncSessionLocal
from src.ingestion.local_watcher import set_main_loop, start_watcher
from src.models.content_upload import ContentUpload
from src.models.post import Post
from src.observability.log_store import RING, install_ring_handler, log_event
from src.observability.logging import configure_logging
from src.observability.tracing import configure_tracing, instrument_fastapi
from src.pipeline.checkpointer import make_checkpointer
from src.pipeline.graph import build_graph
from src.pipeline.resume import resume_pipeline_for_approval, resume_pipeline_thread
from src.pipeline.runner import run_pipeline


async def _run_pipeline_task(graph, upload_id: uuid.UUID, dry_run: bool, thread_id: str) -> None:
    await run_pipeline(
        graph,
        upload_id,
        dry_run=dry_run,
        thread_id=thread_id,
        extra_state={"source": "watcher"},
    )


async def _poll_pending_uploads(app: FastAPI) -> None:
    """Pick up ContentUploads in 'pending' state and trigger the pipeline for each."""
    dry_run = get_settings().auto_publish_dry_run
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
                _run_pipeline_task(app.state.graph, upload.id, dry_run, thread_id)
            )
        if uploads:
            await session.commit()


async def _poll_approvals(app: FastAPI) -> None:
    """Sync approval decisions from the Sheet, then resume any paused graphs.

    Skipped entirely when Sheets isn't configured (no GOOGLE_SHEET_ID) — the
    approval workflow is opt-in, same as the local content watcher is opt-in
    to STORAGE_MODE=local.
    """
    settings = get_settings()
    if not settings.google_sheet_id:
        return

    try:
        async with AsyncSessionLocal() as session:
            sheets = SheetsClient(settings)
            notifier = SlackNotifier(settings)
            poller = ApprovalPoller(session, sheets, notifier, settings)
            actioned = await poller.poll_once()
            await session.commit()
    except Exception as exc:
        await log_event("warning", f"approval poll_once failed: {exc}", node="approval-poller")
        return

    for approval in actioned:
        await resume_pipeline_for_approval(
            app.state.graph,
            approval.id,
            approval.decision,
            approval.decided_by or "sheet",
        )


async def _poll_scheduled_posts(app: FastAPI) -> None:
    """Resume graphs paused in wait_for_slot_node once their slot time is due.

    Without this, a post's assigned (scheduled_date, scheduled_slot) is just
    metadata — this is what actually makes DAILY_POST_LIMIT / POST_SLOTS
    space posts out across the day instead of publishing them back-to-back
    the moment they're approved.
    """
    settings = get_settings()
    tz = pytz.timezone(settings.timezone)
    now = datetime.now(tz)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Post).where(Post.status == "scheduled"))
        posts = list(result.scalars().all())

    for post in posts:
        if post.scheduled_date is None or post.scheduled_slot is None or post.upload_id is None:
            continue
        slot_at = tz.localize(datetime.combine(post.scheduled_date, post.scheduled_slot))
        if now >= slot_at:
            await resume_pipeline_thread(app.state.graph, f"upload-{post.upload_id}")


def _safe_job(fn):
    """Wrap an APScheduler coroutine job so a failure can never kill the loop."""

    async def _runner(app: FastAPI) -> None:
        try:
            await fn(app)
        except Exception as exc:  # noqa: BLE001
            try:
                await log_event("error", f"scheduler job {fn.__name__} failed: {exc}", node="scheduler")
            except Exception:
                pass

    _runner.__name__ = f"safe_{fn.__name__}"
    return _runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    install_ring_handler(maxlen=settings.log_buffer_size)
    configure_tracing(
        service_name="linkedin-pipeline",
        otlp_endpoint=None,
    )
    await log_event("info", "Service starting up")

    async with make_checkpointer() as checkpointer:
        app.state.graph = build_graph(checkpointer=checkpointer)
        app.state.checkpointer = checkpointer

        set_main_loop(asyncio.get_event_loop())

        observer = None
        if settings.storage_mode == "local":
            observer = start_watcher(settings.local_content_dir)

        scheduler = AsyncIOScheduler(timezone=settings.timezone)
        for _job in (_poll_pending_uploads, _poll_approvals, _poll_scheduled_posts):
            scheduler.add_job(
                _safe_job(_job),
                "interval",
                seconds=settings.scheduler_poll_interval_s,
                args=[app],
            )
        scheduler.start()
        await log_event("info", "Scheduler + folder watcher started")

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
    app.include_router(dashboard.router)
    if settings.ui_enabled:
        app.include_router(ui.router)

    _install_exception_handlers(app)
    instrument_fastapi(app)

    return app


def _install_exception_handlers(app: FastAPI) -> None:
    """Last line of defence — no unhandled error ever reaches the client raw."""
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request, exc):  # noqa: ANN001
        return JSONResponse(
            {"ok": False, "error": exc.detail, "status": exc.status_code},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def _valid_exc(request, exc):  # noqa: ANN001
        return JSONResponse(
            {"ok": False, "error": "invalid request", "detail": exc.errors()[:5]},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _any_exc(request, exc):  # noqa: ANN001
        try:
            RING.add(
                {
                    "ts": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                    "level": "error",
                    "logger": "api",
                    "message": f"Unhandled error on {request.method} {request.url.path}: "
                    f"{type(exc).__name__}: {exc}",
                }
            )
        except Exception:
            pass
        return JSONResponse(
            {
                "ok": False,
                "error": "internal error — the request was logged, the service is still running",
                "type": type(exc).__name__,
            },
            status_code=500,
        )


app = create_app()
