"""Tests for the OpenAI adapter's error-mapping behavior.

These use a mocked client rather than real network calls, so no
OPENAI_API_KEY or network access is required to run them (per the
Week 5 instruction to use mocks/fakes rather than requiring Microsoft
Graph/OpenAI credentials for normal unit tests).
"""
from unittest.mock import MagicMock

import pytest

from app.errors.handlers import AIUnavailableError
from app.gateways.openai_intent import OpenAIIntentAdapter


@pytest.fixture
def adapter():
    return OpenAIIntentAdapter(api_key="test-key", model="gpt-4o-mini", timeout_seconds=1.0)


def test_raw_interpret_returns_parsed_json_on_success(adapter, monkeypatch):
    fake_response = MagicMock()
    fake_response.output_text = '{"action": "find_availability", "confidence": 0.9}'
    fake_client = MagicMock()
    fake_client.responses.create.return_value = fake_response
    monkeypatch.setattr(adapter, "_get_client", lambda: fake_client)

    result = adapter.raw_interpret("book a fitting", actor="customer", timezone="UTC")

    assert result == {"action": "find_availability", "confidence": 0.9}
    fake_client.responses.create.assert_called_once()


def test_raw_interpret_maps_sdk_exception_to_ai_unavailable(adapter, monkeypatch):
    fake_client = MagicMock()
    fake_client.responses.create.side_effect = TimeoutError("upstream timed out")
    monkeypatch.setattr(adapter, "_get_client", lambda: fake_client)

    with pytest.raises(AIUnavailableError):
        adapter.raw_interpret("book a fitting", actor="customer", timezone="UTC")


def test_raw_interpret_maps_unparseable_response_to_ai_unavailable(adapter, monkeypatch):
    fake_response = MagicMock()
    fake_response.output_text = "not valid json"
    fake_client = MagicMock()
    fake_client.responses.create.return_value = fake_response
    monkeypatch.setattr(adapter, "_get_client", lambda: fake_client)

    with pytest.raises(AIUnavailableError):
        adapter.raw_interpret("book a fitting", actor="customer", timezone="UTC")


def test_raw_interpret_maps_missing_output_text_to_ai_unavailable(adapter, monkeypatch):
    fake_response = MagicMock(spec=[])  # no output_text attribute at all
    fake_client = MagicMock()
    fake_client.responses.create.return_value = fake_response
    monkeypatch.setattr(adapter, "_get_client", lambda: fake_client)

    with pytest.raises(AIUnavailableError):
        adapter.raw_interpret("book a fitting", actor="customer", timezone="UTC")
