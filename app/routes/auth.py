"""Owner authorization: real Microsoft sign-in, or a dev/CI bearer token.

Week 4 section 4.2 calls for authorization "based on Microsoft
identity/role configuration". Two paths satisfy ``require_owner``:

1. **Microsoft sign-in (the real path).** ``/auth/microsoft/login``
   (``app/routes/microsoft_auth.py``) drives an MSAL authorization-code
   flow; on success it stores the signed-in user's work/school username
   (UPN) in the Flask session, already checked once against
   ``OWNER_ALLOWED_UPNS``. This only works when ``OUTLOOK_GATEWAY=graph``
   (it needs ``MsalTokenProvider``), since Microsoft sign-in has no
   purpose if there's no Microsoft calendar behind it.
2. **A shared bearer token (``OWNER_ACCESS_TOKEN``), for local dev and CI**
   where standing up a real Entra tenant is impractical. This is
   explicitly a shortcut, not identity -- anyone with the token passes.

Either is accepted; routes do not need to know which one was used.
"""
from __future__ import annotations

import hmac
from functools import wraps

from flask import current_app, request, session

from app.errors.handlers import ForbiddenError, UnauthorizedError


def _bearer_token_is_valid() -> bool:
    expected = current_app.config.get("OWNER_ACCESS_TOKEN")
    if not expected:
        return False
    token = request.headers.get("Authorization", "")
    # hmac.compare_digest avoids leaking token length/prefix information
    # via response-timing differences.
    return hmac.compare_digest(token, f"Bearer {expected}")


def _microsoft_session_upn() -> str | None:
    """The signed-in owner's UPN, if any -- present only after a real
    Microsoft sign-in via /auth/microsoft/login completed successfully."""
    return session.get("owner_upn")


def is_owner_request() -> bool:
    """True if this request carries either accepted owner credential.

    Re-checks the allow-list on every request (not just at sign-in time)
    so revoking a UPN from ``OWNER_ALLOWED_UPNS`` takes effect immediately
    for anyone already signed in, without needing to also invalidate
    sessions.
    """
    if _bearer_token_is_valid():
        return True
    upn = _microsoft_session_upn()
    return upn is not None and upn in current_app.config.get("OWNER_ALLOWED_UPNS", frozenset())


def require_owner(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if is_owner_request():
            return view_func(*args, **kwargs)

        # A signed-in Microsoft identity that fell off the allow-list is a
        # real, authenticated principal being denied a permission, which is
        # 403 Forbidden -- distinct from having no credential at all (401).
        if _microsoft_session_upn() is not None:
            raise ForbiddenError("This Microsoft account is not authorized for owner access.")
        raise UnauthorizedError("Owner authentication is required for this endpoint.")

    return wrapper
