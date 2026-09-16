"""Claim creation and retrieval."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AuditEvent
from app.schemas import AuditEventOut, ClaimCreate, ClaimDetail, ClaimOut, DocumentOut
from app.services.claims import create_claim, get_claim_or_404, list_claims_with_counts
from app.services.locks import WORKSPACE_LOCK

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("", response_model=list[ClaimOut])
def list_claims(session: Session = Depends(get_session)) -> list[ClaimOut]:
    with WORKSPACE_LOCK.shared():
        return [
            ClaimOut.model_validate(claim).model_copy(update={"document_count": count})
            for claim, count in list_claims_with_counts(session)
        ]


@router.post("", response_model=ClaimOut, status_code=201)
def create(payload: ClaimCreate, session: Session = Depends(get_session)) -> ClaimOut:
    with WORKSPACE_LOCK.shared():
        return ClaimOut.model_validate(create_claim(session, payload))


@router.get("/{claim_id}", response_model=ClaimDetail)
def get_claim(claim_id: str, session: Session = Depends(get_session)) -> ClaimDetail:
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        documents = [DocumentOut.model_validate(document) for document in claim.documents]
        summary = ClaimOut.model_validate(claim).model_dump(exclude={"document_count"})
        return ClaimDetail(**summary, document_count=len(documents), documents=documents)


@router.get("/{claim_id}/audit", response_model=list[AuditEventOut])
def claim_audit_trail(claim_id: str, session: Session = Depends(get_session)) -> list[AuditEventOut]:
    with WORKSPACE_LOCK.shared():
        get_claim_or_404(session, claim_id)
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.claim_id == claim_id).order_by(AuditEvent.created_at, AuditEvent.id)
        )
        return [AuditEventOut.model_validate(event) for event in events]
