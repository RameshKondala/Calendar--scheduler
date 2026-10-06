"""Microsoft sign-in routes for owner access (completes the wiring that
``MsalTokenProvider`` set up but nothing previously called).

This is the piece that was missing: the provider could build an
authorization URL and complete the code exchange, but no route ever drove
that flow, so ``OUTLOOK_GATEWAY=graph`` had no way to ever populate a
token -- every real Graph call would have failed with
``OUTLOOK_UNAVAILABLE`` since ``client.get_accounts()`` would always be
empty. ``/auth/microsoft/login`` and ``/auth/microsoft/callback`` close
that gap.

A successful sign-in also satisfies the *application's own* owner
authorization (``require_owner``), gated by ``OWNER_ALLOWED_UPNS`` --
being a valid Microsoft identity is necessary but not sufficient; the
signed-in account's username must also be on that allow-list, which is
the "role configuration" half of Week 4 section 4.2.
"""
from __future__ import annotations

from flask import Blueprint, current_app, redirect, request, session, url_for

from app.errors.handlers import OutlookUnavailableError

microsoft_auth_bp = Blueprint("microsoft_auth", __name__)

_FLOW_SESSION_KEY = "ms_auth_flow"


def _token_provider():
    provider = current_app.extensions.get("msal_token_provider")
    if provider is None:
        # Microsoft sign-in only means anything when GraphOutlookGateway is
        # actually in use; with the fake gateway there is no real calendar
        # to sign in for.
        raise OutlookUnavailableError(
            "Microsoft sign-in is only available when OUTLOOK_GATEWAY=graph."
        )
    return provider


@microsoft_auth_bp.get("/auth/microsoft/login")
def login():
    redirect_uri = url_for("microsoft_auth.callback", _external=True)
    flow = _token_provider().initiate_auth_flow(redirect_uri)
    session[_FLOW_SESSION_KEY] = flow
    return redirect(flow["auth_uri"])


@microsoft_auth_bp.get("/auth/microsoft/callback")
def callback():
    flow = session.pop(_FLOW_SESSION_KEY, None)
    if not flow:
        # No flow in session: a stale/replayed callback, or one that
        # arrived at a different process than where it started. Either
        # way there's nothing to complete -- send them to try again.
        return redirect(url_for("frontend.owner_page", auth="expired"))

    result = _token_provider().complete_auth_flow(flow, request.args)

    claims = result.get("id_token_claims") or {}
    upn = (claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
    allowed = current_app.config.get("OWNER_ALLOWED_UPNS", frozenset())

    if not upn or upn not in allowed:
        # This is a real, successfully authenticated Microsoft identity --
        # just not one on the owner allow-list. A full-page redirect with a
        # friendly state (rather than raising ForbiddenError's raw JSON
        # body) fits this being a browser navigation, not a fetch() call;
        # require_owner still raises ForbiddenError for the API-call case
        # (e.g. a UPN removed from the allow-list after signing in).
        return redirect(url_for("frontend.owner_page", auth="forbidden"))

    session["owner_upn"] = upn
    return redirect(url_for("frontend.owner_page", auth="success"))


@microsoft_auth_bp.post("/auth/microsoft/logout")
def logout():
    session.pop("owner_upn", None)
    session.pop(_FLOW_SESSION_KEY, None)
    return "", 204
