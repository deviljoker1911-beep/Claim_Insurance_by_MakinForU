"""Storing findings and moving them through their lifecycle.

A finding is identified by its fingerprint, so running validation again updates the finding
that is already there instead of adding another. What a person decided is never overwritten by
a later run: a resolved finding stays resolved. A finding the rules stop raising is closed
automatically, and if the rules raise it again it comes back as reopened.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.canonical.builder import build_claim_state, json_ready
from app.models import (
    FINDING_ACKNOWLEDGED,
    FINDING_ACTIVE_STATUSES,
    FINDING_AUTO_CLOSED,
    FINDING_OPEN,
    FINDING_REOPENED,
    FINDING_RESOLVED,
    SEVERITIES,
    SEVERITY_ORDER,
    Claim,
    Document,
    Finding,
    ValidationRun,
    utcnow,
)
from app.services.locks import locked
from app.validation import engine
from app.validation.rules import rules_version
from app.text import plural

logger = logging.getLogger("claimai.validation")

ACTION_REVIEW = "review"
ACTION_RESOLVE = "resolve"
ACTION_ACKNOWLEDGE = "acknowledge"
ACTION_REOPEN = "reopen"
ACTION_EXCLUDE_DUPLICATE = "exclude_duplicate"
ACTIONS = (ACTION_REVIEW, ACTION_RESOLVE, ACTION_ACKNOWLEDGE, ACTION_REOPEN, ACTION_EXCLUDE_DUPLICATE)

# Which statuses each action may be applied to.
ALLOWED_FROM: dict[str, tuple[str, ...]] = {
    ACTION_REVIEW: (FINDING_OPEN, FINDING_REOPENED, FINDING_ACKNOWLEDGED),
    ACTION_RESOLVE: (FINDING_OPEN, FINDING_REOPENED, FINDING_ACKNOWLEDGED),
    ACTION_ACKNOWLEDGE: (FINDING_OPEN, FINDING_REOPENED),
    ACTION_REOPEN: (FINDING_RESOLVED, FINDING_ACKNOWLEDGED, FINDING_AUTO_CLOSED),
    ACTION_EXCLUDE_DUPLICATE: (FINDING_OPEN, FINDING_REOPENED, FINDING_ACKNOWLEDGED),
}

EXCLUDABLE_CODES = ("DUPLICATE_DOCUMENT",)


class ActionNotAllowed(ValueError):
    """The requested action does not apply to this finding in its current state."""


@dataclass
class RefreshOutcome:
    run: ValidationRun
    created: int
    auto_closed: int
    reopened: int
    raised: int
    ran: bool


# --- reading ------------------------------------------------------------------------------


def stored_run(session: Session, claim_id: str) -> ValidationRun | None:
    return session.scalar(select(ValidationRun).where(ValidationRun.claim_id == claim_id))


def findings_for(
    session: Session, claim_id: str, *, status: str | None = None, severity: str | None = None
) -> list[Finding]:
    query = select(Finding).where(Finding.claim_id == claim_id)
    if status == "active":
        query = query.where(Finding.status.in_(FINDING_ACTIVE_STATUSES))
    elif status:
        query = query.where(Finding.status == status)
    if severity:
        query = query.where(Finding.severity == severity)
    findings = list(session.scalars(query).all())
    active_first = {True: 0, False: 1}
    return sorted(
        findings,
        key=lambda finding: (
            active_first[finding.status in FINDING_ACTIVE_STATUSES],
            SEVERITY_ORDER.get(finding.severity, 9),
            finding.rule_id,
            finding.subject,
        ),
    )


def summary(session: Session, claim_id: str) -> dict:
    rows = session.execute(
        select(Finding.severity, Finding.status, func.count())
        .where(Finding.claim_id == claim_id)
        .group_by(Finding.severity, Finding.status)
    ).all()
    by_severity = {severity: 0 for severity in SEVERITIES}
    by_status = {}
    active_by_severity = {severity: 0 for severity in SEVERITIES}
    total = 0
    for severity, status, count in rows:
        total += count
        by_severity[severity] = by_severity.get(severity, 0) + count
        by_status[status] = by_status.get(status, 0) + count
        if status in FINDING_ACTIVE_STATUSES:
            active_by_severity[severity] = active_by_severity.get(severity, 0) + count
    return {
        "total": total,
        "active": sum(active_by_severity.values()),
        "by_severity": by_severity,
        "active_by_severity": active_by_severity,
        "by_status": by_status,
    }


# --- running ------------------------------------------------------------------------------


def refresh(session: Session, claim: Claim, *, actor: str | None = None, state: dict | None = None) -> RefreshOutcome:
    """Run the rules and reconcile the findings of this claim with what they raise now."""
    started = time.monotonic()
    result = engine.run(session, claim, state)
    now = utcnow()

    # Hold the claim for the rest of the run. A finding is identified by its fingerprint, and two
    # runs of the same claim at the same moment both found no row for a fingerprint and both
    # inserted one, which the unique constraint refused — so reading a claim's findings while its
    # documents were being read could fail outright. The second run now waits, and then sees the
    # findings the first one wrote and updates them instead of adding a second copy.
    locked(session, claim)

    stored = stored_run(session, claim.id)
    # Replaying the same documents must leave the findings exactly as they are: only a run over
    # changed documents (or changed rules) counts as another occurrence.
    inputs_changed = (
        stored is None
        or stored.input_fingerprint != result.input_fingerprint
        or stored.rules_version != result.rules_version
    )

    existing = {row.fingerprint: row for row in session.scalars(select(Finding).where(Finding.claim_id == claim.id)).all()}
    raised = {finding.fingerprint: finding for finding in result.findings}
    created = reopened = auto_closed = 0

    for fingerprint, finding in raised.items():
        payload = finding.payload()
        row = existing.get(fingerprint)
        if row is None:
            session.add(
                Finding(
                    claim_id=claim.id,
                    status=FINDING_OPEN,
                    first_seen_at=now,
                    last_seen_at=now,
                    occurrences=1,
                    **payload,
                )
            )
            created += 1
            continue
        # The wording and evidence follow the documents; the human decision does not.
        row.rule_id = payload["rule_id"]
        row.code = payload["code"]
        row.category = payload["category"]
        row.severity = payload["severity"]
        row.attribution = payload["attribution"]
        row.title = payload["title"]
        row.explanation = payload["explanation"]
        row.action = payload["action"]
        row.evidence = payload["evidence"]
        row.context = payload["context"]
        if inputs_changed:
            row.last_seen_at = now
            row.occurrences = (row.occurrences or 0) + 1
        if row.status == FINDING_AUTO_CLOSED:
            row.status = FINDING_REOPENED
            row.status_changed_at = now
            row.status_actor = "system"
            row.status_note = "The rule raised this finding again."
            reopened += 1

    for fingerprint, row in existing.items():
        if fingerprint in raised or row.status not in FINDING_ACTIVE_STATUSES:
            continue
        row.status = FINDING_AUTO_CLOSED
        row.status_changed_at = now
        row.status_actor = "system"
        row.status_note = "The rule no longer raises this finding."
        auto_closed += 1

    for document_id, update in result.document_updates.items():
        document = session.get(Document, document_id)
        if document is None:
            continue
        document.duplicate_state = update["duplicate_state"]
        document.duplicate_of = update["duplicate_of"]

    run = stored
    if run is None:
        run = ValidationRun(claim_id=claim.id)
        session.add(run)
    run.rules_version = result.rules_version
    run.input_fingerprint = result.input_fingerprint
    run.checks = result.checks
    run.summary = result.summary
    run.findings_raised = len(result.findings)
    run.findings_created = created
    run.findings_auto_closed = auto_closed
    run.findings_reopened = reopened
    run.duration_ms = int((time.monotonic() - started) * 1000)

    # A run that changed nothing is not worth an audit entry.
    if inputs_changed or created or auto_closed or reopened:
        record_event(
            session,
            "validation_completed",
            f"Validation raised {plural(len(result.findings), 'finding')}",
            claim_id=claim.id,
            actor=actor or "system",
            details={
                "rules_version": result.rules_version,
                "findings_raised": len(result.findings),
                "created": created,
                "auto_closed": auto_closed,
                "reopened": reopened,
                "inputs_changed": inputs_changed,
                "checks": result.summary["checks"],
                "by_severity": result.summary["by_severity"],
            },
        )
    session.commit()
    return RefreshOutcome(
        run=run, created=created, auto_closed=auto_closed, reopened=reopened, raised=len(result.findings), ran=True
    )


def ensure_current(session: Session, claim: Claim, *, actor: str | None = None) -> RefreshOutcome:
    """Validate again only when the processed documents changed since the last run."""
    state = json_ready(build_claim_state(session, claim))
    fingerprint = engine.input_fingerprint(state)
    run = stored_run(session, claim.id)
    if run is not None and run.input_fingerprint == fingerprint and run.rules_version == rules_version():
        return RefreshOutcome(run=run, created=0, auto_closed=0, reopened=0, raised=run.findings_raised, ran=False)
    return refresh(session, claim, actor=actor, state=state)


# --- lifecycle ----------------------------------------------------------------------------


def apply_action(session: Session, finding: Finding, action: str, *, actor: str, note: str | None = None) -> Finding:
    """Move one finding through its lifecycle."""
    if action not in ACTIONS:
        raise ActionNotAllowed(f"Unknown action {action!r}. Use one of: {', '.join(ACTIONS)}.")
    # Hold the finding before reading the status its lifecycle is checked against, so the same
    # action arriving twice is applied once.
    locked(session, finding)
    if finding.status not in ALLOWED_FROM[action]:
        raise ActionNotAllowed(
            f"A finding that is {finding.status.replace('_', ' ')} cannot be {_describe(action)}."
        )

    now = utcnow()
    previous = finding.status
    details: dict = {"action": action, "code": finding.code, "from": previous}

    if action == ACTION_REVIEW:
        finding.reviewed_at = now
        finding.reviewed_by = actor
        if note:
            finding.status_note = note[:500]
        message = f"{finding.code} marked as reviewed"
    elif action == ACTION_RESOLVE:
        _set_status(finding, FINDING_RESOLVED, actor, note or "Resolved by the operator", now)
        message = f"{finding.code} resolved"
    elif action == ACTION_ACKNOWLEDGE:
        _set_status(finding, FINDING_ACKNOWLEDGED, actor, note or "Acknowledged by the operator", now)
        message = f"{finding.code} acknowledged"
    elif action == ACTION_REOPEN:
        _set_status(finding, FINDING_REOPENED, actor, note or "Reopened by the operator", now)
        message = f"{finding.code} reopened"
    else:  # exclude the duplicate copy from the claim
        if finding.code not in EXCLUDABLE_CODES:
            raise ActionNotAllowed(
                "Only a duplicate document finding can be excluded; resolve or acknowledge this finding instead."
            )
        document_id = (finding.context or {}).get("document_id")
        document = session.get(Document, document_id) if document_id else None
        if document is None:
            raise ActionNotAllowed("The duplicate document is no longer part of this claim.")
        document.excluded = True
        document.exclusion_reason = note or "Excluded as a duplicate copy by the operator"
        document.duplicate_state = "excluded"
        document.duplicate_of = (finding.context or {}).get("original_document_id")
        _set_status(finding, FINDING_RESOLVED, actor, note or f"{document.original_filename} excluded as a duplicate", now)
        details["document_id"] = document.id
        details["document"] = document.original_filename
        message = f"{document.original_filename} excluded as a duplicate copy"
        record_event(
            session,
            "document_excluded",
            message,
            claim_id=finding.claim_id,
            document_id=document.id,
            actor=actor,
            details={"reason": document.exclusion_reason, "duplicate_of": document.duplicate_of},
        )

    details["to"] = finding.status
    record_event(
        session,
        "finding_action",
        message,
        claim_id=finding.claim_id,
        actor=actor,
        details=details,
    )
    session.commit()
    return finding


def available_actions(finding: Finding) -> list[str]:
    """The actions that apply to this finding as it stands."""
    actions = [action for action in ACTIONS if finding.status in ALLOWED_FROM[action]]
    if finding.code not in EXCLUDABLE_CODES and ACTION_EXCLUDE_DUPLICATE in actions:
        actions.remove(ACTION_EXCLUDE_DUPLICATE)
    return actions


def _set_status(finding: Finding, status: str, actor: str, note: str | None, now) -> None:
    finding.status = status
    finding.status_actor = actor
    finding.status_note = (note or "")[:500] or None
    finding.status_changed_at = now


def _describe(action: str) -> str:
    return {
        ACTION_REVIEW: "marked as reviewed",
        ACTION_RESOLVE: "resolved",
        ACTION_ACKNOWLEDGE: "acknowledged",
        ACTION_REOPEN: "reopened",
        ACTION_EXCLUDE_DUPLICATE: "excluded as a duplicate",
    }[action]
