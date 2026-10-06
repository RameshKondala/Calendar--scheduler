"""Business policy: appointment types, buffers, and business hours.

Applied before any Outlook query so the application never asks Outlook
about closed days/hours, and never returns a candidate window that
violates business policy even if Outlook happens to be free then
(section 4.5, section 7.1).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from app.config_store.appointment_types import AppointmentType, AppointmentTypeStore
from app.config_store.business_hours import BusinessHours
from app.errors.handlers import ValidationError


@dataclass
class CandidateWindow:
    date: date
    window_start: time
    window_end: time


class BusinessRulesService:
    def __init__(self, appointment_type_store: AppointmentTypeStore, business_hours: BusinessHours) -> None:
        self._appointment_type_store = appointment_type_store
        self._business_hours = business_hours

    @property
    def zone(self) -> tzinfo:
        """The configured business timezone."""
        return self._business_hours.zone

    def to_business_time(self, moment: datetime) -> datetime:
        """Express ``moment`` in the business timezone.

        A naive datetime is interpreted as business-local wall-clock time
        (what a customer or owner types into the UI). An aware datetime is
        converted to the same instant in the business timezone. Every
        datetime handed to the Outlook gateway must go through here, since
        gateways require timezone-aware values (see ``OutlookGateway``).
        """
        if moment.tzinfo is None or moment.utcoffset() is None:
            return moment.replace(tzinfo=self.zone)
        return moment.astimezone(self.zone)

    def get_active_appointment_type(self, code: str) -> AppointmentType:
        appointment_type = self._appointment_type_store.get_by_code(code)
        if appointment_type is None or not appointment_type.active:
            raise ValidationError(f"'{code}' is not a known active appointment type.")
        return appointment_type

    def get_active_appointment_type_by_id(self, type_id: int) -> AppointmentType:
        appointment_type = self._appointment_type_store.get_by_id(type_id)
        if appointment_type is None or not appointment_type.active:
            raise ValidationError(f"Appointment type id {type_id} is not a known active appointment type.")
        return appointment_type

    def build_candidate_windows(
        self,
        date_start: date,
        date_end: date,
        time_start: time | None,
        time_end: time | None,
    ) -> list[CandidateWindow]:
        """Intersect the requested date/time range with open business days/hours."""
        if date_end < date_start:
            raise ValidationError("date_end cannot be before date_start.")
        if (date_end - date_start).days > 30:
            raise ValidationError("Availability searches are limited to a 30 day range.")

        requested_start = time_start or self._business_hours.opening_time
        requested_end = time_end or self._business_hours.closing_time

        windows: list[CandidateWindow] = []
        current = date_start
        while current <= date_end:
            if self._business_hours.is_open_on(current):
                clamped_start, clamped_end = self._business_hours.clamp_window(requested_start, requested_end)
                if clamped_start < clamped_end:
                    windows.append(CandidateWindow(current, clamped_start, clamped_end))
            current += timedelta(days=1)
        return windows

    def slot_duration(self, appointment_type: AppointmentType) -> timedelta:
        return timedelta(minutes=appointment_type.duration_minutes + appointment_type.buffer_minutes)

    def appointment_duration(self, appointment_type: AppointmentType) -> timedelta:
        """The customer-facing duration, excluding the internal buffer."""
        return timedelta(minutes=appointment_type.duration_minutes)

    def ensure_within_business_hours(self, appointment_type: AppointmentType, start: datetime) -> None:
        """Reject a booking start time that ``/availability`` would never have
        offered: a closed day, or a time outside business hours once the
        appointment's own duration is accounted for.

        ``start`` must already be timezone-aware (see ``to_business_time``).
        Week 4 section 3.6 requires ``start`` to match a valid candidate;
        only ``/availability`` enforced that until now, so a direct
        ``POST /appointments`` call could book outside business hours.
        """
        local_start = start.astimezone(self.zone)
        appointment_date = local_start.date()

        if not self._business_hours.is_open_on(appointment_date):
            raise ValidationError("The business is closed on that date.")

        end_moment = local_start + self.appointment_duration(appointment_type)
        if end_moment.date() != appointment_date:
            raise ValidationError("That time is outside business hours for this appointment's duration.")
        if local_start.time() < self._business_hours.opening_time or end_moment.time() > self._business_hours.closing_time:
            raise ValidationError("That time is outside business hours for this appointment's duration.")
