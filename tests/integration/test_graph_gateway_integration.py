"""Flask API driven through the real ``GraphOutlookGateway``.

Only the HTTP call to Microsoft Graph is mocked, so these tests exercise
the seam that neither the gateway's own unit tests (which call it with
hand-built datetimes) nor the API tests (which use ``FakeOutlookGateway``)
cover: whether the datetimes the Flask services produce satisfy the real
gateway's contract, and whether Graph's UTC responses come back out of the
API in business-local time.

Graph responses use its real wire format: UTC ``dateTime`` values with
seven fractional-second digits.
"""
from unittest.mock import patch

import pytest
import requests

from app import create_app
from app.gateways.graph_outlook import GraphOutlookGateway
from config import TestingConfig

OWNER_HEADERS = {"Authorization": f"Bearer {TestingConfig.OWNER_ACCESS_TOKEN}"}

# 2026-09-29 is a Tuesday; America/Chicago is on CDT (UTC-5) that day,
# so 09:00 local == 14:00 UTC.
LOCAL_NINE_AM = "2026-09-29T09:00:00-05:00"
UTC_NINE_AM_GRAPH = "2026-09-29T14:00:00.0000000"
UTC_TEN_AM_GRAPH = "2026-09-29T14:45:00.0000000"


class FakeGraphResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} from Graph")


def graph_event(event_id="AAMk-existing", start=UTC_NINE_AM_GRAPH, end=UTC_TEN_AM_GRAPH,
                categories=None, show_as="busy"):
    return {
        "id": event_id,
        "subject": "Initial Fitting - Existing Customer",
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "categories": categories if categories is not None else ["tuxedo_appointment"],
        "showAs": show_as,
        "body": {"contentType": "text", "content": "Customer: Existing"},
    }


class FakeGraph:
    """Stand-in for ``requests.request`` that records calls and replays Graph responses."""

    def __init__(self):
        self.calls = []
        self.calendar_view_items = []
        self.event_by_id = {}
        self.error = None

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.error is not None:
            raise self.error
        if method == "POST":
            return FakeGraphResponse(201, {"id": "AAMk-new-event"})
        if "/calendarView" in url:
            return FakeGraphResponse(200, {"value": self.calendar_view_items})
        event_id = url.rsplit("/events/", 1)[-1]
        if event_id in self.event_by_id:
            return FakeGraphResponse(200, self.event_by_id[event_id])
        return FakeGraphResponse(404, {})

    def posts(self):
        return [c for c in self.calls if c["method"] == "POST"]


@pytest.fixture
def graph():
    return FakeGraph()


@pytest.fixture
def client(graph):
    gateway = GraphOutlookGateway(calendar_id="cal-1", access_token_provider=lambda: "test-token")
    app = create_app(config_object=TestingConfig, outlook_gateway=gateway)
    with patch("app.gateways.graph_outlook.requests.request", side_effect=graph):
        yield app.test_client()


def booking_payload(start="2026-09-29T09:00:00"):
    return {
        "customer": {"name": "Jane Doe", "email": "jane@example.com"},
        "appointment_type_id": 1,
        "start": start,
        "confirmation": True,
    }


def test_availability_skips_slot_busy_in_graph_and_returns_local_offsets(client, graph):
    graph.calendar_view_items = [graph_event()]

    resp = client.post("/api/v1/availability", json={
        "appointment_type": "initial_fitting",
        "date_start": "2026-09-29",
        "date_end": "2026-09-29",
        "max_options": 3,
    })

    assert resp.status_code == 200
    starts = [option["start"] for option in resp.get_json()["options"]]
    assert LOCAL_NINE_AM not in starts
    assert starts[0] == "2026-09-29T10:00:00-05:00"
    # The window sent to Graph carries the business-timezone offset.
    assert graph.calls[0]["params"]["startDateTime"] == LOCAL_NINE_AM


def test_booking_sends_utc_event_to_graph_and_returns_business_local_time(client, graph):
    resp = client.post("/api/v1/appointments", json=booking_payload())

    assert resp.status_code == 201
    appointment = resp.get_json()["appointment"]
    assert appointment["outlook_event_id"] == "AAMk-new-event"
    assert appointment["start"] == LOCAL_NINE_AM

    (post,) = graph.posts()
    assert post["json"]["start"] == {"dateTime": "2026-09-29T14:00:00", "timeZone": "UTC"}
    assert "tuxedo_appointment" in post["json"]["categories"]


def test_booking_accepts_client_supplied_offset(client, graph):
    """A client that already sends an offset (as /availability returns) must
    book the same instant as the naive business-local form."""
    resp = client.post("/api/v1/appointments", json=booking_payload(start=LOCAL_NINE_AM))

    assert resp.status_code == 201
    (post,) = graph.posts()
    assert post["json"]["start"]["dateTime"] == "2026-09-29T14:00:00"


def test_booking_over_busy_graph_slot_returns_409_and_writes_nothing(client, graph):
    graph.calendar_view_items = [graph_event()]

    resp = client.post("/api/v1/appointments", json=booking_payload())

    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "SLOT_CONFLICT"
    assert graph.posts() == []


@pytest.mark.parametrize("failure", [requests.ConnectionError("down"), requests.Timeout("slow")])
def test_graph_outage_returns_retryable_503(client, graph, failure):
    graph.error = failure

    resp = client.post("/api/v1/availability", json={
        "appointment_type": "initial_fitting",
        "date_start": "2026-09-29",
        "date_end": "2026-09-29",
    })

    assert resp.status_code == 503
    error = resp.get_json()["error"]
    assert error["code"] == "OUTLOOK_UNAVAILABLE"
    assert error["retryable"] is True


def test_owner_schedule_converts_graph_utc_to_business_local_time(client, graph):
    graph.calendar_view_items = [
        graph_event(),
        graph_event(event_id="AAMk-block", categories=["owner_block"]),
    ]

    resp = client.get(
        "/api/v1/owner/appointments?date_from=2026-09-29T00:00:00&date_to=2026-09-30T00:00:00",
        headers=OWNER_HEADERS,
    )

    assert resp.status_code == 200
    (appointment,) = resp.get_json()["appointments"]
    assert appointment["outlook_event_id"] == "AAMk-existing"
    assert appointment["start"] == LOCAL_NINE_AM
    assert appointment["end"] == "2026-09-29T09:45:00-05:00"


def test_owner_block_is_created_in_graph_as_owner_block(client, graph):
    resp = client.post(
        "/api/v1/owner/blocks",
        json={"start": "2026-09-29T13:00:00", "end": "2026-09-29T14:00:00", "reason": "Staff lunch"},
        headers=OWNER_HEADERS,
    )

    assert resp.status_code == 201
    assert resp.get_json()["block"]["start"] == "2026-09-29T13:00:00-05:00"
    (post,) = graph.posts()
    assert post["json"]["categories"] == ["owner_block"]
    assert post["json"]["start"]["dateTime"] == "2026-09-29T18:00:00"


def test_get_appointment_returns_business_local_time_from_graph(client, graph):
    graph.event_by_id["AAMk-existing"] = graph_event()

    resp = client.get("/api/v1/appointments/AAMk-existing", headers=OWNER_HEADERS)

    assert resp.status_code == 200
    assert resp.get_json()["appointment"]["start"] == LOCAL_NINE_AM


def test_get_appointment_missing_in_graph_returns_404(client):
    resp = client.get("/api/v1/appointments/does-not-exist", headers=OWNER_HEADERS)

    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "NOT_FOUND"
