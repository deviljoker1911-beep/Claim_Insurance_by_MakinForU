"""Workspace-wide audit trail."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.claims import visible_audit
from app.db import get_session
from app.models import AuditEvent
from app.schemas import AuditEventOut
from app.services.locks import WORKSPACE_LOCK

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditEventOut])
def audit_events(
    event_type: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z_]+$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    session: Session = Depends(get_session),
) -> list[AuditEventOut]:
    """Most recent events first."""
    # Scoped to the caller's own claims: an audit trail that showed everybody's would hand
    # one visitor the patient names and claim numbers of every other.
    query = visible_audit(
        select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    ).limit(limit)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    with WORKSPACE_LOCK.shared():
        return [AuditEventOut.model_validate(event) for event in session.scalars(query)]
