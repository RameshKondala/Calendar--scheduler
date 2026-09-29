import pytest

from app import create_app
from app.gateways.outlook import FakeOutlookGateway
from app.services.intent import OpenAIIntentInterpreter
from config import TestingConfig


def test_invalid_business_timezone_fails_fast_at_startup():
    class BadTimezoneConfig(TestingConfig):
        BUSINESS_TIMEZONE = "Not/AZone"

    with pytest.raises(ValueError, match="IANA timezone"):
        create_app(config_object=BadTimezoneConfig, outlook_gateway=FakeOutlookGateway())


def test_graph_gateway_selection_is_not_wired_yet():
    """OUTLOOK_GATEWAY=graph is the pending integration point for
    GraphOutlookGateway. Until it is wired (it needs an access-token
    provider), selecting it must fail loudly rather than silently fall back
    to the fake."""
    class GraphConfig(TestingConfig):
        OUTLOOK_GATEWAY = "graph"

    with pytest.raises(RuntimeError, match="not yet implemented"):
        create_app(config_object=GraphConfig)


def test_openai_key_switches_intent_interpreter_to_openai():
    class OpenAIConfig(TestingConfig):
        OPENAI_API_KEY = "sk-test-not-a-real-key"

    app = create_app(config_object=OpenAIConfig, outlook_gateway=FakeOutlookGateway())
    intent_service = app.extensions["scheduling_orchestrator"]._intent_service

    assert isinstance(intent_service._interpreter, OpenAIIntentInterpreter)
