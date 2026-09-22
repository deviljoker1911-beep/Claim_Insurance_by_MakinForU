"""Findings, the checks that produced them, and the actions a person takes on them."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import Finding
from app.schemas import (
    ChecksResponse,
    FindingActionRequest,
    FindingActionResult,
    FindingOut,
    FindingsResponse,
    ValidationRefreshResult,
)
from app.services import validation as validation_service
from app.services.claims import get_claim_or_404, mine_or_404, is_uuid
from app.services.locks import WORKSPACE_LOCK

router = APIRouter(tags=["validation"])

STATUS_VALUES = ("active", "open", "resolved", "acknowledged", "auto_closed", "reopened")
SEVERITY_VALUES = ("critical", "review", "warning", "info")


def _finding_payload(finding: Finding) -> FindingOut:
    from app.models import FINDING_ACTIVE_STATUSES

    return FindingOut.model_validate(finding).model_copy(
        update={
            "is_active": finding.status in FINDING_ACTIVE_STATUSES,
            "actions_available": validation_service.available_actions(finding),
        }
    )


@router.get("/claims/{claim_id}/findings", response_model=FindingsResponse)
def claim_findings(
    claim_id: str,
    status: str | None = Query(default=None, description=f"One of: {', '.join(STATUS_VALUES)}"),
    severity: str | None = Query(default=None, description=f"One of: {', '.join(SEVERITY_VALUES)}"),
    session: Session = Depends(get_session),
) -> FindingsResponse:
    """The findings of one claim.

    Validation runs again first if the processed documents changed since the last run, so the
    list always reflects the documents as they stand. What a person decided about a finding is
    never overwritten by a run.
    """
    if status is not None and status not in STATUS_VALUES:
        raise HTTPException(status_code=422, detail=f"status must be one of: {', '.join(STATUS_VALUES)}")
    if severity is not None and severity not in SEVERITY_VALUES:
        raise HTTPException(status_code=422, detail=f"severity must be one of: {', '.join(SEVERITY_VALUES)}")
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        outcome = validation_service.ensure_current(session, claim, actor=get_settings().operator_name)
        findings = validation_service.findings_for(session, claim.id, status=status, severity=severity)
        return FindingsResponse(
            claim_id=claim.id,
            claim_number=claim.claim_number,
            count=len(findings),
            summary=validation_service.summary(session, claim.id),
            run=outcome.run,
            items=[_finding_payload(finding) for finding in findings],
        )


@router.get("/claims/{claim_id}/checks", response_model=ChecksResponse)
def claim_checks(claim_id: str, session: Session = Depends(get_session)) -> ChecksResponse:
    """Every check the validation engine ran, and whether it passed, failed or is waiting."""
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        outcome = validation_service.ensure_current(session, claim, actor=get_settings().operator_name)
        run = outcome.run
        checks = list(run.checks or []) if run else []
        return ChecksResponse(
            claim_id=claim.id,
            claim_number=claim.claim_number,
            rules_version=run.rules_version if run else 0,
            count=len(checks),
            summary=(run.summary or {}).get("checks", {}) if run else {},
            run=run,
            items=checks,
        )


@router.post("/claims/{claim_id}/validate", response_model=ValidationRefreshResult)
def revalidate(claim_id: str, session: Session = Depends(get_session)) -> ValidationRefreshResult:
    """Run the rules again over the documents as they stand now."""
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        outcome = validation_service.refresh(session, claim, actor=get_settings().operator_name)
        return ValidationRefreshResult(
            claim_id=claim.id,
            claim_number=claim.claim_number,
            ran=outcome.ran,
            findings_raised=outcome.raised,
            findings_created=outcome.created,
            findings_auto_closed=outcome.auto_closed,
            findings_reopened=outcome.reopened,
            summary=validation_service.summary(session, claim.id),
            run=outcome.run,
        )


@router.post("/findings/{finding_id}/action", response_model=FindingActionResult)
def finding_action(
    finding_id: str, request: FindingActionRequest, session: Session = Depends(get_session)
) -> FindingActionResult:
    """Review, resolve, acknowledge or reopen a finding, or exclude a duplicate copy."""
    with WORKSPACE_LOCK.shared():
        finding = session.get(Finding, finding_id) if is_uuid(finding_id) else None
        mine_or_404(session, finding, "Finding")
        try:
            validation_service.apply_action(
                session,
                finding,
                request.action,
                actor=get_settings().operator_name,
                note=request.note,
            )
        except validation_service.ActionNotAllowed as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FindingActionResult(
            finding=_finding_payload(finding),
            summary=validation_service.summary(session, finding.claim_id),
        )
