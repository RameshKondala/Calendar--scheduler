from datetime import datetime

import pytest

from app.errors.handlers import OutlookUnavailableError, SlotConflictError
from app.gateways.outlook import FakeOutlookGateway


def test_create_event_then_get_schedule_reflects_busy_time():
    gateway = FakeOutlookGateway()
    start = datetime(2026, 9, 21, 9, 0)
    end = datetime(2026, 9, 21, 9, 45)

    gateway.create_event(subject="Fitting", start=start, end=end, body=None)
    busy = gateway.get_schedule(start, end)

    assert len(busy) == 1
    assert busy[0].is_free is False


def test_create_event_conflict_raises_slot_conflict():
    gateway = FakeOutlookGateway()
    start = datetime(2026, 9, 21, 9, 0)
    end = datetime(2026, 9, 21, 9, 45)
    gateway.create_event(subject="First", start=start, end=end, body=None)

    with pytest.raises(SlotConflictError):
        gateway.create_event(subject="Second", start=start, end=end, body=None)


def test_forced_unavailable_maps_to_outlook_unavailable_error():
    gateway = FakeOutlookGateway(force_unavailable=True)
    with pytest.raises(OutlookUnavailableError):
        gateway.get_schedule(datetime(2026, 9, 21, 9, 0), datetime(2026, 9, 21, 10, 0))


def test_create_block_is_tagged_with_owner_block_category():
    gateway = FakeOutlookGateway()
    event = gateway.create_block(
        start=datetime(2026, 9, 21, 9, 0), end=datetime(2026, 9, 21, 10, 0), reason="Staff meeting"
    )
    assert "owner_block" in event.categories
