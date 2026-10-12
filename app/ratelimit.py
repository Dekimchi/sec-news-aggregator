from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from starlette.requests import Request


class SlidingWindowLimiter:
    """Simple in-memory sliding window limiter (single-process)."""

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def retry_after(self, key: str) -> int:
        now = time.time()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if not bucket:
                return self.window
            return max(1, int(self.window - (now - bucket[0])) + 1)


# Login: 5 attempts / 10 minutes per IP
login_limiter = SlidingWindowLimiter(limit=5, window_seconds=600)


def client_ip(request: Request) -> str:
    """Prefer X-Forwarded-For only when request comes from local reverse proxy."""
    peer = request.client.host if request.client else ""
    if peer in {"127.0.0.1", "::1"}:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or peer or "unknown"
    return peer or "unknown"
