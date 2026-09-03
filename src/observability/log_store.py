"""In-memory log ring buffer + safe DB log writer for the dashboard.

Two independent sinks, both defensive (an exception in logging must never
propagate into request or pipeline code):

* ``RING`` — a bounded, thread-safe deque of recent log records, fed by a
  stdlib ``logging.Handler`` attached to the root logger. This captures
  everything: uvicorn, httpx, langgraph, structlog output, and the
  pipeline's own logger. The dashboard polls ``GET /api/logs`` to render it.

* ``log_event`` — writes a row to the ``logs`` table for durable,
  post-scoped events (node start/finish/error, publish result, ...).
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import Any

_MAX = 2000

_LEVEL_ORDER = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}


class LogRing:
    """Thread-safe bounded buffer of recent log records."""

    def __init__(self, maxlen: int = _MAX) -> None:
        self._buf: deque[dict] = deque(maxlen=maxlen)
        self._lock = Lock()
        self._seq = 0

    def add(self, record: dict) -> None:
        with self._lock:
            self._seq += 1
            record["seq"] = self._seq
            self._buf.append(record)

    def query(
        self,
        after_seq: int = 0,
        level: str | None = None,
        contains: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        min_level = _LEVEL_ORDER.get((level or "").lower(), 0)
        needle = (contains or "").lower()
        with self._lock:
            items = list(self._buf)
        out = []
        for r in items:
            if r["seq"] <= after_seq:
                continue
            if min_level and _LEVEL_ORDER.get(r["level"], 20) < min_level:
                continue
            if needle and needle not in r["message"].lower() and needle not in r.get("logger", "").lower():
                continue
            out.append(r)
        return out[-limit:]

    def latest_seq(self) -> int:
        with self._lock:
            return self._seq

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


RING = LogRing()


class RingHandler(logging.Handler):
    """Feeds every stdlib log record into RING. Never raises."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            msg = record.getMessage()
        except Exception:
            try:
                msg = str(record.msg)
            except Exception:
                msg = "<unrenderable log message>"
        try:
            RING.add(
                {
                    "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                    "level": record.levelname.lower(),
                    "logger": record.name,
                    "message": msg[:4000],
                }
            )
        except Exception:
            # Logging must never break the caller.
            pass


def install_ring_handler(level: int = logging.INFO, maxlen: int = _MAX) -> None:
    """Attach the ring handler to the root logger (idempotent)."""
    global RING
    if RING._buf.maxlen != maxlen:
        RING = LogRing(maxlen=maxlen)
    root = logging.getLogger()
    if not any(isinstance(h, RingHandler) for h in root.handlers):
        h = RingHandler()
        h.setLevel(level)
        root.addHandler(h)
    # Make sure our pipeline logger propagates to root.
    logging.getLogger("pipeline").setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Durable, post-scoped events -> logs table
# ---------------------------------------------------------------------------

_pylog = logging.getLogger("pipeline")


async def log_event(
    level: str,
    message: str,
    *,
    node: str | None = None,
    post_id: uuid.UUID | None = None,
    upload_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort write to the ``logs`` table + the ring (via the pylogger).

    Any failure here is swallowed and reported to the ring only — a logging
    failure must never abort a pipeline node.
    """
    tag = f"[{node}] " if node else ""
    getattr(_pylog, level if level in _LEVEL_ORDER else "info", _pylog.info)(f"{tag}{message}")

    try:
        from src.database import AsyncSessionLocal  # noqa: PLC0415
        from src.models.log import Log  # noqa: PLC0415

        async with AsyncSessionLocal() as session:
            session.add(
                Log(
                    post_id=post_id,
                    upload_id=upload_id,
                    node_name=node,
                    level=level if level in _LEVEL_ORDER else "info",
                    message=message[:8000],
                    log_metadata=metadata or {},
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — a logging failure must never abort a caller
        try:
            RING.add(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "level": "warning",
                    "logger": "log_store",
                    "message": f"log_event DB write skipped: {type(exc).__name__}",
                }
            )
        except Exception:
            pass


def log_event_sync(level: str, message: str, **kw: Any) -> None:
    """Fire-and-forget sync entry point (schedules the coroutine if a loop runs)."""
    import asyncio  # noqa: PLC0415

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(log_event(level, message, **kw))
    except RuntimeError:
        try:
            asyncio.run(log_event(level, message, **kw))
        except Exception:
            _pylog.info(message)


__all__ = ["RING", "install_ring_handler", "log_event", "log_event_sync", "LogRing"]
