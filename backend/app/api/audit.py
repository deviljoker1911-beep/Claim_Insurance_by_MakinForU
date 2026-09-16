"""Workspace-wide audit trail."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AuditEvent
from app.schemas import AuditEventOut

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditEventOut])
def audit_events(
    event_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    session: Session = Depends(get_session),
) -> list[AuditEvent]:
    """Most recent events first."""
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    return list(session.scalars(query))
