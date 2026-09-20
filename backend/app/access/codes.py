"""Issuing an access code, and deciding whether the one typed back is right.

Two limits matter here and neither is about the demo. An endpoint that sends mail to any address
handed to it is a way to send mail in someone else's name, so the number of codes one address and
one caller may ask for is capped. And a six-digit code is guessable if you may guess forever, so
each one is worth a small number of attempts and then it is spent.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AccessChallenge, Visitor, utcnow

logger = logging.getLogger("claimai.access")

CODE_LENGTH = 6


def _utc(value: datetime) -> datetime:
    """SQLite gives back what it was given, without the timezone. Postgres keeps it."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class CodeOutcome:
    """What happened, in terms the API can answer with and a person can act on."""

    ok: bool
    reason: str = ""
    message: str = ""


def normalise_email(raw: str) -> str | None:
    """The address as it will be stored, or None if it is not one.

    Deliberately permissive: this is a demo gate, and the real test of an address is whether a
    code sent to it arrives. It rejects what cannot be an address rather than trying to judge
    what can.
    """
    email = (raw or "").strip().lower()
    if not email or len(email) > 320 or " " in email:
        return None
    local, at, domain = email.partition("@")
    if not at or not local or not domain:
        return None
    if "." not in domain or domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return None
    return email


def _hash(code: str, email: str) -> str:
    """Bound to the address, so a code issued for one cannot be replayed against another."""
    return hashlib.sha256(f"{email}:{code}".encode()).hexdigest()


def _recent(session: Session, *, email: str | None = None, ip: str | None = None) -> int:
    since = utcnow() - timedelta(hours=1)
    query = select(func.count()).select_from(AccessChallenge).where(AccessChallenge.created_at >= since)
    if email is not None:
        query = query.where(AccessChallenge.email == email)
    if ip is not None:
        query = query.where(AccessChallenge.requested_ip == ip)
    return session.scalar(query) or 0


def issue_code(session: Session, email: str, *, ip: str | None, user_agent: str | None) -> tuple[str | None, CodeOutcome]:
    """Record the request and return the code to send, or say why it was not issued."""
    settings = get_settings()

    if _recent(session, email=email) >= settings.access_requests_per_email_per_hour:
        return None, CodeOutcome(
            False,
            "too_many_for_email",
            "That address has asked for several codes already. Try again in an hour.",
        )
    if ip and _recent(session, ip=ip) >= settings.access_requests_per_ip_per_hour:
        return None, CodeOutcome(
            False,
            "too_many_for_caller",
            "Too many codes have been requested from here. Try again in an hour.",
        )

    visitor = session.scalar(select(Visitor).where(Visitor.email == email))
    if visitor is None:
        visitor = Visitor(email=email)
        session.add(visitor)
    visitor.requests = (visitor.requests or 0) + 1
    visitor.last_user_agent = (user_agent or "")[:400] or None

    # An address asking again replaces what it was sent: only the newest code can be used.
    for stale in session.scalars(
        select(AccessChallenge).where(AccessChallenge.email == email, AccessChallenge.used_at.is_(None))
    ):
        stale.used_at = utcnow()

    code = f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"
    session.add(
        AccessChallenge(
            email=email,
            code_hash=_hash(code, email),
            expires_at=utcnow() + timedelta(minutes=settings.access_code_ttl_minutes),
            requested_ip=(ip or "")[:64] or None,
        )
    )
    session.commit()
    return code, CodeOutcome(True)


def verify_code(session: Session, email: str, code: str) -> CodeOutcome:
    """Check a typed code against the one outstanding for this address."""
    settings = get_settings()
    typed = (code or "").strip().replace(" ", "").replace("-", "")

    challenge = session.scalars(
        select(AccessChallenge)
        .where(AccessChallenge.email == email, AccessChallenge.used_at.is_(None))
        .order_by(AccessChallenge.created_at.desc())
    ).first()
    if challenge is None:
        return CodeOutcome(False, "no_code", "Ask for a code first — there is none outstanding for that address.")
    if utcnow() >= _utc(challenge.expires_at):
        challenge.used_at = utcnow()
        session.commit()
        return CodeOutcome(False, "expired", "That code has expired. Ask for another one.")
    if challenge.attempts >= settings.access_code_max_attempts:
        challenge.used_at = utcnow()
        session.commit()
        return CodeOutcome(False, "too_many_attempts", "Too many tries for that code. Ask for another one.")

    challenge.attempts += 1
    if not hmac.compare_digest(challenge.code_hash, _hash(typed, email)):
        remaining = settings.access_code_max_attempts - challenge.attempts
        session.commit()
        if remaining <= 0:
            return CodeOutcome(False, "too_many_attempts", "Too many tries for that code. Ask for another one.")
        return CodeOutcome(
            False,
            "wrong_code",
            f"That code is not right. {remaining} {'try' if remaining == 1 else 'tries'} left.",
        )

    challenge.used_at = utcnow()
    visitor = session.scalar(select(Visitor).where(Visitor.email == email))
    if visitor is None:
        visitor = Visitor(email=email)
        session.add(visitor)
    now = utcnow()
    if visitor.verified_at is None:
        visitor.verified_at = now
    visitor.last_seen_at = now
    session.commit()
    logger.info("Access granted to %s", email)
    return CodeOutcome(True)


def touch(session: Session, email: str) -> None:
    """Note that a verified address is still using the demo."""
    visitor = session.scalar(select(Visitor).where(Visitor.email == email))
    if visitor is not None:
        visitor.last_seen_at = utcnow()
        session.commit()
