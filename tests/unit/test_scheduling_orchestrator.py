from zoneinfo import ZoneInfo
from datetime import datetime

import pytest

from app.config_store.appointment_types import AppointmentTypeStore
from app.config_store.business_hours import BusinessHours
from app.errors.handlers import SlotConflictError, ValidationError
from app.gateways.outlook import FakeOutlookGateway
from app.models.schemas import BookingCommand
from app.services.availability import AvailabilityService
from app.services.business_rules import BusinessRulesService
from app.services.intent import FakeIntentInterpreter, IntentService
from app.services.scheduling import SchedulingOrchestrator

CHICAGO = ZoneInfo("America/Chicago")


@pytest.fixture
def orchestrator():
    type_store = AppointmentTypeStore()
    business_rules = BusinessRulesService(type_store, BusinessHours())
    gateway = FakeOutlookGateway()
    availability = AvailabilityService(gateway, business_rules)
    intent_service = IntentService(FakeIntentInterpreter(type_store))
    return SchedulingOrchestrator(intent_service, business_rules, availability, gateway), gateway


def _command(start_iso: str, idempotency_key: str | None = None) -> BookingCommand:
    return BookingCommand(
        customer_name="Jane Doe",
        customer_email="jane@example.com",
        customer_phone=None,
        appointment_type_id=1,
        start_iso=start_iso,
        notes=None,
        idempotency_key=idempotency_key,
    )


def test_confirm_booking_creates_outlook_event(orchestrator):
    scheduler, gateway = orchestrator
    result = scheduler.confirm_booking(_command("2026-09-21T09:00:00"))

    assert result.status == "confirmed"
    assert result.outlook_event_id.startswith("fake_")
    assert gateway.get_event(result.outlook_event_id) is not None


def test_confirm_booking_conflict_raises_slot_conflict(orchestrator):
    scheduler, gateway = orchestrator
    gateway.seed_busy(datetime(2026, 9, 21, 9, 0, tzinfo=CHICAGO), datetime(2026, 9, 21, 9, 45, tzinfo=CHICAGO))

    with pytest.raises(SlotConflictError):
        scheduler.confirm_booking(_command("2026-09-21T09:00:00"))


def test_confirm_booking_unknown_appointment_type_raises_validation_error(orchestrator):
    scheduler, _gateway = orchestrator
    command = _command("2026-09-21T09:00:00")
    command.appointment_type_id = 9999

    with pytest.raises(ValidationError):
        scheduler.confirm_booking(command)


def test_get_appointment_id_matches_confirm_booking_id(orchestrator):
    """Regression test: the display-only local id must be stable across
    confirm_booking and a later get_appointment lookup for the same Outlook
    event, since there is no local database to persist an auto-incrementing
    id against (ADR-006)."""
    scheduler, _gateway = orchestrator
    created = scheduler.confirm_booking(_command("2026-09-21T09:00:00"))

    fetched = scheduler.get_appointment(created.outlook_event_id)

    assert fetched is not None
    assert fetched.id == created.id


def test_get_appointment_returns_none_when_missing(orchestrator):
    scheduler, _gateway = orchestrator
    assert scheduler.get_appointment("does-not-exist") is None


def test_create_owner_block_rejects_invalid_range(orchestrator):
    scheduler, _gateway = orchestrator
    start = datetime(2026, 9, 21, 10, 0, tzinfo=CHICAGO)
    end = datetime(2026, 9, 21, 9, 0, tzinfo=CHICAGO)
    with pytest.raises(ValidationError):
        scheduler.create_owner_block(start, end, "test block")


def test_confirm_booking_with_repeated_idempotency_key_does_not_write_twice(orchestrator):
    scheduler, gateway = orchestrator
    first = scheduler.confirm_booking(_command("2026-09-21T09:00:00", idempotency_key="retry-key-1"))
    second = scheduler.confirm_booking(_command("2026-09-21T09:00:00", idempotency_key="retry-key-1"))

    assert second.outlook_event_id == first.outlook_event_id
    assert len(gateway.list_events(
        datetime(2026, 9, 21, 0, 0, tzinfo=CHICAGO),
        datetime(2026, 9, 22, 0, 0, tzinfo=CHICAGO),
    )) == 1


def test_confirm_booking_without_idempotency_key_books_independently(orchestrator):
    scheduler, _gateway = orchestrator
    first = scheduler.confirm_booking(_command("2026-09-21T09:00:00"))
    # A different slot, no key on either call -- these are two real, distinct bookings.
    second = scheduler.confirm_booking(_command("2026-09-21T11:00:00"))
    assert first.outlook_event_id != second.outlook_event_id


def test_different_idempotency_keys_both_book(orchestrator):
    scheduler, _gateway = orchestrator
    first = scheduler.confirm_booking(_command("2026-09-21T09:00:00", idempotency_key="key-a"))
    second = scheduler.confirm_booking(_command("2026-09-21T11:00:00", idempotency_key="key-b"))
    assert first.outlook_event_id != second.outlook_event_id
