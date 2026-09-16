"""Claim creation and lookup."""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.config import get_settings
from app.models import Claim, Document
from app.schemas import ClaimCreate
from app.services.numbering import allocate_claim_number


def create_claim(session: Session, data: ClaimCreate, actor: str | None = None) -> Claim:
    actor = actor or get_settings().operator_name
    try:
        claim_number = allocate_claim_number(session)
        claim = Claim(
            claim_number=claim_number,
            patient_name=data.patient_name,
            uhid=data.uhid,
            hospital=data.hospital,
            insurer=data.insurer,
            tpa=data.tpa,
            admission_date=data.admission_date,
            discharge_date=data.discharge_date,
            status="draft",
            is_demo=data.is_demo,
            created_by=actor,
        )
        session.add(claim)
        session.flush()
        record_event(
            session,
            "claim_created",
            f"Claim {claim_number} created for {data.patient_name}",
            claim_id=claim.id,
            actor=actor,
            details={"claim_number": claim_number, "is_demo": data.is_demo},
        )
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return claim


def get_claim_or_404(session: Session, claim_id: str) -> Claim:
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


def list_claims_with_counts(session: Session) -> list[tuple[Claim, int]]:
    document_count = (
        select(Document.claim_id, func.count(Document.id).label("n")).group_by(Document.claim_id).subquery()
    )
    rows = session.execute(
        select(Claim, func.coalesce(document_count.c.n, 0))
        .outerjoin(document_count, document_count.c.claim_id == Claim.id)
        .order_by(Claim.updated_at.desc(), Claim.claim_number.desc())
    ).all()
    return [(claim, count) for claim, count in rows]
