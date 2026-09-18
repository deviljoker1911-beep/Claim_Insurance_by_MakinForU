"""Incremental re-analysis: run the existing pipelines again and record what changed.

Nothing here analyses anything itself. A document is processed by the phase 3 worker; the
canonical claim, the rules and the checklist are then refreshed through their own services,
the questions are brought in line with the checklist, and the difference between the claim as
it was and as it is now is stored as one re-analysis run.
"""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_event
from app.models import Claim, ReanalysisRun, utcnow
from app.reanalysis import summary as change_model
from app.services import analysis as analysis_service
from app.services import canonical as canonical_service
from app.services import questions as question_service
from app.services import review as review_service
from app.services import validation as validation_service

logger = logging.getLogger("claimai.reanalysis")

# One re-analysis at a time per claim. The worker finishes a document while the interface is
# reading the questions and the changes; without this each of them would record its own pass of
# the same work, and the history would report one upload as several partial passes.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _claim_lock(claim_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(claim_id, threading.Lock())


def latest(session: Session, claim_id: str) -> ReanalysisRun | None:
    return session.scalars(
        select(ReanalysisRun).where(ReanalysisRun.claim_id == claim_id).order_by(ReanalysisRun.sequence.desc()).limit(1)
    ).first()


def history(session: Session, claim_id: str, limit: int = 20) -> list[ReanalysisRun]:
    return list(
        session.scalars(
            select(ReanalysisRun)
            .where(ReanalysisRun.claim_id == claim_id)
            .order_by(ReanalysisRun.sequence.desc())
            .limit(limit)
        ).all()
    )


def run(
    session: Session,
    claim: Claim,
    *,
    trigger: str = "analysis",
    actor: str = "system",
    only_if_changed: bool = False,
) -> ReanalysisRun | None:
    """Refresh everything derived from the documents and record the difference.

    Each stage is the one that phase already owns: the canonical claim from the canonical
    service, the findings from the validation service, the checklist from the canonical claim,
    and the questions from the checklist. One pass runs at a time for a claim, so concurrent
    callers wait for the pass in flight and then see that there is nothing left to do.
    """
    with _claim_lock(claim.id):
        return _run_locked(session, claim, trigger=trigger, actor=actor, only_if_changed=only_if_changed)


def _run_locked(
    session: Session, claim: Claim, *, trigger: str, actor: str, only_if_changed: bool
) -> ReanalysisRun | None:
    started = time.monotonic()
    session.expire_all()  # another pass may have committed while this one waited for the lock
    previous = latest(session, claim.id)
    if only_if_changed and _documents_in_flight(session, claim.id):
        # A pass describes a settled claim. While a document is still being read, what it will
        # change is not known yet, and the worker runs a pass of its own when it finishes.
        return previous
    if only_if_changed:
        state = canonical_service.build(session, claim)
        questions = question_service.questions_for(session, claim.id)
        if previous is not None and previous.after_state == change_model.state_summary(state, questions):
            return previous
    before_state = dict(previous.after_state or {}) if previous else {}
    sequence = (previous.sequence + 1) if previous else 1

    record_event(
        session,
        "reanalysis_started",
        "Re-analysis started",
        claim_id=claim.id,
        actor=actor,
        details={"sequence": sequence, "trigger": trigger},
    )

    state, _ = canonical_service.refresh(session, claim)
    validation_service.refresh(session, claim, actor=actor, state=state)
    # The canonical claim is rebuilt once validation has written its findings, so the checklist
    # and the questions see the claim as it now stands.
    state, _ = canonical_service.refresh(session, claim)
    question_service.refresh(session, claim, state["checklist"], actor=actor)
    session.commit()

    state, _ = canonical_service.refresh(session, claim)
    # An approval given to the claim as it was does not carry over to the claim as it is now.
    if review_service.refresh_approval(session, claim, state, state["readiness"]):
        state, _ = canonical_service.refresh(session, claim)
    questions = question_service.questions_for(session, claim.id)
    after_state = change_model.state_summary(state, questions)
    changes = change_model.diff(before_state, after_state)
    counts = change_model.summarise(changes, after_state)
    added = [
        {"document_id": change["key"], "filename": change["label"]}
        for change in changes
        if change["kind"] == change_model.KIND_DOCUMENT and change["before"] is None
    ]

    run_row = ReanalysisRun(
        claim_id=claim.id,
        sequence=sequence,
        trigger=trigger,
        before_state=before_state,
        after_state=after_state,
        changes=changes,
        summary=counts,
        documents_added=added,
        completed_at=utcnow(),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    session.add(run_row)
    record_event(
        session,
        "reanalysis_completed",
        f"Re-analysis finished with {counts['changes']} change(s)",
        claim_id=claim.id,
        actor=actor,
        details={"sequence": sequence, "trigger": trigger, **counts},
    )
    try:
        session.commit()
    except IntegrityError:
        # Another process recorded this sequence first; its pass covered the same work.
        session.rollback()
        logger.info("Re-analysis %s of %s was recorded by another writer", sequence, claim.claim_number)
        return latest(session, claim.id)
    return run_row


def _documents_in_flight(session: Session, claim_id: str) -> bool:
    counts = analysis_service.status_counts(session, claim_id)
    return any(counts.get(status) for status in analysis_service.UNFINISHED_STATUSES)


def ensure_current(session: Session, claim: Claim, *, actor: str = "system") -> ReanalysisRun | None:
    """Run a re-analysis only where something the claim is derived from has moved on."""
    return run(session, claim, trigger="analysis", actor=actor, only_if_changed=True)
