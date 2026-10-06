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
from dataclasses import replace
from datetime import datetime

from app.errors.handlers import SlotConflictError, ValidationError
from app.gateways.outlook import OutlookEvent, OutlookGateway
from app.models.schemas import (
    AppointmentResult,
    BookingCommand,
    SchedulingIntent,
    SlotOption,
)
from app.services.idempotency import IdempotencyStore
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
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self._intent_service = intent_service
        self._business_rules = business_rules
        self._availability_service = availability_service
        self._outlook_gateway = outlook_gateway
        self._idempotency_store = idempotency_store or IdempotencyStore()

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
        cached = self._idempotency_store.get(command.idempotency_key)
        if cached is not None:
            # Same key seen before: replay the prior result instead of
            # writing to Outlook again (section 3.1, Idempotency-Key).
            return cached

        appointment_type = self._business_rules.get_active_appointment_type_by_id(command.appointment_type_id)
        start = self._business_rules.to_business_time(datetime.fromisoformat(command.start_iso))
        end = start + self._business_rules.appointment_duration(appointment_type)

        # Only /availability applied business hours until now; a direct
        # POST /appointments call must be held to the same rule (Week 4 3.6).
        self._business_rules.ensure_within_business_hours(appointment_type, start)

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

        result = self._to_result(event)
        self._idempotency_store.put(command.idempotency_key, result)
        return result

    def get_appointment(self, event_id: str) -> AppointmentResult | None:
        event = self._outlook_gateway.get_event(event_id)
        if event is None:
            return None
        return self._to_result(event)

    def list_owner_schedule(self, date_from: datetime, date_to: datetime) -> list[OutlookEvent]:
        events = self._outlook_gateway.list_events(
            self._business_rules.to_business_time(date_from),
            self._business_rules.to_business_time(date_to),
            categories=["tuxedo_appointment"],
        )
        return [self._in_business_time(event) for event in events]

    def create_owner_block(self, start: datetime, end: datetime, reason: str | None) -> OutlookEvent:
        start = self._business_rules.to_business_time(start)
        end = self._business_rules.to_business_time(end)
        if end <= start:
            raise ValidationError("Block end time must be after start time.")
        block = self._outlook_gateway.create_block(start=start, end=end, reason=reason)
        return self._in_business_time(block)

    def _in_business_time(self, event: OutlookEvent) -> OutlookEvent:
        """Re-express an event's times in the business timezone.

        Gateways may return instants in any timezone (the Graph gateway
        normalizes to UTC); API responses always carry business-local
        times, per the "local time plus configured business time zone"
        convention in Week 4 section 3.1.
        """
        return replace(
            event,
            start=self._business_rules.to_business_time(event.start),
            end=self._business_rules.to_business_time(event.end),
        )

    def _to_result(self, event: OutlookEvent) -> AppointmentResult:
        local_event = self._in_business_time(event)
        return AppointmentResult(
            id=_derive_local_id(local_event.event_id),
            status="confirmed",
            start=local_event.start.isoformat(),
            end=local_event.end.isoformat(),
            outlook_event_id=local_event.event_id,
        )

    @staticmethod
    def _build_event_body(command: BookingCommand) -> str:
        parts = [f"Customer: {command.customer_name}", f"Email: {command.customer_email}"]
        if command.customer_phone:
            parts.append(f"Phone: {command.customer_phone}")
        if command.notes:
            parts.append(f"Notes: {command.notes}")
        return "\n".join(parts)
