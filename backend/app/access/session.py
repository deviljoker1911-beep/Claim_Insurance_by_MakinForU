"""The signed cookie that says which address a browser proved, and until when.

The cookie carries what it claims and a signature over it. Nothing in it is believed without
recomputing that signature with the server's secret, so a browser can read its own session but
cannot write one, extend one, or put someone else's address in it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config import get_settings

COOKIE_NAME = "claimai_access"


class SessionSecretMissing(RuntimeError):
    """The gate is on and no secret was configured to sign sessions with."""


def _secret() -> bytes:
    value = get_settings().access_session_secret.get_secret_value()
    if not value:
        # Signing with a default would mean anyone holding this source could mint a session.
        raise SessionSecretMissing(
            "ACCESS_GATE_ENABLED is on but ACCESS_SESSION_SECRET is empty. "
            "Set it to a long random value; every session is signed with it."
        )
    return value.encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> str:
    return _b64(hmac.new(_secret(), payload, hashlib.sha256).digest())


def session_cookie_value(email: str, *, now: float | None = None) -> str:
    """A session for this address, good for the configured number of days."""
    settings = get_settings()
    issued = int(now if now is not None else time.time())
    payload = json.dumps(
        {"email": email, "iat": issued, "exp": issued + settings.access_session_days * 86400},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"{_b64(payload)}.{_sign(payload)}"


def read_session(cookie: str | None, *, now: float | None = None) -> str | None:
    """The address this cookie proves, or None for anything that does not verify.

    Every failure is the same answer. A cookie that was edited, signed with another secret,
    truncated, or has run out of time is simply not a session.
    """
    if not cookie or "." not in cookie:
        return None
    encoded, _, signature = cookie.partition(".")
    try:
        payload = _unb64(encoded)
    except (ValueError, TypeError):
        return None
    try:
        expected = _sign(payload)
    except SessionSecretMissing:
        return None
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        claims = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(claims, dict):
        return None
    expires = claims.get("exp")
    email = claims.get("email")
    if not isinstance(expires, int) or not isinstance(email, str) or not email:
        return None
    if (now if now is not None else time.time()) >= expires:
        return None
    return email
