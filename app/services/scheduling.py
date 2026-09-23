"""SchedulingOrchestrator (section 6.1).

Coordinates the booking use case end to end: interpret -> find options ->
confirm -> create. It owns no provider-specific logic itself -- that lives
in the gateways and business-rules service -- and it never marks a booking
confirmed until Microsoft Graph (via OutlookGateway) reports success
(section 2.2, "no appointment is considered confirmed until Microsoft
Graph returns a successful event creation result").
"""
from __future__ import annotations

import logging
import zlib
from datetime import datetime

from app.errors.handlers import SlotConflictError, ValidationError
from app.gateways.outlook import OutlookEvent, OutlookGateway
from app.models.schemas import (
    AppointmentResult,
    BookingCommand,
    SchedulingIntent,
    SlotOption,
)
from app.services.availability import AvailabilityService
from app.services.business_rules import BusinessRulesService
from app.services.intent import IntentService

logger = logging.getLogger(__name__)


def _derive_local_id(outlook_event_id: str) -> int:
    """Derive a stable, display-only integer id from the Outlook event id.

    Per ADR-006 there is no local database, so no auto-incrementing id can
    be persisted. The Outlook event id remains the actual persistent,
    authoritative identifier -- this integer is only a display convenience
    and is deterministic so that fetching the same appointment twice (e.g.
    ``confirm_booking`` then ``get_appointment``) returns the same id.
    """
    return zlib.crc32(outlook_event_id.encode("utf-8"))


class SchedulingOrchestrator:
    def __init__(
        self,
        intent_service: IntentService,
        business_rules: BusinessRulesService,
        availability_service: AvailabilityService,
        outlook_gateway: OutlookGateway,
    ) -> None:
        self._intent_service = intent_service
        self._business_rules = business_rules
        self._availability_service = availability_service
        self._outlook_gateway = outlook_gateway

    def interpret_request(self, text: str, actor: str, timezone: str) -> SchedulingIntent:
        return self._intent_service.interpret(text=text, actor=actor, timezone=timezone)

    def find_options(
        self,
        appointment_type_code: str,
        date_start,
        date_end,
        time_start,
        time_end,
        max_options: int = 3,
    ) -> list[SlotOption]:
        appointment_type = self._business_rules.get_active_appointment_type(appointment_type_code)
        windows = self._business_rules.build_candidate_windows(date_start, date_end, time_start, time_end)
        return self._availability_service.find_options(appointment_type, windows, max_options=max_options)

    def confirm_booking(self, command: BookingCommand) -> AppointmentResult:
        appointment_type = self._business_rules.get_active_appointment_type_by_id(command.appointment_type_id)
        start = datetime.fromisoformat(command.start_iso)
        end = start + self._business_rules.appointment_duration(appointment_type)

        # Recheck immediately before write (section 2.2, section 6.6). A
        # concurrent booking that wins the race between this recheck and the
        # create_event call below still surfaces as SlotConflictError,
        # propagated unchanged from the gateway.
        busy = self._outlook_gateway.get_schedule(start, end)
        if any(b.start < end and b.end > start for b in busy):
            raise SlotConflictError()

        event: OutlookEvent = self._outlook_gateway.create_event(
            subject=f"{appointment_type.display_name} - {command.customer_name}",
            start=start,
            end=end,
            body=self._build_event_body(command),
            categories=["tuxedo_appointment", appointment_type.code],
        )

        logger.info(
            "Appointment created",
            extra={"outlook_event_id": event.event_id, "appointment_type": appointment_type.code},
        )

        return AppointmentResult(
            id=_derive_local_id(event.event_id),
            status="confirmed",
            start=event.start.isoformat(),
            end=event.end.isoformat(),
            outlook_event_id=event.event_id,
        )

    def get_appointment(self, event_id: str) -> AppointmentResult | None:
        event = self._outlook_gateway.get_event(event_id)
        if event is None:
            return None
        return AppointmentResult(
            id=_derive_local_id(event.event_id),
            status="confirmed",
            start=event.start.isoformat(),
            end=event.end.isoformat(),
            outlook_event_id=event.event_id,
        )

    def list_owner_schedule(self, date_from: datetime, date_to: datetime) -> list[OutlookEvent]:
        return self._outlook_gateway.list_events(date_from, date_to, categories=["tuxedo_appointment"])

    def create_owner_block(self, start: datetime, end: datetime, reason: str | None) -> OutlookEvent:
        if end <= start:
            raise ValidationError("Block end time must be after start time.")
        return self._outlook_gateway.create_block(start=start, end=end, reason=reason)

    @staticmethod
    def _build_event_body(command: BookingCommand) -> str:
        parts = [f"Customer: {command.customer_name}", f"Email: {command.customer_email}"]
        if command.customer_phone:
            parts.append(f"Phone: {command.customer_phone}")
        if command.notes:
            parts.append(f"Notes: {command.notes}")
        return "\n".join(parts)
