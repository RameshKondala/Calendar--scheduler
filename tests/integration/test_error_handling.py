"""Exercises the centralized error handling in app/errors/handlers.py,
including branches not reached by the normal happy-path/validation tests
elsewhere: the 405 method-not-allowed handler, the >=500 logging branch
for AppError, and the catch-all handler for a completely unexpected
exception.
"""
from flask import Flask

from app import create_app
from app.errors.handlers import AppError, register_error_handlers
from app.gateways.outlook import FakeOutlookGateway
from config import TestingConfig


def test_method_not_allowed_returns_standard_contract(client):
    # /api/v1/health only supports GET.
    resp = client.delete("/api/v1/health")
    assert resp.status_code == 405
    body = resp.get_json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "request_id" in body["error"]


def test_outlook_unavailable_returns_503_with_retryable_true(app):
    unavailable_gateway = FakeOutlookGateway(force_unavailable=True)
    broken_app = create_app(config_object=TestingConfig, outlook_gateway=unavailable_gateway)
    client = broken_app.test_client()

    resp = client.post(
        "/api/v1/availability",
        json={
            "appointment_type": "initial_fitting",
            "date_start": "2026-09-21",
            "date_end": "2026-09-21",
        },
    )

    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"]["code"] == "OUTLOOK_UNAVAILABLE"
    assert body["error"]["retryable"] is True


def test_unexpected_exception_returns_generic_internal_error():
    """The catch-all handler must never leak the real exception message,
    a stack trace, or any internal details to the client."""
    probe_app = Flask(__name__)
    register_error_handlers(probe_app)

    @probe_app.get("/boom")
    def boom():
        raise RuntimeError("some sensitive internal detail that must not leak")

    client = probe_app.test_client()
    resp = client.get("/boom")

    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "sensitive internal detail" not in body["error"]["message"]


def test_app_error_subclass_without_message_uses_default_message():
    class CustomError(AppError):
        code = "VALIDATION_ERROR"
        http_status = 400
        default_message = "custom default"

    err = CustomError()
    assert err.message == "custom default"
