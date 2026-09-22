"""Who may use this deployment, and the address they proved to get in.

The demo is open to anyone who asks — the gate is not there to keep people out. It is there so
that a public URL with an open upload endpoint has a name attached to every session, and so the
people who came to look can be counted and contacted.

A visitor gives an address, receives a six-digit code, and types it back. The code is stored only
as a hash, expires, and is worth five attempts. The session that follows is a signed cookie
carrying the address and an expiry, which the server verifies on every request; nothing about it
is taken on trust from the browser.

Off by default. Local development, the test suite and an offline demo never see it.
"""

from app.access.codes import (
    CodeOutcome,
    issue_code,
    normalise_email,
    verify_code,
)
from app.access.mail import deliver_code, delivery_mode
from app.access.session import read_session, session_cookie_value

__all__ = [
    "CodeOutcome",
    "deliver_code",
    "delivery_mode",
    "issue_code",
    "normalise_email",
    "read_session",
    "session_cookie_value",
    "verify_code",
]
