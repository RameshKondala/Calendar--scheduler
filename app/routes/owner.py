"""Owner-only routes (section 3.7). All require owner authorization."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from marshmallow import ValidationError as MarshmallowValidationError

from app.errors.handlers import NotFoundError, ValidationError
from app.models.schemas import AppointmentTypeUpdateSchema, OwnerBlockCreateSchema
from app.routes.auth import require_owner

owner_bp = Blueprint("owner", __name__)


def _orchestrator():
    return current_app.extensions["scheduling_orchestrator"]


def _appointment_type_store():
    return current_app.extensions["appointment_type_store"]


@owner_bp.get("/owner/appointments")
@require_owner
def get_owner_appointments():
    date_from_raw = request.args.get("date_from")
    date_to_raw = request.args.get("date_to")

    if not date_from_raw or not date_to_raw:
        raise ValidationError("date_from and date_to query parameters are required.")

    try:
        date_from = datetime.fromisoformat(date_from_raw)
        date_to = datetime.fromisoformat(date_to_raw)
    except ValueError as exc:
        raise ValidationError("date_from and date_to must be ISO 8601 datetimes.") from exc

    events = _orchestrator().list_owner_schedule(date_from, date_to)

    return (
        jsonify(
            {
                "appointments": [
                    {
                        "outlook_event_id": e.event_id,
                        "subject": e.subject,
                        "start": e.start.isoformat(),
                        "end": e.end.isoformat(),
                        "categories": e.categories,
                    }
                    for e in events
                ]
            }
        ),
        200,
    )


@owner_bp.post("/owner/blocks")
@require_owner
def post_owner_blocks():
    payload = request.get_json(silent=True) or {}
    try:
        data = OwnerBlockCreateSchema().load(payload)
    except MarshmallowValidationError as exc:
        raise ValidationError(str(exc.messages)) from exc

    event = _orchestrator().create_owner_block(data["start"], data["end"], data.get("reason"))

    return (
        jsonify(
            {
                "block": {
                    "outlook_event_id": event.event_id,
                    "start": event.start.isoformat(),
                    "end": event.end.isoformat(),
                }
            }
        ),
        201,
    )


@owner_bp.put("/owner/appointment-types/<int:type_id>")
@require_owner
def put_appointment_type(type_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        data = AppointmentTypeUpdateSchema().load(payload)
    except MarshmallowValidationError as exc:
        raise ValidationError(str(exc.messages)) from exc

    updated = _appointment_type_store().update(
        type_id,
        duration_minutes=data.get("duration_minutes"),
        buffer_minutes=data.get("buffer_minutes"),
        active=data.get("active"),
    )
    if updated is None:
        raise NotFoundError(f"Appointment type id {type_id} was not found.")

    return (
        jsonify(
            {
                "appointment_type": {
                    "id": updated.id,
                    "code": updated.code,
                    "display_name": updated.display_name,
                    "duration_minutes": updated.duration_minutes,
                    "buffer_minutes": updated.buffer_minutes,
                    "active": updated.active,
                }
            }
        ),
        200,
    )
