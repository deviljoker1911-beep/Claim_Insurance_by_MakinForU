"""Claim creation and lookup."""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.access.scope import current_owner, is_scoped
from app.audit import record_event
from app.config import get_settings
from app.models import AuditEvent, Claim, Document
from app.schemas import ClaimCreate
from app.services.numbering import allocate_claim_number


def create_claim(session: Session, data: ClaimCreate, actor: str | None = None) -> Claim:
    actor = actor or get_settings().operator_name
    try:
        claim_number = allocate_claim_number(session)
        claim = Claim(
            owner=current_owner(),
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


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def get_claim_or_404(session: Session, claim_id: str) -> Claim:
    """The claim, if it is this request's to see.

    Every route that takes a claim id comes through here, which is what makes one check enough.
    Someone else's claim answers exactly as a claim that was never created does — a 404 rather
    than a 403, because "you may not see this" still says the claim exists.
    """
    # IDs are UUIDs; anything else (including NUL bytes PostgreSQL would reject) cannot exist.
    claim = session.get(Claim, claim_id) if is_uuid(claim_id) else None
    if claim is None or claim.owner != current_owner():
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


def mine_or_404(session: Session, obj, label: str):
    """Return obj if the claim it hangs off is this request's, else 404.

    Documents, findings and questions are addressed by their own ids, not their claim's, so
    they never pass through get_claim_or_404. A uuid nobody can guess is not the same as a
    check, and a page image of someone else's uploaded document is exactly what must not be
    served. Same answer as a thing that does not exist, for the same reason.
    """
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    owner = session.scalar(select(Claim.owner).where(Claim.id == obj.claim_id))
    if owner is None or owner != current_owner():
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return obj


def visible_audit(query):
    """Narrow an audit query to what this request is entitled to see.

    Unscoped, that is everything, exactly as before. Scoped, it is this workspace's claims —
    plus the events that belong to no claim at all. Those are the workspace's own: a reset, a
    restart, documents requeued after one. Dropping them was a mistake worth naming: an audit
    trail that quietly omits whole classes of event is worse than one that is not filtered,
    because it still looks complete.
    """
    if not is_scoped():
        return query
    return query.where(
        or_(
            AuditEvent.claim_id.is_(None),
            AuditEvent.claim_id.in_(select(Claim.id).where(Claim.owner == current_owner())),
        )
    )


def list_claims_with_counts(session: Session) -> list[tuple[Claim, int]]:
    document_count = (
        select(Document.claim_id, func.count(Document.id).label("n")).group_by(Document.claim_id).subquery()
    )
    rows = session.execute(
        select(Claim, func.coalesce(document_count.c.n, 0))
        .outerjoin(document_count, document_count.c.claim_id == Claim.id)
        .where(Claim.owner == current_owner())
        .order_by(Claim.updated_at.desc(), Claim.claim_number.desc())
    ).all()
    return [(claim, count) for claim, count in rows]
