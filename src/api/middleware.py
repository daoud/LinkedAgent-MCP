from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Paths that bypass API key authentication
_PUBLIC_PATHS = {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str | None = None) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        if self._api_key and request.url.path not in _PUBLIC_PATHS:
            provided = request.headers.get("X-API-Key", "")
            if provided != self._api_key:
                return JSONResponse(
                    {"detail": "Invalid or missing API key"}, status_code=401
                )
        return await call_next(request)
