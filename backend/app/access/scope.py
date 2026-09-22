"""Whose claims a request is allowed to see.

On a deployment with the gate on, two people looking at the demo at the same time should not
find each other's claims in the list, or each other's patients on the dashboard. Each verified
address gets its own workspace: its own claims, its own numbering from CLM-2026-00123, and its
own reset.

The owner is carried in a context variable set once per request, rather than threaded through
ten routers as an argument. That is deliberate. Scoping enforced in one place cannot be
forgotten when a route is added; scoping passed by hand is one missed parameter away from a
claim belonging to someone else.

With the gate off — local development, the test suite, an offline demo — every request carries
the same empty owner, which is one shared workspace and exactly how it behaved before.
"""

from __future__ import annotations

from contextvars import ContextVar

# "" is the single shared workspace: no gate, so no one to tell apart.
SHARED = ""

_owner: ContextVar[str] = ContextVar("claim_owner", default=SHARED)


def set_owner(email: str | None) -> object:
    """Bind this request to an address. Returns the token to reset it with."""
    return _owner.set((email or SHARED).strip().lower())


def reset_owner(token: object) -> None:
    _owner.reset(token)  # type: ignore[arg-type]


def current_owner() -> str:
    """The address this request belongs to, or SHARED when nothing is gating it."""
    return _owner.get()


def is_scoped() -> bool:
    """Whether claims are being kept apart at all."""
    return current_owner() != SHARED
