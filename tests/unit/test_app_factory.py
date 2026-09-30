import pytest

from app import create_app
from app.gateways.graph_outlook import GraphOutlookGateway
from app.gateways.msal_auth import MsalTokenProvider
from app.gateways.outlook import FakeOutlookGateway
from app.services.intent import OpenAIIntentInterpreter
from config import TestingConfig


def test_invalid_business_timezone_fails_fast_at_startup():
    class BadTimezoneConfig(TestingConfig):
        BUSINESS_TIMEZONE = "Not/AZone"

    with pytest.raises(ValueError, match="IANA timezone"):
        create_app(
            config_object=BadTimezoneConfig,
            outlook_gateway=FakeOutlookGateway(),
        )


def test_graph_gateway_selection_wires_msal_and_graph():
    class GraphConfig(TestingConfig):
        OUTLOOK_GATEWAY = "graph"
        MS_GRAPH_CLIENT_ID = "test-client-id"
        MS_GRAPH_CLIENT_SECRET = "test-client-secret"
        MS_GRAPH_TENANT_ID = "test-tenant-id"
        MS_GRAPH_CALENDAR_ID = "test-calendar-id"
        GRAPH_TIMEOUT_SECONDS = 8

    app = create_app(config_object=GraphConfig)

    gateway = app.extensions["outlook_gateway"]
    token_provider = app.extensions["msal_token_provider"]

    assert isinstance(gateway, GraphOutlookGateway)
    assert isinstance(token_provider, MsalTokenProvider)

    assert gateway.calendar_id == "test-calendar-id"
    assert gateway.timeout_seconds == 8
    assert gateway.access_token_provider == token_provider.get_access_token


def test_fake_gateway_does_not_create_msal_provider():
    class FakeConfig(TestingConfig):
        OUTLOOK_GATEWAY = "fake"

    app = create_app(config_object=FakeConfig)

    assert isinstance(
        app.extensions["outlook_gateway"],
        FakeOutlookGateway,
    )
    assert "msal_token_provider" not in app.extensions


def test_unsupported_gateway_configuration_fails_fast():
    class InvalidGatewayConfig(TestingConfig):
        OUTLOOK_GATEWAY = "something-invalid"

    with pytest.raises(
        RuntimeError,
        match="Unsupported Outlook gateway configuration",
    ):
        create_app(config_object=InvalidGatewayConfig)


def test_openai_key_switches_intent_interpreter_to_openai():
    class OpenAIConfig(TestingConfig):
        OPENAI_API_KEY = "sk-test-not-a-real-key"

    app = create_app(
        config_object=OpenAIConfig,
        outlook_gateway=FakeOutlookGateway(),
    )

    intent_service = (
        app.extensions["scheduling_orchestrator"]._intent_service
    )

    assert isinstance(
        intent_service._interpreter,
        OpenAIIntentInterpreter,
    )
