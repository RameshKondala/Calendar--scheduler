"""Contract tests for the standard API error envelope (Week 4 section 3.2).

Distinct from the functional/integration tests elsewhere: those check
that *a specific endpoint* behaves correctly; this checks that *every*
error response, regardless of which endpoint produced it, honors the one
documented shape -- ``{"error": {code, message, retryable, request_id}}``
-- with the right types and the right status/retryable/code combination.
A new endpoint that raises an existing AppError subclass is automatically
covered without writing a new test here; only a genuinely new error code
needs one.
"""
import pytest

# (trigger, expected_status, expected_code, expected_retryable)
CASES = [
    pytest.param(
        lambda c: c.post("/api/v1/intent", json={"text": "", "actor": "customer"}),
        400, "VALIDATION_ERROR", False, id="validation_error",
    ),
    pytest.param(
        lambda c: c.get("/api/v1/owner/appointments?date_from=2026-09-21T00:00:00&date_to=2026-09-22T00:00:00"),
        401, "UNAUTHORIZED", False, id="unauthorized",
    ),
    pytest.param(
        lambda c: c.get("/api/v1/appointments/does-not-exist"),
        401, "UNAUTHORIZED", False, id="unauthorized_guest_lookup",
    ),
    pytest.param(
        lambda c: c.get("/api/v1/does-not-exist"),
        404, "NOT_FOUND", False, id="not_found",
    ),
    pytest.param(
        lambda c: c.delete("/api/v1/health"),
        405, "VALIDATION_ERROR", False, id="method_not_allowed",
    ),
]


@pytest.mark.parametrize("trigger,expected_status,expected_code,expected_retryable", CASES)
def test_error_envelope_matches_the_documented_contract(
    client, trigger, expected_status, expected_code, expected_retryable
):
    response = trigger(client)

    assert response.status_code == expected_status
    body = response.get_json()

    assert set(body.keys()) == {"error"}
    error = body["error"]
    assert set(error.keys()) == {"code", "message", "retryable", "request_id"}

    assert error["code"] == expected_code
    assert isinstance(error["message"], str) and error["message"]
    assert error["retryable"] is expected_retryable
    assert isinstance(error["request_id"], str) and error["request_id"].startswith("req_")


def test_forbidden_contract_for_a_signed_in_but_disallowed_owner(client, app):
    """Exercises 403 specifically, which needs a signed-in-but-not-allowed
    session rather than a simple one-shot request."""
    with client.session_transaction() as sess:
        sess["owner_upn"] = "not-an-owner@example.com"

    response = client.get(
        "/api/v1/owner/appointments?date_from=2026-09-21T00:00:00&date_to=2026-09-22T00:00:00"
    )

    assert response.status_code == 403
    error = response.get_json()["error"]
    assert error["code"] == "FORBIDDEN"
    assert error["retryable"] is False
    assert set(error.keys()) == {"code", "message", "retryable", "request_id"}


def test_rate_limited_contract(client):
    from config import TestingConfig

    from app import create_app
    from app.gateways.outlook import FakeOutlookGateway

    class TinyLimitConfig(TestingConfig):
        RATE_LIMIT_AI_PER_MINUTE = 1

    tiny_client = create_app(config_object=TinyLimitConfig, outlook_gateway=FakeOutlookGateway()).test_client()
    payload = {"text": "a fitting", "actor": "customer"}
    tiny_client.post("/api/v1/intent", json=payload)

    response = tiny_client.post("/api/v1/intent", json=payload)

    assert response.status_code == 429
    error = response.get_json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["retryable"] is True
    assert set(error.keys()) == {"code", "message", "retryable", "request_id"}


def test_slot_conflict_contract(client):
    payload = {
        "customer": {"name": "Jane Doe", "email": "jane@example.com"},
        "appointment_type_id": 1,
        "start": "2026-09-21T09:00:00",
        "confirmation": True,
    }
    client.post("/api/v1/appointments", json=payload)

    response = client.post("/api/v1/appointments", json=payload)

    assert response.status_code == 409
    error = response.get_json()["error"]
    assert error["code"] == "SLOT_CONFLICT"
    assert error["retryable"] is True
    assert set(error.keys()) == {"code", "message", "retryable", "request_id"}
