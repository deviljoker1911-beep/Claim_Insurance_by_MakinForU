"""Audit trail helpers."""

from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditEvent


def record_event(
    session: Session,
    event_type: str,
    message: str,
    *,
    claim_id: str | None = None,
    document_id: str | None = None,
    actor: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to the session. The caller commits it with its own changes."""
    event = AuditEvent(
        claim_id=claim_id,
        document_id=document_id,
        event_type=event_type,
        actor=actor or get_settings().operator_name,
        message=message[:500],
        details=details or {},
    )
    session.add(event)
    return event
