"""
services/ratelimit.py
---------------------
Tiny in-memory sliding-window rate limiter used as a FastAPI dependency.

Per-process only, which is right for a single container. Put Redis behind it
if you scale horizontally.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, name: str, limit: int, window_seconds: int = 60) -> None:
        self.name = name
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def __call__(self, request: Request) -> None:
        if self.limit <= 0:
            return
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = int(self.window - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many requests. Try again in {retry}s.",
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)
