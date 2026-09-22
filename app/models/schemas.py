"""Request validation schemas and internal dataclasses.

Marshmallow schemas validate everything coming in over HTTP *and* the
structured intent returned by the AI adapter before it is trusted by any
business logic, per Week 4 section 6.2 ("the application still validates
every returned field before applying business rules or contacting
Outlook").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_, time as time_

from marshmallow import Schema, ValidationError as MarshmallowValidationError, fields, validate

ALLOWED_ACTORS = ("customer", "owner")
ALLOWED_ACTIONS = ("find_availability", "list_schedule", "block_time", "clarify")


class IntentRequestSchema(Schema):
    text = fields.String(required=True, validate=validate.Length(min=1, max=500))
    actor = fields.String(required=True, validate=validate.OneOf(ALLOWED_ACTORS))
    timezone = fields.String(required=False, load_default=None)


class SchedulingIntentSchema(Schema):
    """Validates the structured object returned by the intent interpreter."""

    action = fields.String(required=True, validate=validate.OneOf(ALLOWED_ACTIONS))
    appointment_type = fields.String(required=False, allow_none=True, load_default=None)
    date_start = fields.Date(required=False, allow_none=True, load_default=None)
    date_end = fields.Date(required=False, allow_none=True, load_default=None)
    time_start = fields.Time(required=False, allow_none=True, load_default=None)
    time_end = fields.Time(required=False, allow_none=True, load_default=None)
    confidence = fields.Float(required=False, load_default=0.0, validate=validate.Range(min=0.0, max=1.0))
    clarification_question = fields.String(required=False, allow_none=True, load_default=None)


class AvailabilityRequestSchema(Schema):
    appointment_type = fields.String(required=True, validate=validate.Length(min=1, max=100))
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    time_start = fields.Time(required=False, allow_none=True, load_default=None)
    time_end = fields.Time(required=False, allow_none=True, load_default=None)
    max_options = fields.Integer(required=False, load_default=3, validate=validate.Range(min=1, max=10))


class CustomerSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    email = fields.Email(required=True)
    phone = fields.String(required=False, allow_none=True, validate=validate.Length(max=30))


class AppointmentCreateSchema(Schema):
    customer = fields.Nested(CustomerSchema, required=True)
    appointment_type_id = fields.Integer(required=True)
    start = fields.DateTime(required=True)
    confirmation = fields.Boolean(required=True)
    notes = fields.String(required=False, allow_none=True, validate=validate.Length(max=500))


class OwnerBlockCreateSchema(Schema):
    start = fields.DateTime(required=True)
    end = fields.DateTime(required=True)
    reason = fields.String(required=False, allow_none=True, validate=validate.Length(max=200))


class AppointmentTypeUpdateSchema(Schema):
    duration_minutes = fields.Integer(required=False, validate=validate.Range(min=5, max=480))
    buffer_minutes = fields.Integer(required=False, validate=validate.Range(min=0, max=120))
    active = fields.Boolean(required=False)


# --- Internal dataclasses used between services (not directly serialized) ---


@dataclass
class SchedulingIntent:
    action: str
    appointment_type: str | None = None
    date_start: date_ | None = None
    date_end: date_ | None = None
    time_start: time_ | None = None
    time_end: time_ | None = None
    confidence: float = 0.0
    clarification_question: str | None = None

    @property
    def needs_clarification(self) -> bool:
        return self.action == "clarify" or self.clarification_question is not None


@dataclass
class SlotOption:
    slot_id: str
    start: str  # ISO 8601
    end: str  # ISO 8601


@dataclass
class BookingCommand:
    customer_name: str
    customer_email: str
    customer_phone: str | None
    appointment_type_id: int
    start_iso: str
    notes: str | None
    idempotency_key: str | None = None


@dataclass
class AppointmentResult:
    id: int
    status: str
    start: str
    end: str
    outlook_event_id: str


__all__ = [
    "IntentRequestSchema",
    "SchedulingIntentSchema",
    "AvailabilityRequestSchema",
    "AppointmentCreateSchema",
    "OwnerBlockCreateSchema",
    "AppointmentTypeUpdateSchema",
    "MarshmallowValidationError",
    "SchedulingIntent",
    "SlotOption",
    "BookingCommand",
    "AppointmentResult",
]
