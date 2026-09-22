"""OpenAI Responses API adapter (ADR-007).

Isolates the OpenAI SDK behind a narrow ``raw_interpret`` call. This module
is the *only* place the OpenAI SDK is imported (section 5.1). It never
talks to Microsoft Graph and never creates or confirms appointments -- it
only returns a raw structured-intent dict that ``IntentService`` validates.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.errors.handlers import AIUnavailableError

logger = logging.getLogger(__name__)

SCHEDULING_INTENT_JSON_SCHEMA: dict[str, Any] = {
    "name": "SchedulingIntent",
    "schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["find_availability", "list_schedule", "block_time", "clarify"],
            },
            "appointment_type": {"type": ["string", "null"]},
            "date_start": {"type": ["string", "null"]},
            "date_end": {"type": ["string", "null"]},
            "time_start": {"type": ["string", "null"]},
            "time_end": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
            "clarification_question": {"type": ["string", "null"]},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    "strict": True,
}

SYSTEM_PROMPT = (
    "You convert a tuxedo rental customer or owner's natural-language scheduling "
    "request into a constrained SchedulingIntent JSON object. You never invent "
    "availability, business hours, or confirmed appointments. If required "
    "information is missing, set action to 'clarify' and provide a plain-language "
    "clarification_question."
)


class OpenAIIntentAdapter:
    """Thin wrapper around the OpenAI Responses API with Structured Outputs.

    Requires the ``openai`` package and ``OPENAI_API_KEY`` to be configured.
    Any network/timeout/SDK failure is translated to ``AIUnavailableError``
    so callers never see raw OpenAI exceptions.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", timeout_seconds: float = 8.0) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = None  # lazily constructed to avoid import cost when unused

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI  # imported lazily; only dependency user of this module
            except ImportError as exc:  # pragma: no cover - exercised only if package missing
                raise AIUnavailableError("The AI interpreter is not configured.") from exc
            self._client = OpenAI(api_key=self._api_key, timeout=self._timeout_seconds)
        return self._client

    def raw_interpret(self, text: str, actor: str, timezone: str) -> dict:
        """Call the OpenAI Responses API and return the raw structured intent dict."""
        client = self._get_client()
        try:
            response = client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"actor: {actor}\ntimezone: {timezone}\nrequest: {text}"
                        ),
                    },
                ],
                response_format={"type": "json_schema", "json_schema": SCHEDULING_INTENT_JSON_SCHEMA},
            )
        except Exception as exc:  # noqa: BLE001 - any SDK/network error maps to AI_UNAVAILABLE
            logger.warning("OpenAI intent call failed: %s", exc)
            raise AIUnavailableError() from exc

        try:
            raw_text = response.output_text
            return json.loads(raw_text)
        except (AttributeError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("OpenAI intent response could not be parsed: %s", exc)
            raise AIUnavailableError("The AI interpreter returned an unreadable response.") from exc
