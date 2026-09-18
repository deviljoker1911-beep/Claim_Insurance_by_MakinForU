"""Documentation readiness, and the human approval that follows it."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.readiness import workflow
from app.schemas import ApprovalRequest, ApprovalResult, ReadinessResponse
from app.services import canonical as canonical_service
from app.services import reanalysis as reanalysis_service
from app.services import review as review_service
from app.services.claims import get_claim_or_404
from app.services.locks import WORKSPACE_LOCK

router = APIRouter(tags=["readiness"])


def _state(session: Session, claim):
    """The claim as it stands, brought up to date first."""
    reanalysis_service.ensure_current(session, claim, actor=get_settings().operator_name)
    return canonical_service.build(session, claim)


@router.get("/claims/{claim_id}/readiness", response_model=ReadinessResponse)
def claim_readiness(claim_id: str, session: Session = Depends(get_session)) -> ReadinessResponse:
    """How complete this claim's documentation is, and what each missing point is for.

    The score is counted from the checklist, the findings and the questions as they stand; it
    is a description of the paperwork, not a judgement about the claim.
    """
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        state = _state(session, claim)
        readiness = state["readiness"]
        review_service.note_ready_for_review(session, claim, readiness)
        return ReadinessResponse.model_validate(
            {
                **readiness,
                "claim_id": claim.id,
                "claim_number": claim.claim_number,
                "review": {**state["review"], "review_started_at": claim.review_started_at},
                "workflow": workflow.build(state),
            }
        )


@router.post("/claims/{claim_id}/review/approve", response_model=ApprovalResult)
def approve_claim(
    claim_id: str, request: ApprovalRequest | None = None, session: Session = Depends(get_session)
) -> ApprovalResult:
    """Approve a claim. A person does this; nothing in the system does it for them.

    Refused while the documentation is incomplete or needs attention, and refused a second
    time once the claim is approved.
    """
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        state = _state(session, claim)
        readiness = state["readiness"]
        try:
            claim = review_service.approve(
                session,
                claim,
                readiness,
                actor=get_settings().operator_name,
                note=(request.note if request else None),
            )
        except review_service.ApprovalNotAllowed as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        # The score is what it was: approval records a decision, it does not change the claim.
        return ApprovalResult.model_validate(
            {
                "claim_id": claim.id,
                "claim_number": claim.claim_number,
                "review": {**review_service.payload(claim), "can_approve": False},
                "readiness": readiness,
            }
        )
