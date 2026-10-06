"""Confirms rate limiting is actually enforced through real HTTP calls,
not just at the RateLimiter unit level. Uses tiny limits so a handful of
requests is enough to trip them, rather than needing 30+ requests per test.
"""
import pytest

from app import create_app
from config import TestingConfig


class TinyAiLimitConfig(TestingConfig):
    RATE_LIMIT_AI_PER_MINUTE = 2


class TinyBookingLimitConfig(TestingConfig):
    RATE_LIMIT_BOOKING_PER_MINUTE = 1


@pytest.fixture
def ai_limited_client():
    from app.gateways.outlook import FakeOutlookGateway
    app = create_app(config_object=TinyAiLimitConfig, outlook_gateway=FakeOutlookGateway())
    return app.test_client()


@pytest.fixture
def booking_limited_client():
    from app.gateways.outlook import FakeOutlookGateway
    app = create_app(config_object=TinyBookingLimitConfig, outlook_gateway=FakeOutlookGateway())
    return app.test_client()


def test_intent_endpoint_enforces_the_ai_rate_limit(ai_limited_client):
    payload = {"text": "I need a fitting next Monday at 9am", "actor": "customer"}

    first = ai_limited_client.post("/api/v1/intent", json=payload)
    second = ai_limited_client.post("/api/v1/intent", json=payload)
    third = ai_limited_client.post("/api/v1/intent", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    error = third.get_json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["retryable"] is True


def test_availability_and_intent_share_the_same_ai_bucket(ai_limited_client):
    """Week 4 section 3.1 groups AI and availability under one limit."""
    intent_payload = {"text": "a fitting", "actor": "customer"}
    availability_payload = {
        "appointment_type": "initial_fitting", "date_start": "2026-09-28", "date_end": "2026-09-28",
    }

    ai_limited_client.post("/api/v1/intent", json=intent_payload)
    ai_limited_client.post("/api/v1/availability", json=availability_payload)
    third = ai_limited_client.post("/api/v1/intent", json=intent_payload)

    assert third.status_code == 429


def test_appointments_endpoint_enforces_its_own_booking_rate_limit(booking_limited_client):
    payload = {
        "customer": {"name": "Jane Doe", "email": "jane@example.com"},
        "appointment_type_id": 1,
        "start": "2026-09-28T09:00:00",
        "confirmation": True,
    }

    first = booking_limited_client.post("/api/v1/appointments", json=payload)
    second = booking_limited_client.post(
        "/api/v1/appointments", json={**payload, "start": "2026-09-28T11:00:00"}
    )

    assert first.status_code == 201
    assert second.status_code == 429


def test_rate_limit_is_keyed_per_client_not_global(ai_limited_client):
    """A second client (different IP) must not be blocked by the first
    client's usage."""
    payload = {"text": "a fitting", "actor": "customer"}
    ai_limited_client.post("/api/v1/intent", json=payload, environ_overrides={"REMOTE_ADDR": "10.0.0.1"})
    ai_limited_client.post("/api/v1/intent", json=payload, environ_overrides={"REMOTE_ADDR": "10.0.0.1"})

    still_fresh_client = ai_limited_client.post(
        "/api/v1/intent", json=payload, environ_overrides={"REMOTE_ADDR": "10.0.0.2"}
    )
    assert still_fresh_client.status_code == 200
