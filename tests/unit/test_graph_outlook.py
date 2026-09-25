
"""Unit tests for the Microsoft Graph Outlook gateway."""

from datetime import datetime, timezone

import pytest
import requests

from app.errors.handlers import OutlookUnavailableError, SlotConflictError
from app.gateways.graph_outlook import GraphOutlookGateway
from app.gateways.outlook import FreeBusyWindow, OutlookEvent


def _gateway():
    return GraphOutlookGateway(
        calendar_id="test-calendar",
        access_token_provider=lambda: "test-access-token",
        timeout_seconds=8,
    )


def _window():
    return (
        datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 25, 17, 0, tzinfo=timezone.utc),
    )


def _graph_event(
    event_id="event-123",
    subject="Tuxedo fitting",
    categories=None,
):
    return {
        "id": event_id,
        "subject": subject,
        "start": {
            "dateTime": "2026-09-25T10:00:00+00:00",
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": "2026-09-25T11:00:00+00:00",
            "timeZone": "UTC",
        },
        "categories": categories if categories is not None else ["appointment"],
        "body": {
            "contentType": "text",
            "content": "Customer appointment",
        },
    }


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_request_sends_authenticated_request(monkeypatch):
    gateway = _gateway()
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return FakeResponse({})

    monkeypatch.setattr(requests, "request", fake_request)

    response = gateway._request(
        "GET",
        "/me/events",
        params={"$top": 10},
    )

    assert isinstance(response, FakeResponse)
    assert captured["method"] == "GET"
    assert captured["url"] == "https://graph.microsoft.com/v1.0/me/events"
    assert captured["headers"]["Authorization"] == "Bearer test-access-token"
    assert captured["headers"]["Prefer"] == 'outlook.timezone="UTC"'
    assert captured["params"] == {"$top": 10}
    assert captured["timeout"] == 8


def test_request_handles_timeout(monkeypatch):
    gateway = _gateway()

    def fake_request(**kwargs):
        raise requests.Timeout("Graph request timed out")

    monkeypatch.setattr(requests, "request", fake_request)

    with pytest.raises(OutlookUnavailableError):
        gateway._request("GET", "/me/events")


def test_request_handles_http_error(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        requests,
        "request",
        lambda **kwargs: FakeResponse({}, status_code=503),
    )

    with pytest.raises(OutlookUnavailableError):
        gateway._request("GET", "/me/events")


def test_request_handles_token_provider_error():
    def failing_token_provider():
        raise ValueError("No access token available")

    gateway = GraphOutlookGateway(
        calendar_id="test-calendar",
        access_token_provider=failing_token_provider,
        timeout_seconds=8,
    )

    with pytest.raises(OutlookUnavailableError):
        gateway._request("GET", "/me/events")


def test_get_schedule_returns_busy_windows(monkeypatch):
    gateway = _gateway()
    captured = {}

    def fake_request(method, path, *, params=None, json=None):
        captured.update(method=method, path=path, params=params)

        return FakeResponse({
            "value": [{
                "showAs": "busy",
                "start": {"dateTime": "2026-09-25T10:00:00+00:00"},
                "end": {"dateTime": "2026-09-25T11:00:00+00:00"},
            }]
        })

    monkeypatch.setattr(gateway, "_request", fake_request)

    start, end = _window()
    windows = gateway.get_schedule(start, end)

    assert len(windows) == 1
    assert windows[0].is_free is False
    assert windows[0].start.hour == 10
    assert windows[0].end.hour == 11
    assert captured["method"] == "GET"
    assert captured["path"] == "/me/calendars/test-calendar/calendarView"
    assert captured["params"]["startDateTime"] == start.isoformat()


def test_get_schedule_ignores_free_events(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse({
            "value": [
                {
                    "showAs": "free",
                    "start": {"dateTime": "2026-09-25T10:00:00+00:00"},
                    "end": {"dateTime": "2026-09-25T11:00:00+00:00"},
                },
                {
                    "showAs": "busy",
                    "start": {"dateTime": "2026-09-25T13:00:00+00:00"},
                    "end": {"dateTime": "2026-09-25T14:00:00+00:00"},
                },
            ]
        }),
    )

    start, end = _window()
    windows = gateway.get_schedule(start, end)

    assert len(windows) == 1
    assert windows[0].start.hour == 13


def test_create_event_success(monkeypatch):
    gateway = _gateway()
    start, end = _window()

    monkeypatch.setattr(gateway, "get_schedule", lambda *args: [])

    calls = []

    def fake_request(method, path, *, params=None, json=None):
        calls.append((method, path, json))
        return FakeResponse({"id": "outlook-event-123"})

    monkeypatch.setattr(gateway, "_request", fake_request)

    event = gateway.create_event(
        subject="Tuxedo fitting",
        start=start,
        end=end,
        body="Customer appointment",
        categories=["appointment"],
    )

    assert event.event_id == "outlook-event-123"
    assert event.subject == "Tuxedo fitting"
    assert event.start == start
    assert event.end == end
    assert event.categories == ["appointment"]

    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert calls[0][1] == "/me/calendars/test-calendar/events"
    assert calls[0][2]["showAs"] == "busy"
    assert calls[0][2]["start"]["timeZone"] == "UTC"


def test_create_event_rejects_occupied_slot(monkeypatch):
    gateway = _gateway()
    start, end = _window()

    monkeypatch.setattr(
        gateway,
        "get_schedule",
        lambda *args: [
            FreeBusyWindow(start=start, end=end, is_free=False)
        ],
    )

    def unexpected_request(*args, **kwargs):
        pytest.fail("Occupied slot must not trigger event creation")

    monkeypatch.setattr(gateway, "_request", unexpected_request)

    with pytest.raises(SlotConflictError):
        gateway.create_event(
            subject="Tuxedo fitting",
            start=start,
            end=end,
            body=None,
        )


def test_create_event_rejects_missing_event_id(monkeypatch):
    gateway = _gateway()
    start, end = _window()

    monkeypatch.setattr(gateway, "get_schedule", lambda *args: [])
    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse({}),
    )

    with pytest.raises(OutlookUnavailableError):
        gateway.create_event(
            subject="Tuxedo fitting",
            start=start,
            end=end,
            body=None,
        )


def test_list_events_returns_appointments(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse({
            "value": [_graph_event()]
        }),
    )

    start, end = _window()
    events = gateway.list_events(start, end)

    assert len(events) == 1
    assert events[0].event_id == "event-123"
    assert events[0].subject == "Tuxedo fitting"
    assert events[0].categories == ["appointment"]
    assert events[0].body == "Customer appointment"
    assert events[0].start.hour == 10


def test_list_events_filters_categories(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse({
            "value": [
                _graph_event(
                    event_id="appointment-1",
                    categories=["appointment"],
                ),
                _graph_event(
                    event_id="block-1",
                    subject="Owner unavailable",
                    categories=["owner_block"],
                ),
            ]
        }),
    )

    start, end = _window()
    events = gateway.list_events(
        start,
        end,
        categories=["owner_block"],
    )

    assert len(events) == 1
    assert events[0].event_id == "block-1"


def test_list_events_rejects_malformed_response(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse({
            "unexpected": "response"
        }),
    )

    start, end = _window()

    with pytest.raises(OutlookUnavailableError):
        gateway.list_events(start, end)


def test_list_events_rejects_incomplete_pages(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse({
            "value": [_graph_event()],
            "@odata.nextLink": "https://graph.microsoft.com/next-page",
        }),
    )

    start, end = _window()

    with pytest.raises(OutlookUnavailableError):
        gateway.list_events(start, end)


def test_get_event_returns_appointment(monkeypatch):
    gateway = _gateway()
    captured = {}

    def fake_request(method, path, *, params=None, json=None,
                     allow_not_found=False):
        captured["method"] = method
        captured["path"] = path
        captured["allow_not_found"] = allow_not_found
        return FakeResponse(_graph_event())

    monkeypatch.setattr(gateway, "_request", fake_request)

    event = gateway.get_event("event-123")

    assert event.event_id == "event-123"
    assert event.subject == "Tuxedo fitting"
    assert captured["method"] == "GET"
    assert captured["path"] == (
        "/me/calendars/test-calendar/events/event-123"
    )
    assert captured["allow_not_found"] is True


def test_get_event_returns_none_for_404(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse(
            {},
            status_code=404,
        ),
    )

    assert gateway.get_event("missing-event") is None


def test_get_event_rejects_malformed_response(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse({"id": "event-123"}),
    )

    with pytest.raises(OutlookUnavailableError):
        gateway.get_event("event-123")


def test_get_event_encodes_event_id(monkeypatch):
    gateway = _gateway()
    captured = {}

    def fake_request(method, path, **kwargs):
        captured["path"] = path
        return FakeResponse(_graph_event())

    monkeypatch.setattr(gateway, "_request", fake_request)

    gateway.get_event("event/with spaces")

    assert captured["path"].endswith(
        "/events/event%2Fwith%20spaces"
    )


def test_create_block_uses_owner_category(monkeypatch):
    gateway = _gateway()
    start, end = _window()
    captured = {}

    def fake_create_event(**kwargs):
        captured.update(kwargs)

        return OutlookEvent(
            event_id="block-123",
            subject=kwargs["subject"],
            start=kwargs["start"],
            end=kwargs["end"],
            categories=kwargs["categories"],
            body=kwargs["body"],
        )

    monkeypatch.setattr(gateway, "create_event", fake_create_event)

    block = gateway.create_block(
        start=start,
        end=end,
        reason="Owner vacation",
    )

    assert block.event_id == "block-123"
    assert block.subject == "Owner unavailable"
    assert block.categories == ["owner_block"]
    assert block.body == "Owner vacation"
    assert captured["start"] == start
    assert captured["end"] == end


def test_create_block_rejects_occupied_slot(monkeypatch):
    gateway = _gateway()
    start, end = _window()

    monkeypatch.setattr(
        gateway,
        "get_schedule",
        lambda *args: [
            FreeBusyWindow(start=start, end=end, is_free=False)
        ],
    )

    with pytest.raises(SlotConflictError):
        gateway.create_block(
            start=start,
            end=end,
            reason="Owner unavailable",
        )


def test_schedule_rejects_incomplete_pages(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse({
            "value": [],
            "@odata.nextLink": "https://graph.microsoft.com/next-page",
        }),
    )

    start, end = _window()

    with pytest.raises(OutlookUnavailableError):
        gateway.get_schedule(start, end)


def test_schedule_rejects_unexpected_timezone(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *args, **kwargs: FakeResponse({
            "value": [{
                "showAs": "busy",
                "start": {
                    "dateTime": "2026-09-25T10:00:00",
                    "timeZone": "Pacific Standard Time",
                },
                "end": {
                    "dateTime": "2026-09-25T11:00:00",
                    "timeZone": "Pacific Standard Time",
                },
            }]
        }),
    )

    start, end = _window()

    with pytest.raises(OutlookUnavailableError):
        gateway.get_schedule(start, end)


def test_create_event_rejects_naive_datetimes():
    gateway = _gateway()

    start = datetime(2026, 9, 25, 10, 0)
    end = datetime(2026, 9, 25, 11, 0)

    with pytest.raises(OutlookUnavailableError):
        gateway.create_event(
            subject="Tuxedo fitting",
            start=start,
            end=end,
            body=None,
        )


def test_create_event_rejects_invalid_window():
    gateway = _gateway()
    start, _ = _window()

    with pytest.raises(OutlookUnavailableError):
        gateway.create_event(
            subject="Tuxedo fitting",
            start=start,
            end=start,
            body=None,
        )


def test_request_rejects_empty_token():
    gateway = GraphOutlookGateway(
        calendar_id="test-calendar",
        access_token_provider=lambda: "",
    )

    with pytest.raises(OutlookUnavailableError):
        gateway._request("GET", "/me/events")


def test_request_allows_404_only_when_requested(monkeypatch):
    gateway = _gateway()

    monkeypatch.setattr(
        requests,
        "request",
        lambda **kwargs: FakeResponse({}, status_code=404),
    )

    response = gateway._request(
        "GET",
        "/me/events/missing",
        allow_not_found=True,
    )

    assert response.status_code == 404

    with pytest.raises(OutlookUnavailableError):
        gateway._request("GET", "/me/events/missing")
