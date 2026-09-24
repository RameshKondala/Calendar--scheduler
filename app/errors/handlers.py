"""Application error types and centralized Flask error handling.

Every error returned by the API follows the standard contract defined in the
Week 4 design (section 3.2):

    {"error": {"code": ..., "message": ..., "retryable": ..., "request_id": ...}}

Routes and services should raise ``AppError`` subclasses instead of letting
provider-specific exceptions (Graph, OpenAI, etc.) leak across the boundary.
"""
from __future__ import annotations

import logging
import uuid

from flask import Flask, g, jsonify, request

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for all application errors that map to the API error contract."""

    code = "INTERNAL_ERROR"
    http_status = 500
    retryable = False
    default_message = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message

    def to_response(self, request_id: str) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "request_id": request_id,
            }
        }


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 400
    retryable = False
    default_message = "The request failed validation."


class UnauthorizedError(AppError):
    code = "UNAUTHORIZED"
    http_status = 401
    retryable = False
    default_message = "Authentication is missing or invalid."


class ForbiddenError(AppError):
    code = "FORBIDDEN"
    http_status = 403
    retryable = False
    default_message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404
    retryable = False
    default_message = "The requested resource was not found."


class SlotConflictError(AppError):
    code = "SLOT_CONFLICT"
    http_status = 409
    retryable = True
    default_message = "The selected slot is no longer available. Please choose another time."


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    http_status = 429
    retryable = True
    default_message = "Too many requests. Please slow down and try again shortly."


class AIUnavailableError(AppError):
    code = "AI_UNAVAILABLE"
    http_status = 503
    retryable = True
    default_message = "We could not process your request right now. Please try again shortly."


class OutlookUnavailableError(AppError):
    code = "OUTLOOK_UNAVAILABLE"
    http_status = 503
    retryable = True
    default_message = (
        "We are having trouble checking the calendar right now. Please try again in a few minutes."
    )


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    http_status = 500
    retryable = True
    default_message = "An unexpected server error occurred."


def _get_request_id() -> str:
    return getattr(g, "request_id", "unknown")


def register_error_handlers(app: Flask) -> None:
    """Attach centralized error handling to the Flask app.

    Ensures no stack traces, secrets, or internal implementation details are
    ever exposed to the client, and that every error response matches the
    standard contract.
    """

    @app.before_request
    def _assign_request_id() -> None:
        g.request_id = request.headers.get("X-Request-Id", f"req_{uuid.uuid4().hex[:12]}")

    @app.errorhandler(AppError)
    def _handle_app_error(err: AppError):
        request_id = _get_request_id()
        if err.http_status >= 500:
            logger.exception("Unhandled AppError %s: %s", err.code, err.message, extra={"request_id": request_id})
        else:
            logger.info("AppError %s: %s", err.code, err.message, extra={"request_id": request_id})
        return jsonify(err.to_response(request_id)), err.http_status

    @app.errorhandler(404)
    def _handle_404(_err):
        request_id = _get_request_id()
        err = NotFoundError("The requested endpoint does not exist.")
        return jsonify(err.to_response(request_id)), err.http_status

    @app.errorhandler(405)
    def _handle_405(_err):
        request_id = _get_request_id()
        err = ValidationError("This HTTP method is not allowed for this endpoint.")
        # Use the actual 405 status here rather than err.http_status (400):
        # this handler reformats Werkzeug's real "method not allowed" result,
        # so the response must keep returning 405, not the ValidationError
        # class's own default status.
        return jsonify(err.to_response(request_id)), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        request_id = _get_request_id()
        logger.exception("Unhandled exception", extra={"request_id": request_id})
        internal = InternalError()
        return jsonify(internal.to_response(request_id)), internal.http_status
