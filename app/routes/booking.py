"""Customer-facing booking routes (sections 3.4-3.6).

Routes stay thin: request -> validation -> service -> integration
boundary -> response. No provider-specific or business logic lives here.
"""
from __future__ import annotations

import uuid

from flask import Blueprint, current_app, jsonify, request
from marshmallow import ValidationError as MarshmallowValidationError

from app.errors.handlers import NotFoundError, UnauthorizedError, ValidationError
from app.models.schemas import (
    AppointmentCreateSchema,
    AppointmentResult,
    AvailabilityRequestSchema,
    BookingCommand,
    IntentRequestSchema,
)
from app.routes.auth import is_owner_request
from app.services.rate_limit import rate_limited
from app.services import confirmation_tokens

booking_bp = Blueprint("booking", __name__)


def _orchestrator():
    return current_app.extensions["scheduling_orchestrator"]


def _appointment_type_store():
    return current_app.extensions["appointment_type_store"]


def _serialize_appointment(result: AppointmentResult) -> dict:
    return {
        "id": result.id,
        "status": result.status,
        "start": result.start,
        "end": result.end,
        "outlook_event_id": result.outlook_event_id,
    }


@booking_bp.post("/intent")
@rate_limited("ai")
def post_intent():
    payload = request.get_json(silent=True) or {}
    try:
        data = IntentRequestSchema().load(payload)
    except MarshmallowValidationError as exc:
        raise ValidationError(str(exc.messages)) from exc

    timezone = data.get("timezone") or current_app.config["BUSINESS_TIMEZONE"]
    intent = _orchestrator().interpret_request(text=data["text"], actor=data["actor"], timezone=timezone)

    return (
        jsonify(
            {
                "intent": {
                    "action": intent.action,
                    "appointment_type": intent.appointment_type,
                    "date_start": intent.date_start.isoformat() if intent.date_start else None,
                    "date_end": intent.date_end.isoformat() if intent.date_end else None,
                    "time_start": intent.time_start.isoformat() if intent.time_start else None,
                    "time_end": intent.time_end.isoformat() if intent.time_end else None,
                    "confidence": intent.confidence,
                },
                "needs_clarification": intent.needs_clarification,
                "clarification_question": intent.clarification_question,
            }
        ),
        200,
    )


@booking_bp.post("/availability")
@rate_limited("ai")
def post_availability():
    payload = request.get_json(silent=True) or {}
    try:
        data = AvailabilityRequestSchema().load(payload)
    except MarshmallowValidationError as exc:
        raise ValidationError(str(exc.messages)) from exc

    options = _orchestrator().find_options(
        appointment_type_code=data["appointment_type"],
        date_start=data["date_start"],
        date_end=data["date_end"],
        time_start=data.get("time_start"),
        time_end=data.get("time_end"),
        max_options=data["max_options"],
    )

    return (
        jsonify(
            {
                "options": [{"slot_id": o.slot_id, "start": o.start, "end": o.end} for o in options],
                "source": "outlook",
                "expires_in_seconds": 120,
            }
        ),
        200,
    )


@booking_bp.post("/appointments")
@rate_limited("booking")
def post_appointments():
    payload = request.get_json(silent=True) or {}
    try:
        data = AppointmentCreateSchema().load(payload)
    except MarshmallowValidationError as exc:
        raise ValidationError(str(exc.messages)) from exc

    if not data["confirmation"]:
        raise ValidationError("confirmation must be true to create an appointment.")

    idempotency_key = request.headers.get("Idempotency-Key") or str(uuid.uuid4())

    command = BookingCommand(
        customer_name=data["customer"]["name"],
        customer_email=data["customer"]["email"],
        customer_phone=data["customer"].get("phone"),
        appointment_type_id=data["appointment_type_id"],
        start_iso=data["start"].isoformat(),
        notes=data.get("notes"),
        idempotency_key=idempotency_key,
    )

    result = _orchestrator().confirm_booking(command)
    token = confirmation_tokens.issue(current_app.config["SECRET_KEY"], result.outlook_event_id)

    return (
        jsonify({
            "appointment": _serialize_appointment(result),
            "confirmation_token": token,
            "message": "Your appointment is confirmed. Keep the confirmation_token to look this booking up later.",
        }),
        201,
    )


@booking_bp.get("/appointments/<event_id>")
def get_appointment(event_id: str):
    token = request.args.get("token") or request.headers.get("X-Confirmation-Token")
    has_guest_token = confirmation_tokens.verify(current_app.config["SECRET_KEY"], token, event_id)

    # Week 4 section 3.3: this endpoint is "guest token or owner" -- the
    # Outlook event id alone is not authorization to read a booking.
    if not (has_guest_token or is_owner_request()):
        raise UnauthorizedError(
            "Provide the confirmation_token from your booking (as ?token=... or "
            "X-Confirmation-Token), or sign in as the owner."
        )

    result = _orchestrator().get_appointment(event_id)
    if result is None:
        raise NotFoundError("No appointment was found with that id.")
    return jsonify({"appointment": _serialize_appointment(result)}), 200


@booking_bp.get("/appointment-types")
def get_appointment_types():
    types = _appointment_type_store().list_active()
    return (
        jsonify(
            {
                "appointment_types": [
                    {
                        "id": t.id,
                        "code": t.code,
                        "display_name": t.display_name,
                        "duration_minutes": t.duration_minutes,
                        "buffer_minutes": t.buffer_minutes,
                    }
                    for t in types
                ]
            }
        ),
        200,
    )
