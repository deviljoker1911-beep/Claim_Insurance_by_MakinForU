"""The procedure checklist of one claim."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.schemas import ChecklistResponse
from app.services import canonical as canonical_service
from app.services import validation as validation_service
from app.services.claims import get_claim_or_404
from app.services.locks import WORKSPACE_LOCK

router = APIRouter(tags=["checklist"])


@router.get("/claims/{claim_id}/checklist", response_model=ChecklistResponse)
def claim_checklist(claim_id: str, session: Session = Depends(get_session)) -> ChecklistResponse:
    """What the detected procedure's claim is expected to carry, and what this claim has.

    The checklist is part of the canonical claim, so it is rebuilt from the documents as they
    stand now. It reports; the findings that a missing document also raises come from the
    rules and are listed against the requirement they belong to. Validation runs again first
    where the documents changed, so this answer and the findings list agree with each other.
    """
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        validation_service.ensure_current(session, claim, actor=get_settings().operator_name)
        state = canonical_service.build(session, claim)
        return ChecklistResponse.model_validate(
            {**state["checklist"], "claim_id": claim.id, "claim_number": claim.claim_number}
        )
