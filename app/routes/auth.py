"""Minimal owner authorization check.

Week 4 assigns real owner authentication to Microsoft identity (section
4.2: "Authorization is based on Microsoft identity/role configuration").
That MSAL/Entra wiring belongs with Jose's Outlook integration. This
module provides a header-based stand-in behind the same call shape
(``require_owner``) so routes do not need to change when the real
implementation lands.
"""
from __future__ import annotations

from functools import wraps

from flask import current_app, request

from app.errors.handlers import UnauthorizedError


def require_owner(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization", "")
        expected = current_app.config.get("OWNER_ACCESS_TOKEN")
        if not expected or token != f"Bearer {expected}":
            raise UnauthorizedError("Owner authentication is required for this endpoint.")
        return view_func(*args, **kwargs)

    return wrapper
