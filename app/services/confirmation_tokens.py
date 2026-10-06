"""Signed confirmation tokens for guest access to their own booking.

``GET /appointments/{id}`` is otherwise open to anyone who knows the
Outlook event id (Week 4 section 3.3 calls for "guest token or owner"
auth). This issues a stateless, signed token tying one guest to the one
event id they just booked, using the same signing key as the Flask
session (``SECRET_KEY``) via ``itsdangerous`` (already a Flask
dependency, so no new package is needed). No server-side storage is
required: verification just checks the signature and that the token was
issued for the event id being requested.
"""
from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer

_SALT = "appointment-confirmation-token"


def _serializer(secret_key: str) -> URLSafeSerializer:
    return URLSafeSerializer(secret_key, salt=_SALT)


def issue(secret_key: str, outlook_event_id: str) -> str:
    """Create a token a guest can use to look up this one appointment."""
    return _serializer(secret_key).dumps(outlook_event_id)


def verify(secret_key: str, token: str, outlook_event_id: str) -> bool:
    """True if ``token`` was issued for exactly ``outlook_event_id``."""
    if not token:
        return False
    try:
        return _serializer(secret_key).loads(token) == outlook_event_id
    except BadSignature:
        return False
