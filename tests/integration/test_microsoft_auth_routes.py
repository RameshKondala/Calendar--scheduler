"""Tests for /auth/microsoft/{login,callback,logout}.

These close the gap Jose's MsalTokenProvider left open: the provider
could build an authorization URL and complete a code exchange, but
nothing ever called it. As with Jose's own MSAL tests, the MSAL client
itself is mocked -- there is no live Azure tenant in CI -- so this
verifies the routes drive the flow correctly and gate owner access on
the result, not that Microsoft's servers behave as MSAL expects.
"""
from unittest.mock import patch

import pytest

from app import create_app
from config import TestingConfig


class GraphConfig(TestingConfig):
    OUTLOOK_GATEWAY = "graph"
    MS_GRAPH_CLIENT_ID = "test-client-id"
    MS_GRAPH_CLIENT_SECRET = "test-client-secret"
    MS_GRAPH_TENANT_ID = "test-tenant-id"
    MS_GRAPH_CALENDAR_ID = "test-calendar-id"
    OWNER_ALLOWED_UPNS = frozenset({"owner@example.com"})


@pytest.fixture
def graph_app():
    return create_app(config_object=GraphConfig)


@pytest.fixture
def graph_client(graph_app):
    return graph_app.test_client()


def _sign_in(graph_client, provider, upn):
    with graph_client.session_transaction() as sess:
        sess["ms_auth_flow"] = {"state": "abc"}
    with patch.object(
        provider, "complete_auth_flow",
        return_value={"access_token": "tok", "id_token_claims": {"preferred_username": upn}},
    ):
        return graph_client.get("/auth/microsoft/callback?code=abc&state=abc", follow_redirects=False)


def test_login_redirects_to_the_microsoft_authorization_url(graph_app, graph_client):
    provider = graph_app.extensions["msal_token_provider"]
    fake_flow = {"auth_uri": "https://login.microsoftonline.com/fake-auth", "state": "abc"}
    with patch.object(provider, "initiate_auth_flow", return_value=fake_flow):
        resp = graph_client.get("/auth/microsoft/login", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://login.microsoftonline.com/fake-auth"
    with graph_client.session_transaction() as sess:
        assert sess["ms_auth_flow"] == fake_flow


def test_login_fails_clearly_when_not_using_the_graph_gateway(client):
    """With OUTLOOK_GATEWAY=fake there is no Microsoft calendar to sign in
    for, so this must fail loudly rather than pretend to work."""
    resp = client.get("/auth/microsoft/login")
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "OUTLOOK_UNAVAILABLE"


def test_callback_with_an_allowed_upn_signs_in_and_redirects_to_owner_page(graph_app, graph_client):
    resp = _sign_in(graph_client, graph_app.extensions["msal_token_provider"], "Owner@Example.com")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/owner?auth=success")
    with graph_client.session_transaction() as sess:
        assert sess["owner_upn"] == "owner@example.com"  # normalized to lowercase


def test_callback_with_a_disallowed_upn_redirects_without_signing_in(graph_app, graph_client):
    resp = _sign_in(graph_client, graph_app.extensions["msal_token_provider"], "intruder@example.com")

    assert resp.status_code == 302
    assert "auth=forbidden" in resp.headers["Location"]
    with graph_client.session_transaction() as sess:
        assert "owner_upn" not in sess


def test_callback_with_no_pending_flow_redirects_to_owner_page_expired(graph_client):
    resp = graph_client.get("/auth/microsoft/callback", follow_redirects=False)
    assert resp.status_code == 302
    assert "auth=expired" in resp.headers["Location"]


def test_signed_in_session_satisfies_owner_only_endpoints(graph_app, graph_client):
    _sign_in(graph_client, graph_app.extensions["msal_token_provider"], "owner@example.com")

    resp = graph_client.get(
        "/api/v1/owner/appointments?date_from=2026-09-21T00:00:00&date_to=2026-09-22T00:00:00"
    )
    # The real Graph HTTP call isn't mocked here and will fail offline
    # (-> 503), but it must get *past* authorization, i.e. never 401/403.
    assert resp.status_code not in (401, 403)


def test_signed_in_session_rejected_once_removed_from_the_allow_list(graph_app, graph_client):
    """Revoking a UPN takes effect immediately for an existing session,
    without needing to also invalidate it server-side."""
    _sign_in(graph_client, graph_app.extensions["msal_token_provider"], "owner@example.com")
    graph_app.config["OWNER_ALLOWED_UPNS"] = frozenset()

    resp = graph_client.get(
        "/api/v1/owner/appointments?date_from=2026-09-21T00:00:00&date_to=2026-09-22T00:00:00"
    )
    assert resp.status_code == 403


def test_logout_clears_the_session(graph_client):
    with graph_client.session_transaction() as sess:
        sess["owner_upn"] = "owner@example.com"

    resp = graph_client.post("/auth/microsoft/logout")

    assert resp.status_code == 204
    with graph_client.session_transaction() as sess:
        assert "owner_upn" not in sess
