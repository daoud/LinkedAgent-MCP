"""JSON API that backs the dashboard UI.

Design rules for this module:
  * No handler may raise past FastAPI — every route wraps its work and returns
    a structured ``{"ok": false, "error": ...}`` on failure (HTTP 200 or a
    deliberate 4xx). The global exception handler in ``app.py`` is the final
    net; this layer keeps the UI usable when something downstream is broken.
  * All heavy work (subprocess, LinkedIn, pipeline) is dispatched, never
    awaited inline in a way that could hang a request.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.linkedin.auth import LinkedInAuth
from src.linkedin.client import LinkedInClient
from src.models.approval import Approval
from src.models.content_upload import ContentUpload
from src.models.llm_cost import LLMCost
from src.models.log import Log
from src.models.post import Post
from src.models.prompt_template import PromptTemplate
from src.observability.log_store import RING, log_event
from src.pipeline.resume import resume_pipeline_for_approval
from src.pipeline.runner import run_pipeline

router = APIRouter(prefix="/api", tags=["dashboard"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_TEXT_EXT = {".txt", ".md", ".markdown", ".pdf", ".doc", ".docx"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _err(msg: str, status: int = 200, **extra: Any) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(msg), **extra}, status_code=status)


def _ok(**data: Any) -> dict:
    return {"ok": True, **data}


def _post_dict(p: Post, *, full: bool = False) -> dict:
    d = {
        "id": str(p.id),
        "title": p.title,
        "status": p.status,
        "source": p.source,
        "tone": p.tone,
        "upload_id": str(p.upload_id) if p.upload_id else None,
        "scheduled_date": p.scheduled_date.isoformat() if p.scheduled_date else None,
        "scheduled_slot": p.scheduled_slot.strftime("%H:%M") if p.scheduled_slot else None,
        "linkedin_post_id": p.linkedin_post_id,
        "linkedin_url": (
            f"https://www.linkedin.com/feed/update/{p.linkedin_post_id}"
            if p.linkedin_post_id
            else None
        ),
        "has_image": bool(p.image_path),
        "image_url": f"/api/media/{Path(p.image_path).name}" if p.image_path else None,
        "last_error": p.last_error,
        "failed_at_node": p.failed_at_node,
        "retry_count": p.retry_count,
        "tokens_used": p.tokens_used,
        "cost_usd": float(p.cost_usd) if p.cost_usd is not None else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "published_at": p.published_at.isoformat() if p.published_at else None,
        "preview": (p.transformed_text or p.raw_content or "")[:160],
    }
    if full:
        d["raw_content"] = p.raw_content
        d["transformed_text"] = p.transformed_text
        d["image_asset_urn"] = p.image_asset_urn
    return d


# ---------------------------------------------------------------------------
# overview / config
# ---------------------------------------------------------------------------

@router.get("/overview")
async def overview() -> Any:
    try:
        settings = get_settings()
        async with AsyncSessionLocal() as session:
            counts = {
                row.status: row.n
                for row in (
                    await session.execute(
                        select(Post.status, func.count(Post.id).label("n")).group_by(Post.status)
                    )
                ).all()
            }
            total_cost = float(
                (await session.execute(select(func.sum(LLMCost.cost_usd)))).scalar_one_or_none()
                or 0.0
            )
            month_start = datetime.now(UTC).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            month_cost = float(
                (
                    await session.execute(
                        select(func.sum(LLMCost.cost_usd)).where(LLMCost.recorded_at >= month_start)
                    )
                ).scalar_one_or_none()
                or 0.0
            )
            pending = int(
                (
                    await session.execute(
                        select(func.count(Approval.id)).where(Approval.decision == "pending")
                    )
                ).scalar_one()
            )
            published = int(
                (
                    await session.execute(
                        select(func.count(Post.id)).where(Post.status == "published")
                    )
                ).scalar_one()
            )
            db_ok = True
    except SQLAlchemyError as exc:
        return _err(f"database unavailable: {exc}")

    token = _token_status()
    return _ok(
        counts=counts,
        published=published,
        pending_approvals=pending,
        total_cost_usd=round(total_cost, 4),
        month_cost_usd=round(month_cost, 4),
        month_budget_usd=settings.llm_monthly_budget,
        token=token,
        db_ok=db_ok,
        config={
            "approval_required": settings.approval_required,
            "auto_publish_dry_run": settings.auto_publish_dry_run,
            "daily_post_limit": settings.daily_post_limit,
            "post_slots": settings.post_slots,
            "timezone": settings.timezone,
            "llm_model": settings.llm_model,
            "storage_mode": settings.storage_mode,
            "google_sheet_configured": bool(settings.google_sheet_id),
            "slack_configured": bool(settings.slack_webhook_url),
            "linkedin_profile_urn": settings.linkedin_profile_urn,
        },
    )


@router.get("/config")
async def config() -> Any:
    s = get_settings()
    return _ok(
        config={
            "environment": s.environment,
            "timezone": s.timezone,
            "storage_mode": s.storage_mode,
            "local_content_dir": s.local_content_dir,
            "media_dir": s.media_dir,
            "llm_model": s.llm_model,
            "llm_monthly_budget": s.llm_monthly_budget,
            "daily_post_limit": s.daily_post_limit,
            "post_slots": s.post_slots,
            "approval_required": s.approval_required,
            "approval_timeout_h": s.approval_timeout_h,
            "auto_publish_dry_run": s.auto_publish_dry_run,
            "google_sheet_configured": bool(s.google_sheet_id),
            "slack_configured": bool(s.slack_webhook_url),
            "api_key_set": bool(s.api_key),
            "linkedin_client_configured": bool(s.linkedin_client_id and s.linkedin_client_secret),
            "linkedin_token_configured": bool(s.linkedin_access_token),
            "linkedin_profile_urn": s.linkedin_profile_urn,
            "anthropic_key_set": bool(s.anthropic_api_key),
        }
    )


def _token_status() -> dict:
    try:
        auth = LinkedInAuth.from_settings(get_settings())
        days = auth.days_until_expiry()
        if days is None:
            return {"state": "unknown", "days": None, "message": "expiry not recorded"}
        if days < 0:
            return {"state": "expired", "days": round(days, 1), "message": "re-authorize now"}
        if days < 7:
            return {"state": "critical", "days": round(days, 1), "message": "refresh immediately"}
        if days < 14:
            return {"state": "warning", "days": round(days, 1), "message": "refresh soon"}
        return {"state": "ok", "days": round(days, 1), "message": f"{round(days)} days left"}
    except Exception as exc:  # noqa: BLE001
        return {"state": "unknown", "days": None, "message": str(exc)}


# ---------------------------------------------------------------------------
# posts
# ---------------------------------------------------------------------------

@router.get("/posts")
async def list_posts(status: str | None = None, limit: int = 50, offset: int = 0) -> Any:
    limit = max(1, min(limit, 200))
    try:
        async with AsyncSessionLocal() as session:
            q = select(Post).order_by(Post.created_at.desc())
            if status and status != "all":
                q = q.where(Post.status == status)
            rows = list((await session.execute(q.limit(limit).offset(max(0, offset)))).scalars())
            total = int(
                (
                    await session.execute(
                        select(func.count(Post.id)).where(
                            Post.status == status if (status and status != "all") else True
                        )
                    )
                ).scalar_one()
            )
        return _ok(posts=[_post_dict(p) for p in rows], total=total)
    except SQLAlchemyError as exc:
        return _err(f"could not list posts: {exc}")


@router.get("/posts/{post_id}")
async def get_post(post_id: uuid.UUID) -> Any:
    try:
        async with AsyncSessionLocal() as session:
            p = (
                await session.execute(select(Post).where(Post.id == post_id))
            ).scalar_one_or_none()
            if p is None:
                return _err("post not found", status=404)
            approvals = list(
                (
                    await session.execute(
                        select(Approval)
                        .where(Approval.post_id == post_id)
                        .order_by(Approval.created_at.desc())
                    )
                ).scalars()
            )
            logs = list(
                (
                    await session.execute(
                        select(Log)
                        .where(Log.post_id == post_id)
                        .order_by(Log.created_at.asc())
                        .limit(200)
                    )
                ).scalars()
            )
        return _ok(
            post=_post_dict(p, full=True),
            approvals=[
                {
                    "id": str(a.id),
                    "decision": a.decision,
                    "decided_by": a.decided_by,
                    "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                    "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in approvals
            ],
            logs=[
                {
                    "ts": lg.created_at.isoformat() if lg.created_at else None,
                    "level": lg.level,
                    "node": lg.node_name,
                    "message": lg.message,
                }
                for lg in logs
            ],
        )
    except SQLAlchemyError as exc:
        return _err(f"could not load post: {exc}")


@router.patch("/posts/{post_id}")
async def patch_post(post_id: uuid.UUID, request: Request) -> Any:
    try:
        body = await request.json()
    except Exception:
        return _err("invalid JSON body", status=400)
    new_text = body.get("transformed_text")
    new_title = body.get("title")
    try:
        async with AsyncSessionLocal() as session:
            p = (
                await session.execute(select(Post).where(Post.id == post_id))
            ).scalar_one_or_none()
            if p is None:
                return _err("post not found", status=404)
            if p.status in ("published", "publishing"):
                return _err("cannot edit a post that is already publishing/published", status=409)
            if new_text is not None:
                p.transformed_text = str(new_text)
            if new_title is not None:
                p.title = str(new_title)[:200]
            await session.commit()
            out = _post_dict(p, full=True)
        await log_event("info", "Draft edited from dashboard", node="dashboard", post_id=post_id)
        return _ok(post=out)
    except SQLAlchemyError as exc:
        return _err(f"could not update post: {exc}")


@router.post("/posts/{post_id}/retry")
async def retry_post(post_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks) -> Any:
    try:
        dry_run = _bool(request.query_params.get("dry_run"), default=True)
        async with AsyncSessionLocal() as session:
            p = (
                await session.execute(select(Post).where(Post.id == post_id))
            ).scalar_one_or_none()
            if p is None:
                return _err("post not found", status=404)
            if p.upload_id is None:
                return _err("post has no source upload to retry from", status=400)
            upload_id = p.upload_id
            p.status = "processing"
            p.retry_count = (p.retry_count or 0) + 1
            p.last_error = None
            p.failed_at_node = None
            await session.commit()
        thread_id = f"retry-{post_id}-{uuid.uuid4().hex[:8]}"
        background_tasks.add_task(
            run_pipeline,
            request.app.state.graph,
            upload_id,
            dry_run=dry_run,
            thread_id=thread_id,
            post_id=post_id,
        )
        await log_event("info", f"Retry requested (dry_run={dry_run})", node="dashboard", post_id=post_id)
        return _ok(post_id=str(post_id), thread_id=thread_id)
    except SQLAlchemyError as exc:
        return _err(f"could not retry: {exc}")


@router.post("/posts/{post_id}/decision")
async def post_decision(post_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks) -> Any:
    try:
        body = await request.json()
    except Exception:
        return _err("invalid JSON body", status=400)
    decision = body.get("decision")
    decided_by = body.get("decided_by") or "dashboard"
    if decision not in ("approved", "rejected"):
        return _err("decision must be 'approved' or 'rejected'", status=400)
    try:
        async with AsyncSessionLocal() as session:
            a = (
                await session.execute(
                    select(Approval)
                    .where(Approval.post_id == post_id, Approval.decision == "pending")
                    .order_by(Approval.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if a is None:
                return _err("no pending approval for this post", status=404)
            approval_id = a.id
        background_tasks.add_task(
            resume_pipeline_for_approval,
            request.app.state.graph,
            approval_id,
            decision,
            decided_by,
        )
        await log_event("info", f"Approval decision: {decision} by {decided_by}", node="dashboard", post_id=post_id)
        return _ok(approval_id=str(approval_id), decision=decision)
    except SQLAlchemyError as exc:
        return _err(f"could not record decision: {exc}")


@router.post("/posts/{post_id}/delete-linkedin")
async def delete_from_linkedin(post_id: uuid.UUID) -> Any:
    """Delete a published post from LinkedIn and clear its id on the row."""
    settings = get_settings()
    try:
        async with AsyncSessionLocal() as session:
            p = (
                await session.execute(select(Post).where(Post.id == post_id))
            ).scalar_one_or_none()
            if p is None:
                return _err("post not found", status=404)
            urn = p.linkedin_post_id
        if not urn:
            return _err("this post has no LinkedIn id — nothing to delete", status=400)
        if not settings.linkedin_access_token:
            return _err("LinkedIn is not configured", status=400)

        auth = LinkedInAuth.from_settings(settings)
        client = LinkedInClient(auth=auth, profile_urn=settings.linkedin_profile_urn or "urn:li:person:unknown")
        try:
            ok = await asyncio.to_thread(client.delete_post, urn)
        except Exception as exc:  # noqa: BLE001
            await log_event("error", f"LinkedIn delete failed for {urn}: {exc}", node="dashboard", post_id=post_id)
            return _err(f"LinkedIn API error: {exc}")
        if not ok:
            return _err("LinkedIn rejected the delete — the post may still be live")

        async with AsyncSessionLocal() as session:
            p = (
                await session.execute(select(Post).where(Post.id == post_id))
            ).scalar_one_or_none()
            if p is not None:
                p.status = "rejected"
                p.last_error = f"Deleted from LinkedIn via dashboard ({urn})"
                p.linkedin_post_id = None
                await session.commit()
        await log_event("info", f"Deleted from LinkedIn: {urn}", node="dashboard", post_id=post_id)
        return _ok(deleted=urn)
    except SQLAlchemyError as exc:
        return _err(f"database error: {exc}")


# ---------------------------------------------------------------------------
# approvals
# ---------------------------------------------------------------------------

@router.get("/approvals")
async def list_approvals() -> Any:
    try:
        async with AsyncSessionLocal() as session:
            rows = list(
                (
                    await session.execute(
                        select(Approval, Post)
                        .join(Post, Post.id == Approval.post_id)
                        .where(Approval.decision == "pending")
                        .order_by(Approval.created_at.asc())
                    )
                ).all()
            )
        now = datetime.now(UTC)
        out = []
        for a, p in rows:
            expires_in = None
            if a.expires_at:
                exp = a.expires_at if a.expires_at.tzinfo else a.expires_at.replace(tzinfo=UTC)
                expires_in = round((exp - now).total_seconds() / 3600, 1)
            out.append(
                {
                    "id": str(a.id),
                    "post_id": str(a.post_id),
                    "title": p.title,
                    "preview_text": a.preview_text,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "expires_in_h": expires_in,
                    "scheduled_date": p.scheduled_date.isoformat() if p.scheduled_date else None,
                    "scheduled_slot": p.scheduled_slot.strftime("%H:%M") if p.scheduled_slot else None,
                }
            )
        return _ok(approvals=out)
    except SQLAlchemyError as exc:
        return _err(f"could not list approvals: {exc}")


@router.post("/approvals/{approval_id}")
async def decide_approval(approval_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks) -> Any:
    try:
        body = await request.json()
    except Exception:
        return _err("invalid JSON body", status=400)
    decision = body.get("decision")
    decided_by = body.get("decided_by") or "dashboard"
    if decision not in ("approved", "rejected"):
        return _err("decision must be 'approved' or 'rejected'", status=400)
    try:
        async with AsyncSessionLocal() as session:
            a = (
                await session.execute(select(Approval).where(Approval.id == approval_id))
            ).scalar_one_or_none()
            if a is None:
                return _err("approval not found", status=404)
        background_tasks.add_task(
            resume_pipeline_for_approval,
            request.app.state.graph,
            approval_id,
            decision,
            decided_by,
        )
        return _ok(approval_id=str(approval_id), decision=decision)
    except SQLAlchemyError as exc:
        return _err(f"could not decide: {exc}")


# ---------------------------------------------------------------------------
# prompt templates
# ---------------------------------------------------------------------------

@router.get("/templates")
async def list_templates() -> Any:
    try:
        async with AsyncSessionLocal() as session:
            rows = list(
                (
                    await session.execute(
                        select(PromptTemplate).order_by(
                            PromptTemplate.name, PromptTemplate.version.desc()
                        )
                    )
                ).scalars()
            )
        return _ok(
            templates=[
                {
                    "id": str(t.id),
                    "name": t.name,
                    "version": t.version,
                    "template_text": t.template_text,
                    "variables": t.variables or {},
                    "is_active": bool(t.is_active),
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in rows
            ]
        )
    except SQLAlchemyError as exc:
        return _err(f"could not list templates: {exc}")


@router.post("/templates")
async def save_template(request: Request) -> Any:
    """Create a new version of a template and make it the active one."""
    try:
        body = await request.json()
    except Exception:
        return _err("invalid JSON body", status=400)
    name = (body.get("name") or "linkedin_post").strip()
    text = body.get("template_text")
    if not text or "{content}" not in text:
        return _err("template_text is required and must contain the {content} placeholder", status=400)
    try:
        async with AsyncSessionLocal() as session:
            latest = (
                await session.execute(
                    select(PromptTemplate)
                    .where(PromptTemplate.name == name)
                    .order_by(PromptTemplate.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            next_version = (latest.version + 1) if latest else 1
            # deactivate every existing version of this name
            for t in (
                await session.execute(
                    select(PromptTemplate).where(PromptTemplate.name == name)
                )
            ).scalars():
                t.is_active = False
            row = PromptTemplate(
                name=name,
                version=next_version,
                template_text=text,
                variables=body.get("variables") or {"content": "source", "tone": "tone"},
                is_active=True,
            )
            session.add(row)
            await session.commit()
            tid = str(row.id)
        await log_event("info", f"Prompt template '{name}' v{next_version} saved & activated", node="dashboard")
        return _ok(id=tid, name=name, version=next_version)
    except SQLAlchemyError as exc:
        return _err(f"could not save template: {exc}")


@router.post("/templates/{template_id}/activate")
async def activate_template(template_id: uuid.UUID) -> Any:
    try:
        async with AsyncSessionLocal() as session:
            t = (
                await session.execute(select(PromptTemplate).where(PromptTemplate.id == template_id))
            ).scalar_one_or_none()
            if t is None:
                return _err("template not found", status=404)
            for other in (
                await session.execute(
                    select(PromptTemplate).where(PromptTemplate.name == t.name)
                )
            ).scalars():
                other.is_active = other.id == t.id
            await session.commit()
        return _ok(id=str(template_id))
    except SQLAlchemyError as exc:
        return _err(f"could not activate template: {exc}")


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------

@router.get("/logs")
async def get_logs(after_seq: int = 0, level: str | None = None, q: str | None = None, limit: int = 500) -> Any:
    try:
        items = RING.query(after_seq=after_seq, level=level, contains=q, limit=max(1, min(limit, 2000)))
        return _ok(logs=items, latest_seq=RING.latest_seq())
    except Exception as exc:  # noqa: BLE001
        return _err(f"log read failed: {exc}")


@router.post("/logs/clear")
async def clear_logs() -> Any:
    RING.clear()
    return _ok()


# ---------------------------------------------------------------------------
# media
# ---------------------------------------------------------------------------

@router.get("/media/{name}")
async def get_media(name: str) -> Any:
    safe = Path(name).name  # strip any path components
    path = Path(get_settings().media_dir) / safe
    if not path.is_file():
        return _err("not found", status=404)
    return FileResponse(str(path))


# ---------------------------------------------------------------------------
# compose — the main "write a post" entry point
# ---------------------------------------------------------------------------

@router.post("/compose")
async def compose(
    request: Request,
    background_tasks: BackgroundTasks,
    text: str = Form(default=""),
    title: str = Form(default=""),
    tone: str = Form(default="professional and insightful"),
    dry_run: str = Form(default="true"),
    file: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
) -> Any:
    settings = get_settings()
    is_dry = _bool(dry_run, default=True)

    # ---- resolve the source content ----
    try:
        if file is not None:
            raw_bytes = await file.read()
            src_name = Path(file.filename or f"{uuid.uuid4().hex}.txt").name
            if Path(src_name).suffix.lower() not in _TEXT_EXT:
                return _err(f"unsupported content file type: {Path(src_name).suffix}", status=400)
        elif text.strip():
            raw_bytes = text.strip().encode("utf-8")
            slug = "".join(c for c in (title or "post")[:40] if c.isalnum() or c in "-_ ").strip().replace(" ", "-")
            src_name = f"compose-{slug or 'post'}-{uuid.uuid4().hex[:8]}.md"
        else:
            return _err("provide either 'text' or a content 'file'", status=400)
    except Exception as exc:  # noqa: BLE001
        return _err(f"could not read content: {exc}", status=400)

    content_dir = Path(settings.local_content_dir)
    try:
        content_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return _err(f"content dir not writable: {exc}")

    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    dest = content_dir / src_name
    mime_type = mimetypes.guess_type(src_name)[0] or "text/plain"

    # ---- optional image ----
    image_path: str | None = None
    if image is not None and (image.filename or ""):
        ext = Path(image.filename).suffix.lower()
        if ext not in _IMAGE_EXT:
            return _err(f"unsupported image type: {ext}", status=400)
        try:
            img_bytes = await image.read()
            if len(img_bytes) > 12 * 1024 * 1024:
                return _err("image too large (max 12 MB)", status=400)
            media_dir = Path(settings.media_dir)
            media_dir.mkdir(parents=True, exist_ok=True)
            image_path = str(media_dir / f"{uuid.uuid4().hex}{ext}")
            Path(image_path).write_bytes(img_bytes)
        except Exception as exc:  # noqa: BLE001
            return _err(f"could not store image: {exc}")

    # ---- create the ContentUpload row, then write the file ----
    try:
        async with AsyncSessionLocal() as session:
            dup = (
                await session.execute(
                    select(ContentUpload).where(ContentUpload.content_hash == content_hash)
                )
            ).scalar_one_or_none()
            if dup is not None:
                return _err(
                    "this exact content was already submitted — edit it or change the wording",
                    status=409,
                )
            upload = ContentUpload(
                file_name=dest.name,
                storage_path=str(dest),
                storage_type="local",
                mime_type=mime_type,
                file_type="markdown" if dest.suffix.lower() in (".md", ".markdown") else "text",
                content_hash=content_hash,
                file_size_bytes=len(raw_bytes),
                status="processing",
            )
            session.add(upload)
            await session.commit()
            upload_id = upload.id
    except SQLAlchemyError as exc:
        return _err(f"database error: {exc}")

    try:
        dest.write_bytes(raw_bytes)
    except Exception as exc:  # noqa: BLE001
        return _err(f"could not write content file: {exc}")

    thread_id = f"upload-{upload_id}"
    background_tasks.add_task(
        run_pipeline,
        request.app.state.graph,
        upload_id,
        dry_run=is_dry,
        thread_id=thread_id,
        extra_state={
            "source": "compose" if file is not None else "compose-text",
            "tone": tone.strip() or None,
            "title": (title or "").strip() or None,
            "image_path": image_path,
        },
    )
    await log_event(
        "info",
        f"Compose submitted (dry_run={is_dry}, image={'yes' if image_path else 'no'}): "
        f"{(title or src_name)[:80]}",
        node="dashboard",
        upload_id=upload_id,
    )
    return _ok(upload_id=str(upload_id), thread_id=thread_id, dry_run=is_dry)


# ---------------------------------------------------------------------------
# ops panel — run project scripts
# ---------------------------------------------------------------------------

_PYBIN = str(Path(sys.executable))

_OPS: dict[str, list[str]] = {
    "migrate": [str(_REPO_ROOT / "venv" / "bin" / "alembic"), "upgrade", "head"],
    "seed": [_PYBIN, str(_REPO_ROOT / "scripts" / "seed_prompt_template.py")],
    "token": [_PYBIN, str(_REPO_ROOT / "scripts" / "check_token_expiry.py")],
    "checklist": [_PYBIN, str(_REPO_ROOT / "scripts" / "production_checklist.py")],
}


@router.post("/ops/{action}")
async def run_op(action: str) -> Any:
    if action not in _OPS:
        return _err(f"unknown op '{action}' (allowed: {', '.join(_OPS)})", status=404)
    cmd = list(_OPS[action])
    if not Path(cmd[0]).exists() and action == "migrate":
        cmd = [_PYBIN, "-m", "alembic", "upgrade", "head"]
    started = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(_REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError:
            proc.kill()
            return _err(f"op '{action}' timed out after 120s", exit_code=None)
    except Exception as exc:  # noqa: BLE001
        return _err(f"could not run op '{action}': {exc}")

    output = (out or b"").decode("utf-8", errors="replace")
    took = round(time.time() - started, 1)
    await log_event(
        "info" if proc.returncode == 0 else "warning",
        f"ops:{action} exited {proc.returncode} in {took}s",
        node="ops",
    )
    return _ok(
        action=action,
        exit_code=proc.returncode,
        took_s=took,
        output=output[-8000:],
    )


@router.get("/ops/linkedin-auth-url")
async def linkedin_auth_url() -> Any:
    s = get_settings()
    if not s.linkedin_client_id:
        return _err("LINKEDIN_CLIENT_ID not configured", status=400)
    import urllib.parse  # noqa: PLC0415

    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": s.linkedin_client_id,
            "redirect_uri": "http://localhost:8080/auth/callback",
            "scope": "w_member_social openid profile",
            "state": uuid.uuid4().hex,
        }
    )
    return _ok(
        url=f"https://www.linkedin.com/oauth/v2/authorization?{params}",
        note="Run `python scripts/linkedin_first_auth.py` locally to complete the flow "
        "and capture the tokens — this URL is for reference / manual auth.",
    )


# ---------------------------------------------------------------------------
# util
# ---------------------------------------------------------------------------

def _bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")
