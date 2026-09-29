from zoneinfo import ZoneInfo
from datetime import datetime

import pytest

from app.errors.handlers import OutlookUnavailableError, SlotConflictError
from app.gateways.outlook import FakeOutlookGateway

CHICAGO = ZoneInfo("America/Chicago")


def test_create_event_then_get_schedule_reflects_busy_time():
    gateway = FakeOutlookGateway()
    start = datetime(2026, 9, 21, 9, 0, tzinfo=CHICAGO)
    end = datetime(2026, 9, 21, 9, 45, tzinfo=CHICAGO)

    gateway.create_event(subject="Fitting", start=start, end=end, body=None)
    busy = gateway.get_schedule(start, end)

    assert len(busy) == 1
    assert busy[0].is_free is False


def test_create_event_conflict_raises_slot_conflict():
    gateway = FakeOutlookGateway()
    start = datetime(2026, 9, 21, 9, 0, tzinfo=CHICAGO)
    end = datetime(2026, 9, 21, 9, 45, tzinfo=CHICAGO)
    gateway.create_event(subject="First", start=start, end=end, body=None)

    with pytest.raises(SlotConflictError):
        gateway.create_event(subject="Second", start=start, end=end, body=None)


def test_forced_unavailable_maps_to_outlook_unavailable_error():
    gateway = FakeOutlookGateway(force_unavailable=True)
    with pytest.raises(OutlookUnavailableError):
        gateway.get_schedule(datetime(2026, 9, 21, 9, 0, tzinfo=CHICAGO), datetime(2026, 9, 21, 10, 0, tzinfo=CHICAGO))


def test_create_block_is_tagged_with_owner_block_category():
    gateway = FakeOutlookGateway()
    event = gateway.create_block(
        start=datetime(2026, 9, 21, 9, 0, tzinfo=CHICAGO), end=datetime(2026, 9, 21, 10, 0, tzinfo=CHICAGO), reason="Staff meeting"
    )
    assert "owner_block" in event.categories


NAIVE_START = datetime(2026, 9, 21, 9, 0)
NAIVE_END = datetime(2026, 9, 21, 10, 0)


@pytest.mark.parametrize(
    "call",
    [
        lambda gateway: gateway.get_schedule(NAIVE_START, NAIVE_END),
        lambda gateway: gateway.create_event(subject="Fitting", start=NAIVE_START, end=NAIVE_END, body=None),
        lambda gateway: gateway.list_events(NAIVE_START, NAIVE_END),
        lambda gateway: gateway.create_block(start=NAIVE_START, end=NAIVE_END, reason=None),
    ],
    ids=["get_schedule", "create_event", "list_events", "create_block"],
)
def test_fake_gateway_rejects_naive_datetimes_like_the_real_gateway(call):
    """The fake must enforce the same timezone-aware contract as the Graph
    gateway; otherwise services can pass naive values in tests and only fail
    against the real calendar."""
    with pytest.raises(ValueError):
        call(FakeOutlookGateway())
