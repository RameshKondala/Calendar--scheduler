"""Unit tests for Microsoft Entra / MSAL authentication."""

from unittest.mock import MagicMock

import pytest

from app.errors.handlers import OutlookUnavailableError
from app.gateways.msal_auth import GRAPH_SCOPES, MsalTokenProvider


@pytest.fixture
def token_store():
    return {}


@pytest.fixture
def provider(token_store):
    return MsalTokenProvider(
        client_id="test-client-id",
        client_secret="test-client-secret",
        tenant_id="test-tenant-id",
        token_cache=token_store,
    )


def test_requires_complete_microsoft_configuration():
    with pytest.raises(ValueError, match="client ID"):
        MsalTokenProvider(
            client_id="",
            client_secret="secret",
            tenant_id="tenant",
            token_cache={},
        )

    with pytest.raises(ValueError, match="client ID"):
        MsalTokenProvider(
            client_id="client",
            client_secret="",
            tenant_id="tenant",
            token_cache={},
        )

    with pytest.raises(ValueError, match="client ID"):
        MsalTokenProvider(
            client_id="client",
            client_secret="secret",
            tenant_id="",
            token_cache={},
        )


def test_authority_uses_configured_tenant(provider):
    assert provider.authority == (
        "https://login.microsoftonline.com/test-tenant-id"
    )


def test_build_client_uses_confidential_client(provider, mocker):
    client_class = mocker.patch(
        "app.gateways.msal_auth.msal.ConfidentialClientApplication"
    )
    cache = MagicMock()

    provider._build_client(cache)

    client_class.assert_called_once_with(
        client_id="test-client-id",
        client_credential="test-client-secret",
        authority="https://login.microsoftonline.com/test-tenant-id",
        token_cache=cache,
    )


def test_get_access_token_returns_cached_delegated_token(provider, mocker):
    client = MagicMock()
    client.get_accounts.return_value = [{"home_account_id": "owner"}]
    client.acquire_token_silent.return_value = {
        "access_token": "graph-access-token"
    }

    mocker.patch.object(provider, "_build_client", return_value=client)
    mocker.patch.object(provider, "_save_cache")

    token = provider.get_access_token()

    assert token == "graph-access-token"
    client.acquire_token_silent.assert_called_once_with(
        scopes=GRAPH_SCOPES,
        account={"home_account_id": "owner"},
    )


def test_get_access_token_fails_when_no_account_exists(provider, mocker):
    client = MagicMock()
    client.get_accounts.return_value = []

    mocker.patch.object(provider, "_build_client", return_value=client)

    with pytest.raises(OutlookUnavailableError):
        provider.get_access_token()


def test_get_access_token_fails_when_silent_acquisition_fails(
    provider,
    mocker,
):
    client = MagicMock()
    client.get_accounts.return_value = [{"home_account_id": "owner"}]
    client.acquire_token_silent.return_value = {
        "error": "interaction_required"
    }

    mocker.patch.object(provider, "_build_client", return_value=client)

    with pytest.raises(OutlookUnavailableError):
        provider.get_access_token()


def test_initiate_auth_flow_returns_msal_flow(provider, mocker):
    client = MagicMock()
    flow = {
        "auth_uri": "https://login.microsoftonline.com/example",
        "state": "test-state",
    }
    client.initiate_auth_code_flow.return_value = flow

    mocker.patch.object(provider, "_build_client", return_value=client)

    result = provider.initiate_auth_flow(
        "http://localhost:5000/auth/callback"
    )

    assert result == flow
    client.initiate_auth_code_flow.assert_called_once_with(
        scopes=GRAPH_SCOPES,
        redirect_uri="http://localhost:5000/auth/callback",
    )


def test_initiate_auth_flow_fails_without_auth_uri(provider, mocker):
    client = MagicMock()
    client.initiate_auth_code_flow.return_value = {
        "error": "invalid_request"
    }

    mocker.patch.object(provider, "_build_client", return_value=client)

    with pytest.raises(OutlookUnavailableError):
        provider.initiate_auth_flow(
            "http://localhost:5000/auth/callback"
        )


def test_complete_auth_flow_returns_successful_result(provider, mocker):
    client = MagicMock()
    expected = {
        "access_token": "graph-access-token",
        "id_token_claims": {
            "name": "Owner",
        },
    }
    client.acquire_token_by_auth_code_flow.return_value = expected

    mocker.patch.object(provider, "_build_client", return_value=client)

    result = provider.complete_auth_flow(
        {"state": "expected-state"},
        {
            "code": "authorization-code",
            "state": "expected-state",
        },
    )

    assert result == expected


def test_complete_auth_flow_converts_validation_error(provider, mocker):
    client = MagicMock()
    client.acquire_token_by_auth_code_flow.side_effect = ValueError(
        "state mismatch"
    )

    mocker.patch.object(provider, "_build_client", return_value=client)

    with pytest.raises(OutlookUnavailableError):
        provider.complete_auth_flow(
            {"state": "expected-state"},
            {"state": "wrong-state"},
        )


def test_complete_auth_flow_fails_without_access_token(provider, mocker):
    client = MagicMock()
    client.acquire_token_by_auth_code_flow.return_value = {
        "error": "access_denied"
    }

    mocker.patch.object(provider, "_build_client", return_value=client)

    with pytest.raises(OutlookUnavailableError):
        provider.complete_auth_flow(
            {"state": "expected-state"},
            {"code": "authorization-code"},
        )


def test_load_cache_deserializes_existing_cache(provider, token_store, mocker):
    token_store["msal_token_cache"] = "serialized-cache"

    cache = MagicMock()
    cache_class = mocker.patch(
        "app.gateways.msal_auth.msal.SerializableTokenCache",
        return_value=cache,
    )

    result = provider._load_cache()

    assert result is cache
    cache_class.assert_called_once_with()
    cache.deserialize.assert_called_once_with("serialized-cache")


def test_save_cache_persists_changed_cache(provider, token_store):
    cache = MagicMock()
    cache.has_state_changed = True
    cache.serialize.return_value = "updated-cache"

    provider._save_cache(cache)

    assert token_store["msal_token_cache"] == "updated-cache"


def test_save_cache_ignores_unchanged_cache(provider, token_store):
    cache = MagicMock()
    cache.has_state_changed = False

    provider._save_cache(cache)

    assert "msal_token_cache" not in token_store
    cache.serialize.assert_not_called()
