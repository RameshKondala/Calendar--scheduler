"""Outlook / Microsoft Graph integration boundary.

This is the interface Jose's real Microsoft Graph implementation must
satisfy (ADR-002, section 6.3). Nothing outside this module should ever
import the Microsoft Graph SDK or handle raw Graph exceptions -- gateway
implementations translate provider errors into the application's
``AppError`` hierarchy so the rest of the system stays provider-agnostic
and easily testable (section 6.4, Adapter pattern; section 7.6,
Testability).

``FakeOutlookGateway`` is a deterministic in-memory stand-in used by unit
and integration tests, and for local development before Jose's real
gateway is wired in.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from app.errors.handlers import OutlookUnavailableError, SlotConflictError


@dataclass
class FreeBusyWindow:
    start: datetime
    end: datetime
    is_free: bool


@dataclass
class OutlookEvent:
    event_id: str
    subject: str
    start: datetime
    end: datetime
    categories: list[str] = field(default_factory=list)
    body: str | None = None


class OutlookGateway(ABC):
    """Interface for all Outlook Calendar / Microsoft Graph operations.

    Every method should raise ``OutlookUnavailableError`` on timeout/outage
    and ``SlotConflictError`` when a create_event call loses a race against
    a slot that just became busy. No other exception types should escape
    this boundary.
    """

    @abstractmethod
    def get_schedule(self, window_start: datetime, window_end: datetime) -> list[FreeBusyWindow]:
        """Return free/busy windows for the given bounded range."""

    @abstractmethod
    def create_event(
        self,
        *,
        subject: str,
        start: datetime,
        end: datetime,
        body: str | None,
        categories: list[str] | None = None,
    ) -> OutlookEvent:
        """Create a confirmed calendar event. Must raise SlotConflictError
        if the slot is no longer free at write time."""

    @abstractmethod
    def list_events(
        self,
        window_start: datetime,
        window_end: datetime,
        categories: list[str] | None = None,
    ) -> list[OutlookEvent]:
        """List events in a range, optionally filtered by category (owner view)."""

    @abstractmethod
    def get_event(self, event_id: str) -> OutlookEvent | None:
        """Retrieve a single event by its persistent Outlook event id."""

    @abstractmethod
    def create_block(self, *, start: datetime, end: datetime, reason: str | None) -> OutlookEvent:
        """Create an owner-only busy block."""


class FakeOutlookGateway(OutlookGateway):
    """In-memory fake used for tests and local development.

    Simulates Outlook as the source of truth: events created here are
    immediately reflected in subsequent free/busy and list queries.
    """

    def __init__(self, *, force_unavailable: bool = False) -> None:
        self._events: dict[str, OutlookEvent] = {}
        self.force_unavailable = force_unavailable

    def _check_available(self) -> None:
        if self.force_unavailable:
            raise OutlookUnavailableError()

    def get_schedule(self, window_start: datetime, window_end: datetime) -> list[FreeBusyWindow]:
        self._check_available()
        busy_windows = [
            FreeBusyWindow(e.start, e.end, is_free=False)
            for e in self._events.values()
            if e.start < window_end and e.end > window_start
        ]
        return busy_windows

    def _is_slot_free(self, start: datetime, end: datetime) -> bool:
        for e in self._events.values():
            if e.start < end and e.end > start:
                return False
        return True

    def create_event(
        self,
        *,
        subject: str,
        start: datetime,
        end: datetime,
        body: str | None,
        categories: list[str] | None = None,
    ) -> OutlookEvent:
        self._check_available()
        if not self._is_slot_free(start, end):
            raise SlotConflictError()
        event_id = f"fake_{uuid.uuid4().hex[:16]}"
        event = OutlookEvent(
            event_id=event_id,
            subject=subject,
            start=start,
            end=end,
            categories=categories or [],
            body=body,
        )
        self._events[event_id] = event
        return event

    def list_events(
        self,
        window_start: datetime,
        window_end: datetime,
        categories: list[str] | None = None,
    ) -> list[OutlookEvent]:
        self._check_available()
        results = [
            e
            for e in self._events.values()
            if e.start < window_end and e.end > window_start
        ]
        if categories:
            results = [e for e in results if set(categories) & set(e.categories)]
        return sorted(results, key=lambda e: e.start)

    def get_event(self, event_id: str) -> OutlookEvent | None:
        self._check_available()
        return self._events.get(event_id)

    def create_block(self, *, start: datetime, end: datetime, reason: str | None) -> OutlookEvent:
        return self.create_event(
            subject=reason or "Blocked",
            start=start,
            end=end,
            body=reason,
            categories=["owner_block"],
        )

    # Test helper, not part of the interface.
    def seed_busy(self, start: datetime, end: datetime, subject: str = "Existing appointment") -> None:
        event_id = f"fake_{uuid.uuid4().hex[:16]}"
        self._events[event_id] = OutlookEvent(event_id=event_id, subject=subject, start=start, end=end)
