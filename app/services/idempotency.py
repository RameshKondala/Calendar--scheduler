"""In-memory idempotency store for ``POST /appointments``.

Per ADR-006 there is no local appointment database, so this is explicitly
*not* one: it holds only a short-lived cache mapping an ``Idempotency-Key``
to the result of the booking it produced, so a retried request with the
same key replays that result instead of writing to Outlook again. It is
process-local and in-memory by design, which is the honest limitation to
know about -- a retry that lands on a different worker process (behind a
load balancer, say) will not see another process's cache and could still
double-book. Closing that fully would need a shared store (e.g. Redis) or
an Outlook-side marker (e.g. a custom extension property on the event);
either is a reasonable next step but is out of scope for this MVP.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.models.schemas import AppointmentResult

DEFAULT_TTL_SECONDS = 24 * 60 * 60


@dataclass
class _Entry:
    result: AppointmentResult
    expires_at: float


class IdempotencyStore:
    """Thread-safe, process-local key -> AppointmentResult cache."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    def get(self, key: str | None) -> AppointmentResult | None:
        if not key:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                del self._entries[key]
                return None
            return entry.result

    def put(self, key: str | None, result: AppointmentResult) -> None:
        if not key:
            return
        with self._lock:
            self._purge_expired()
            self._entries[key] = _Entry(result=result, expires_at=time.monotonic() + self._ttl_seconds)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]
