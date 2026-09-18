"""Human review: the one decision in this system that only a person makes.

Nothing here is automatic. The readiness engine says whether the documentation is still waiting
for something; approving the claim is an action a named operator takes, and it is refused while
anything is outstanding. Approval records who approved it, when, and what the documentation
looked like at that moment — and it never changes the score.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.audit import record_event
from app.models import REVIEW_APPROVED, REVIEW_DRAFT, Claim, utcnow
from app.readiness import engine as readiness_engine

logger = logging.getLogger("claimai.review")


class ApprovalNotAllowed(RuntimeError):
    """The claim cannot be approved in its current state."""

    def __init__(self, message: str, *, status: int = 409, readiness: dict | None = None):
        super().__init__(message)
        self.status = status
        self.readiness = readiness


def note_ready_for_review(session: Session, claim: Claim, readiness: dict) -> None:
    """Record, once, that the documentation reached the point where a person can review it."""
    if claim.review_started_at is not None or readiness["status"] != readiness_engine.READY_FOR_HUMAN_REVIEW:
        return
    claim.review_started_at = utcnow()
    record_event(
        session,
        "human_review_started",
        "Documentation is ready for human review",
        claim_id=claim.id,
        actor="system",
        details={
            "score": readiness["score"],
            "status": readiness["status"],
            "counted_findings": readiness["summary"]["counted_findings"],
        },
    )
    session.commit()


def approve(session: Session, claim: Claim, readiness: dict, *, actor: str, note: str | None = None) -> Claim:
    """Approve a claim. Only a person reaches this, and only for a claim that is ready."""
    if claim.review_state == REVIEW_APPROVED:
        raise ApprovalNotAllowed(
            f"{claim.claim_number} was already approved by {claim.approved_by}.", readiness=readiness
        )
    if readiness["status"] != readiness_engine.READY_FOR_HUMAN_REVIEW:
        raise ApprovalNotAllowed(
            (
                f"{claim.claim_number} is {readiness_engine.STATUS_LABELS[readiness['status']].lower()} "
                f"({readiness['score']}%). Approval is offered once the documentation is ready for review."
            ),
            status=422,
            readiness=readiness,
        )

    claim.review_state = REVIEW_APPROVED
    claim.approved_by = actor
    claim.approved_at = utcnow()
    claim.approval_note = (note or "").strip()[:500] or None
    claim.approved_readiness = {
        "score": readiness["score"],
        "status": readiness["status"],
        "deducted": readiness["breakdown"]["deducted"],
        "counted_findings": readiness["summary"]["counted_findings"],
    }
    record_event(
        session,
        "human_approval",
        f"{claim.claim_number} approved by {actor}",
        claim_id=claim.id,
        actor=actor,
        details={
            "old_state": REVIEW_DRAFT,
            "new_state": REVIEW_APPROVED,
            "score": readiness["score"],
            "status": readiness["status"],
            "note": claim.approval_note,
        },
    )
    session.commit()
    logger.info("%s approved by %s", claim.claim_number, actor)
    return claim


def payload(claim: Claim) -> dict:
    return {
        "state": claim.review_state,
        "approved": claim.review_state == REVIEW_APPROVED,
        "approved_by": claim.approved_by,
        "approved_at": claim.approved_at,
        "approval_note": claim.approval_note,
        "review_started_at": claim.review_started_at,
        "approved_readiness": claim.approved_readiness or {},
    }
