"""In-memory rate limiting (Week 4 section 3.1).

Deliberately simple and explicitly process-local: a sliding window of
request timestamps per client key, held in memory. That is the right
scope for a single Flask dev-server/one-worker MVP, and the honest
limitation to flag -- behind multiple worker processes or machines, each
would enforce its own limit independently rather than sharing one count.
Closing that fully would need a shared store (e.g. Redis); out of scope
here, same as the equivalent caveat on the idempotency store.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from functools import wraps

from flask import current_app, request

from app.errors.handlers import RateLimitedError


class RateLimiter:
    """Sliding-window limiter: at most ``limit`` hits per key per
    ``window_seconds``."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        """Record a hit for ``key`` and return whether it's within the limit."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def _client_key() -> str:
    # One client == one IP for this MVP; a real deployment behind a proxy
    # would want to trust a configured header (e.g. X-Forwarded-For)
    # instead, which is a deployment-specific decision left to whoever
    # sets that up.
    return request.remote_addr or "unknown"


def rate_limited(bucket: str):
    """Decorator: enforce the named limiter bucket (see
    ``app.extensions["rate_limiters"]``) for this route, keyed by client IP."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            limiter: RateLimiter = current_app.extensions["rate_limiters"][bucket]
            if not limiter.allow(_client_key()):
                raise RateLimitedError()
            return view_func(*args, **kwargs)

        return wrapper

    return decorator
