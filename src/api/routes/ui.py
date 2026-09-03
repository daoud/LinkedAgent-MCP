"""Serves the single-page dashboard from src/web/."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

router = APIRouter(tags=["ui"])

_WEB = Path(__file__).resolve().parents[2] / "web"

_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


@router.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    idx = _WEB / "index.html"
    if not idx.is_file():
        return HTMLResponse(
            "<h1>Dashboard not installed</h1><p>src/web/index.html is missing.</p>",
            status_code=500,
        )
    return HTMLResponse(idx.read_text(encoding="utf-8"))


@router.get("/assets/{name}", include_in_schema=False)
async def asset(name: str) -> FileResponse:
    safe = Path(name).name
    path = _WEB / safe
    if not path.is_file():
        return PlainTextResponse("not found", status_code=404)
    ct = _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(path), media_type=ct)
