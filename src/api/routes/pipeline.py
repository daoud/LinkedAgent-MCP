from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database import AsyncSessionLocal, get_db
from src.models.approval import Approval
from src.models.content_upload import ContentUpload
from src.models.post import Post
from src.pipeline.state import PipelineState

try:
    from langgraph.types import Command
except ImportError:
    from langgraph.pregel import Command  # type: ignore[assignment]

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class TriggerRequest(BaseModel):
    upload_id: uuid.UUID
    dry_run: bool = True


class ApprovalRequest(BaseModel):
    decision: str  # "approved" | "rejected"
    decided_by: str = "api"


async def _run_pipeline(graph, upload_id: uuid.UUID, dry_run: bool, thread_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    state: PipelineState = {"upload_id": upload_id, "dry_run": dry_run}
    try:
        async for _ in graph.astream(state, config=config):
            pass
    except Exception as exc:
        print(f"[pipeline] Error for upload {upload_id}: {exc}")


@router.post("/trigger")
async def trigger(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    thread_id = f"upload-{body.upload_id}"
    background_tasks.add_task(
        _run_pipeline, request.app.state.graph, body.upload_id, body.dry_run, thread_id
    )
    return {"status": "accepted", "upload_id": str(body.upload_id), "thread_id": thread_id}


@router.get("/status/{post_id}")
async def status(post_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    r = await session.execute(select(Post).where(Post.id == post_id))
    post = r.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return {
        "post_id": str(post.id),
        "status": post.status,
        "upload_id": str(post.upload_id) if post.upload_id else None,
        "scheduled_date": post.scheduled_date.isoformat() if post.scheduled_date else None,
        "scheduled_slot": post.scheduled_slot.isoformat() if post.scheduled_slot else None,
        "linkedin_post_id": post.linkedin_post_id,
        "last_error": post.last_error,
        "failed_at_node": post.failed_at_node,
        "retry_count": post.retry_count,
        "tokens_used": post.tokens_used,
        "cost_usd": float(post.cost_usd) if post.cost_usd else None,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "published_at": post.published_at.isoformat() if post.published_at else None,
    }


@router.post("/upload")
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    request: Request,
    dry_run: bool = True,
):
    settings = get_settings()
    content_dir = Path(settings.local_content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)

    file_bytes = await file.read()
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    file_name = file.filename or f"{uuid.uuid4()}.txt"
    dest = content_dir / file_name
    dest.write_bytes(file_bytes)

    mime_type = file.content_type or mimetypes.guess_type(str(dest))[0]
    file_type = _classify_file_type(mime_type, dest.suffix.lower())

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(ContentUpload).where(ContentUpload.content_hash == content_hash)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Duplicate content — already uploaded")

        upload = ContentUpload(
            file_name=dest.name,
            storage_path=str(dest),
            storage_type="local",
            mime_type=mime_type,
            file_type=file_type,
            content_hash=content_hash,
            file_size_bytes=len(file_bytes),
            status="processing",
        )
        session.add(upload)
        await session.commit()
        upload_id = upload.id

    thread_id = f"upload-{upload_id}"
    background_tasks.add_task(
        _run_pipeline, request.app.state.graph, upload_id, dry_run, thread_id
    )
    return {"status": "accepted", "upload_id": str(upload_id), "thread_id": thread_id}


@router.post("/retry/{post_id}")
async def retry(
    post_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    dry_run: bool = True,
):
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Post).where(Post.id == post_id))
        post = r.scalar_one_or_none()
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.upload_id is None:
            raise HTTPException(status_code=400, detail="Post has no associated upload")
        upload_id = post.upload_id
        post.status = "processing"
        post.retry_count = (post.retry_count or 0) + 1
        post.last_error = None
        post.failed_at_node = None
        await session.commit()

    # Fresh thread_id so the retry starts from scratch rather than resuming a paused graph
    thread_id = f"retry-{post_id}-{uuid.uuid4().hex[:8]}"
    background_tasks.add_task(
        _run_pipeline, request.app.state.graph, upload_id, dry_run, thread_id
    )
    return {"status": "accepted", "post_id": str(post_id), "thread_id": thread_id}


@router.post("/approve/{approval_id}")
async def approve(
    approval_id: uuid.UUID,
    body: ApprovalRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")

    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Approval).where(Approval.id == approval_id))
        approval = r.scalar_one_or_none()
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")

        r2 = await session.execute(select(Post).where(Post.id == approval.post_id))
        post = r2.scalar_one()
        upload_id = post.upload_id

    # thread_id must match the one used when the graph first ran for this upload
    thread_id = f"upload-{upload_id}"
    graph = request.app.state.graph
    decision = body.decision
    decided_by = body.decided_by

    async def _resume() -> None:
        config = {"configurable": {"thread_id": thread_id}}
        try:
            async for _ in graph.astream(
                Command(resume={"decision": decision, "decided_by": decided_by}),
                config=config,
            ):
                pass
        except Exception as exc:
            print(f"[pipeline] Resume error for approval {approval_id}: {exc}")

    background_tasks.add_task(_resume)
    return {"status": "accepted", "approval_id": str(approval_id), "decision": body.decision}


def _classify_file_type(mime_type: str | None, suffix: str) -> str:
    if mime_type:
        if mime_type == "application/pdf":
            return "document"
        if "wordprocessingml" in mime_type or "opendocument" in mime_type:
            return "document"
        if mime_type in ("text/markdown", "text/x-markdown"):
            return "markdown"
        if mime_type.startswith("text/"):
            return "text"
        if mime_type.startswith("image/"):
            return "image"
    if suffix in (".pdf", ".docx", ".doc", ".odt"):
        return "document"
    if suffix in (".md", ".markdown"):
        return "markdown"
    if suffix in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        return "image"
    return "text"
