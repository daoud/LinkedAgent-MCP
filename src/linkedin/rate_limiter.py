from __future__ import annotations

import time
from threading import Lock
from typing import Any, Optional


class RateLimiter:
    """In-memory token-bucket rate limiter for LinkedIn API calls.

    LinkedIn allows 100 UGC post creations per day per application.
    Remaining quota is updated from response headers after each call.
    """

    def __init__(self, max_calls_per_day: int = 100) -> None:
        self.max_calls = max_calls_per_day
        self._remaining = max_calls_per_day
        self._reset_at: Optional[float] = None
        self._lock = Lock()

    # ---- public API --------------------------------------------------------

    def wait_if_needed(self) -> None:
        """Block if the rate limit has been exhausted, then consume one token."""
        with self._lock:
            self._maybe_reset()
            if self._remaining <= 0:
                if self._reset_at is None:
                    # We don't know when the quota resets (no rate-limit
                    # headers seen yet) — block conservatively for a fixed
                    # interval instead of resetting immediately, which would
                    # make the daily cap a no-op once headers stop arriving.
                    time.sleep(60.0)
                else:
                    sleep_secs = max(0.0, self._reset_at - time.time())
                    if sleep_secs > 0:
                        time.sleep(sleep_secs)
                    self._remaining = self.max_calls
                    self._reset_at = None
            self._remaining -= 1

    def update_from_headers(self, headers: Any) -> None:
        """Parse X-RateLimit-* headers from a LinkedIn response and update state."""
        with self._lock:
            remaining = (
                headers.get("x-ratelimit-remaining")
                or headers.get("X-RateLimit-Remaining")
            )
            if remaining is not None:
                self._remaining = int(remaining)

            limit = headers.get("x-ratelimit-limit") or headers.get("X-RateLimit-Limit")
            if limit is not None:
                self.max_calls = int(limit)

            reset = headers.get("x-ratelimit-reset") or headers.get("X-RateLimit-Reset")
            if reset is not None:
                self._reset_at = float(reset)

    @property
    def remaining(self) -> int:
        with self._lock:
            self._maybe_reset()
            return self._remaining

    # ---- private -----------------------------------------------------------

    def _maybe_reset(self) -> None:
        if self._reset_at and time.time() >= self._reset_at:
            self._remaining = self.max_calls
            self._reset_at = None
