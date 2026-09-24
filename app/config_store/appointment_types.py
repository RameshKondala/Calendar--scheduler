"""Appointment-type configuration store.

Per ADR-006, the application does not maintain a separate appointment
database. Appointment types, durations, and buffers are version-controlled
application configuration rather than database rows. This module is the
single place that owns that configuration and exposes a small read/update
API so services never need to know how it is stored.

Swapping this in-memory store for a file- or DB-backed one later only
requires changing this module.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class AppointmentType:
    id: int
    code: str
    display_name: str
    duration_minutes: int
    buffer_minutes: int
    active: bool = True


class AppointmentTypeStore:
    """Thread-safe in-memory configuration store for appointment types."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._types: dict[int, AppointmentType] = {
            t.id: t for t in self._seed_data()
        }

    @staticmethod
    def _seed_data() -> list[AppointmentType]:
        return [
            AppointmentType(1, "initial_fitting", "Initial Fitting", 45, 15),
            AppointmentType(2, "final_fitting", "Final Fitting", 30, 15),
            AppointmentType(3, "pickup", "Pickup", 15, 10),
            AppointmentType(4, "return", "Return", 15, 10),
        ]

    def list_active(self) -> list[AppointmentType]:
        with self._lock:
            return [t for t in self._types.values() if t.active]

    def get_by_id(self, type_id: int) -> AppointmentType | None:
        with self._lock:
            return self._types.get(type_id)

    def get_by_code(self, code: str) -> AppointmentType | None:
        with self._lock:
            for t in self._types.values():
                if t.code == code:
                    return t
            return None

    def update(
        self,
        type_id: int,
        *,
        duration_minutes: int | None = None,
        buffer_minutes: int | None = None,
        active: bool | None = None,
    ) -> AppointmentType | None:
        with self._lock:
            existing = self._types.get(type_id)
            if existing is None:
                return None
            updated = replace(
                existing,
                duration_minutes=duration_minutes if duration_minutes is not None else existing.duration_minutes,
                buffer_minutes=buffer_minutes if buffer_minutes is not None else existing.buffer_minutes,
                active=active if active is not None else existing.active,
            )
            self._types[type_id] = updated
            return updated


# Module-level singleton used by the app factory / DI container.
appointment_type_store = AppointmentTypeStore()
