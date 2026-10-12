"""A small in-memory rate limiter for public endpoints.

Good enough for a single server process. If the API ever runs on several
instances, move this to a shared store (e.g. Redis or the database).
"""

import time
from collections import defaultdict, deque
from threading import Lock

from app.errors import ApiError


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = int(self.window - (now - hits[0])) + 1
                raise ApiError(429, "RATE_LIMITED", "Too many attempts. Please wait a minute and try again.",
                               {"retry_after_seconds": retry})
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
