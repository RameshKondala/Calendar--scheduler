"""AI intent interpretation service (Strategy/Adapter pattern, section 6.2).

``IntentService`` never trusts raw AI output: every field returned by an
interpreter is re-validated through ``SchedulingIntentSchema`` before it
becomes a ``SchedulingIntent`` the orchestrator can act on. The confidence
value is informational only and never bypasses validation (section 6.2 table).
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import date, datetime, time, timedelta

from marshmallow import ValidationError as MarshmallowValidationError

from app.config_store.appointment_types import AppointmentTypeStore
from app.errors.handlers import ValidationError as AppValidationError
from app.gateways.openai_intent import OpenAIIntentAdapter
from app.models.schemas import SchedulingIntent, SchedulingIntentSchema


class IntentInterpreter(ABC):
    """Interface every intent-interpreter strategy must satisfy."""

    @abstractmethod
    def raw_interpret(self, text: str, actor: str, timezone: str) -> dict:
        """Return a raw (untrusted) structured-intent dict."""


class OpenAIIntentInterpreter(IntentInterpreter):
    """Production interpreter backed by the OpenAI Responses API."""

    def __init__(self, adapter: OpenAIIntentAdapter) -> None:
        self._adapter = adapter

    def raw_interpret(self, text: str, actor: str, timezone: str) -> dict:
        return self._adapter.raw_interpret(text, actor, timezone)


class FakeIntentInterpreter(IntentInterpreter):
    """Deterministic keyword-based interpreter for local dev and tests.

    This intentionally does not try to be a good NLU system -- it exists so
    the application runs end-to-end without an OpenAI key, per section 8.2
    ("select the fake interpreter for local tests").
    """

    _TYPE_KEYWORDS = {
        "initial_fitting": ["initial fitting", "first fitting", "fitting"],
        "final_fitting": ["final fitting"],
        "pickup": ["pick up", "pickup", "collect"],
        "return": ["return", "drop off"],
    }

    def __init__(self, appointment_type_store: AppointmentTypeStore) -> None:
        self._appointment_type_store = appointment_type_store

    def raw_interpret(self, text: str, actor: str, timezone: str) -> dict:
        lowered = text.lower()

        appointment_type = None
        for code, keywords in self._TYPE_KEYWORDS.items():
            if any(k in lowered for k in keywords):
                appointment_type = code
                break

        target_date = self._extract_date(lowered)
        time_start = self._extract_time_after(lowered)

        if appointment_type is None or target_date is None:
            return {
                "action": "clarify",
                "appointment_type": appointment_type,
                "confidence": 0.3,
                "clarification_question": (
                    "Could you tell me what type of appointment you need and what day works for you?"
                ),
            }

        return {
            "action": "find_availability",
            "appointment_type": appointment_type,
            "date_start": target_date.isoformat(),
            "date_end": target_date.isoformat(),
            "time_start": time_start.isoformat() if time_start else None,
            "time_end": None,
            "confidence": 0.6,
            "clarification_question": None,
        }

    @staticmethod
    def _extract_date(lowered: str) -> date | None:
        today = datetime.now().date()
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for i, name in enumerate(weekdays):
            if name in lowered:
                days_ahead = (i - today.weekday()) % 7
                days_ahead = days_ahead or 7  # "next Friday" means the upcoming one, not today
                return today + timedelta(days=days_ahead)
        if "tomorrow" in lowered:
            return today + timedelta(days=1)
        if "today" in lowered:
            return today
        return None

    @staticmethod
    def _extract_time_after(lowered: str) -> time | None:
        match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", lowered)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return time(hour, minute)


class IntentService:
    """Validates raw interpreter output into a trusted ``SchedulingIntent``."""

    def __init__(self, interpreter: IntentInterpreter) -> None:
        self._interpreter = interpreter

    def interpret(self, text: str, actor: str, timezone: str) -> SchedulingIntent:
        raw = self._interpreter.raw_interpret(text=text, actor=actor, timezone=timezone)
        try:
            loaded = SchedulingIntentSchema().load(raw)
        except MarshmallowValidationError as exc:
            raise AppValidationError(f"The interpreted intent was invalid: {exc.messages}") from exc
        return SchedulingIntent(**loaded)
