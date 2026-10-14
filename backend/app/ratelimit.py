"""Rate limiter for public endpoints (login codes, lookups, passphrase tries).

With one server, counts are kept in memory. With several servers, set
SAHYOG_REDIS_URL so every server shares the same counts; if Redis cannot be
reached, the limiter falls back to memory rather than blocking people.
"""

import logging
import time
from collections import defaultdict, deque
from threading import Lock

from app.errors import ApiError

log = logging.getLogger("sahyogcare.ratelimit")
_redis_client = None


def _redis():
    """The shared Redis connection, or None when not configured / not installed."""
    global _redis_client
    from app.config import settings

    if not settings.redis_url:
        return None
    if _redis_client is None:
        try:
            import redis  # optional dependency: pip install redis

            _redis_client = redis.Redis.from_url(settings.redis_url, socket_timeout=1)
        except Exception:  # noqa: BLE001
            log.warning("SAHYOG_REDIS_URL is set but Redis is not available; counting in memory")
            return None
    return _redis_client


def _too_many(retry: int) -> ApiError:
    return ApiError(429, "RATE_LIMITED", "Too many attempts. Please wait a minute and try again.",
                    {"retry_after_seconds": retry})


class RateLimiter:
    _names = 0

    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        RateLimiter._names += 1
        self._prefix = f"sahyog:rl:{RateLimiter._names}:"

    def _check_shared(self, client, key: str) -> bool:
        """Fixed-window count in Redis. Returns False when Redis failed (use memory instead)."""
        try:
            bucket = f"{self._prefix}{key}:{int(time.time() // self.window)}"
            count = client.incr(bucket)
            if count == 1:
                client.expire(bucket, int(self.window) + 1)
        except Exception:  # noqa: BLE001
            log.warning("Redis unreachable; counting in memory")
            return False
        if count > self.limit:
            raise _too_many(int(self.window - time.time() % self.window) + 1)
        return True

    def check(self, key: str) -> None:
        client = _redis()
        if client is not None and self._check_shared(client, key):
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise _too_many(int(self.window - (now - hits[0])) + 1)
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
