"""The access gate: ask for a code, prove the address, and read who has been in."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import codes as code_service
from app.access import mail
from app.access.session import COOKIE_NAME, read_session, session_cookie_value
from app.config import get_settings
from app.db import get_session
from app.models import Visitor
from app.schemas import (
    AccessRequestIn,
    AccessRequestResult,
    AccessSession,
    AccessVerifyIn,
    VisitorOut,
)

logger = logging.getLogger("claimai.access")

router = APIRouter(prefix="/access", tags=["access"])


def caller_ip(request: Request) -> str | None:
    """The caller, trusting a proxy header only as far as its first hop."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64] or None
    return request.client.host[:64] if request.client else None


def _over_https(request: Request) -> bool:
    """Whether the visitor's own connection was encrypted.

    The proxy terminates TLS and talks plain http to this process, so the request as seen here
    says nothing about how it arrived. The forwarded header is what carries that.
    """
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return (forwarded or request.url.scheme) == "https"


def _cookie(response: Response, request: Request, email: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        session_cookie_value(email),
        max_age=get_settings().access_session_days * 86400,
        httponly=True,
        samesite="lax",
        # Marked Secure exactly when the visitor is on https. Setting it on a plain-http
        # deployment would be worse than useless: the browser would take the cookie and never
        # send it back, and the gate would ask for a code again on every page.
        secure=_over_https(request),
        path="/",
    )


@router.get("/session", response_model=AccessSession)
def current_session(request: Request) -> AccessSession:
    """Whether this deployment asks for an address, and whether this browser has given one."""
    settings = get_settings()
    if not settings.access_gate_enabled:
        return AccessSession(gate_enabled=False, verified=True, email=None, delivery=mail.delivery_mode())
    email = read_session(request.cookies.get(COOKIE_NAME))
    return AccessSession(
        gate_enabled=True,
        verified=email is not None,
        email=email,
        delivery=mail.delivery_mode(),
    )


@router.post("/request", response_model=AccessRequestResult)
def request_code(
    payload: AccessRequestIn,
    request: Request,
    session: Session = Depends(get_session),
) -> AccessRequestResult:
    """Send a code to an address. Answers the same way whether or not it has been seen before."""
    email = code_service.normalise_email(payload.email)
    if email is None:
        raise HTTPException(status_code=422, detail={"message": "That does not look like an email address."})

    code, outcome = code_service.issue_code(
        session,
        email,
        ip=caller_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if not outcome.ok:
        raise HTTPException(status_code=429, detail={"message": outcome.message, "reason": outcome.reason})

    try:
        delivery = mail.deliver_code(email, code)
    except Exception as exc:  # noqa: BLE001 — a mail server that is down is told to the caller, not hidden
        logger.exception("Could not send the access code to %s", email)
        raise HTTPException(
            status_code=502,
            detail={"message": "The code could not be sent. Try again, or tell whoever runs this demo."},
        ) from exc

    return AccessRequestResult(
        sent=True,
        delivery=delivery,
        expires_in_minutes=get_settings().access_code_ttl_minutes,
        message=(
            f"A code is on its way to {email}."
            if delivery == mail.MAILED
            else "No mail server is configured here, so the code was written to the server log."
        ),
    )


@router.post("/verify", response_model=AccessSession)
def verify(
    payload: AccessVerifyIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> AccessSession:
    """Exchange a code for a session."""
    email = code_service.normalise_email(payload.email)
    if email is None:
        raise HTTPException(status_code=422, detail={"message": "That does not look like an email address."})

    outcome = code_service.verify_code(session, email, payload.code)
    if not outcome.ok:
        raise HTTPException(status_code=401, detail={"message": outcome.message, "reason": outcome.reason})

    _cookie(response, request, email)
    return AccessSession(gate_enabled=True, verified=True, email=email, delivery=mail.delivery_mode())


@router.post("/signout", response_model=AccessSession)
def signout(response: Response) -> AccessSession:
    response.delete_cookie(COOKIE_NAME, path="/")
    settings = get_settings()
    return AccessSession(
        gate_enabled=settings.access_gate_enabled,
        verified=not settings.access_gate_enabled,
        email=None,
        delivery=mail.delivery_mode(),
    )


@router.get("/visitors", response_model=list[VisitorOut])
def visitors(
    x_admin_token: str = Header(default=""),
    session: Session = Depends(get_session),
) -> list[VisitorOut]:
    """Everyone who asked for access, newest first. Served only to a configured token."""
    configured = get_settings().access_admin_token.get_secret_value()
    if not configured:
        raise HTTPException(
            status_code=404,
            detail={"message": "No visitor list is served: ACCESS_ADMIN_TOKEN is not set."},
        )
    if not x_admin_token or x_admin_token != configured:
        raise HTTPException(status_code=401, detail={"message": "That token is not right."})

    rows = session.scalars(select(Visitor).order_by(Visitor.first_seen_at.desc())).all()
    return [
        VisitorOut(
            email=row.email,
            verified=row.is_verified,
            requests=row.requests or 0,
            first_seen_at=row.first_seen_at,
            verified_at=row.verified_at,
            last_seen_at=row.last_seen_at,
        )
        for row in rows
    ]
