"""Business-hours and blackout-rule configuration store.

Also version-controlled application configuration per the Week 4 design
(section 4.2), separate from Outlook's role as the availability/authority
source. These rules are applied *before* the Outlook free/busy query so
the application never asks Outlook about times the business is closed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time


@dataclass(frozen=True)
class BusinessHours:
    # Monday=0 ... Sunday=6, matching datetime.weekday()
    open_days: frozenset[int] = field(default_factory=lambda: frozenset({0, 1, 2, 3, 4, 5}))
    opening_time: time = time(9, 0)
    closing_time: time = time(18, 0)
    timezone: str = "America/Chicago"
    blackout_dates: frozenset[date] = field(default_factory=frozenset)

    def is_open_on(self, day: date) -> bool:
        if day in self.blackout_dates:
            return False
        return day.weekday() in self.open_days

    def clamp_window(self, requested_start: time, requested_end: time) -> tuple[time, time]:
        """Intersect a requested time window with business hours."""
        start = max(requested_start, self.opening_time)
        end = min(requested_end, self.closing_time)
        return start, end


business_hours_store = BusinessHours()
