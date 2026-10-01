"""Microsoft Entra / MSAL delegated authentication for Microsoft Graph."""

from __future__ import annotations

from collections.abc import MutableMapping

import msal

from app.errors.handlers import OutlookUnavailableError


GRAPH_SCOPES = ["Calendars.ReadWrite"]


class MsalTokenProvider:
    """Provide delegated Microsoft Graph access tokens through MSAL.

    The Flask application is a confidential client. The owner completes
    an authorization-code flow, and subsequent Graph requests acquire
    delegated tokens silently from the MSAL token cache.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        token_cache: MutableMapping,
    ) -> None:
        if not client_id or not client_secret or not tenant_id:
            raise ValueError(
                "Microsoft Graph client ID, client secret, and tenant ID "
                "are required"
            )

        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.token_cache = token_cache

    @property
    def authority(self) -> str:
        """Return the Microsoft identity authority for this tenant."""

        return f"https://login.microsoftonline.com/{self.tenant_id}"

    def _load_cache(self) -> msal.SerializableTokenCache:
        """Load the serialized MSAL cache from the backing mapping."""

        cache = msal.SerializableTokenCache()

        serialized = self.token_cache.get("msal_token_cache")
        if serialized:
            cache.deserialize(serialized)

        return cache

    def _save_cache(self, cache: msal.SerializableTokenCache) -> None:
        """Persist the MSAL cache when MSAL reports that it changed."""

        if cache.has_state_changed:
            self.token_cache["msal_token_cache"] = cache.serialize()

    def _build_client(
        self,
        cache: msal.SerializableTokenCache,
    ) -> msal.ConfidentialClientApplication:
        """Build the confidential MSAL client used by the Flask app."""

        return msal.ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=self.authority,
            token_cache=cache,
        )

    def get_access_token(self) -> str:
        """Return a delegated Graph access token from the MSAL cache."""

        cache = self._load_cache()
        client = self._build_client(cache)

        accounts = client.get_accounts()
        if not accounts:
            raise OutlookUnavailableError()

        result = client.acquire_token_silent(
            scopes=GRAPH_SCOPES,
            account=accounts[0],
        )

        self._save_cache(cache)

        if not result or not result.get("access_token"):
            raise OutlookUnavailableError()

        return result["access_token"]

    def initiate_auth_flow(self, redirect_uri: str) -> dict:
        """Create an authorization-code flow for Microsoft sign-in."""

        cache = self._load_cache()
        client = self._build_client(cache)

        flow = client.initiate_auth_code_flow(
            scopes=GRAPH_SCOPES,
            redirect_uri=redirect_uri,
        )

        self._save_cache(cache)

        if "auth_uri" not in flow:
            raise OutlookUnavailableError()

        return flow

    def complete_auth_flow(
        self,
        flow: dict,
        auth_response: dict,
    ) -> dict:
        """Complete a previously initiated authorization-code flow."""

        cache = self._load_cache()
        client = self._build_client(cache)

        try:
            result = client.acquire_token_by_auth_code_flow(
                flow,
                auth_response,
            )
        except ValueError as exc:
            raise OutlookUnavailableError() from exc

        self._save_cache(cache)

        if "access_token" not in result:
            raise OutlookUnavailableError()

        return result
