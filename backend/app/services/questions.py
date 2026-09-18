"""Storing questions, recording what the operator answered, and closing them with a document.

A question asks for one checklist requirement of one claim. It is created when the checklist
says a required document is missing, and it closes when a document of the expected type is in
the claim — not when someone says it will be. What a person answered is kept as they gave it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.classify import type_label
from app.audit import record_event
from app.config import get_settings
from app.models import (
    ANSWER_NOT_APPLICABLE,
    ANSWER_NOT_AVAILABLE,
    ANSWER_YES_HAVE_IT,
    QUESTION_ANSWERED,
    QUESTION_DOCUMENTED_UNAVAILABLE,
    QUESTION_NOT_APPLICABLE,
    QUESTION_OPEN,
    QUESTION_PENDING_STATUSES,
    QUESTION_RESOLVED,
    Claim,
    Document,
    Question,
    utcnow,
)
from app.questions import engine as question_engine

logger = logging.getLogger("claimai.questions")


class AnswerNotAllowed(ValueError):
    """The answer does not apply to this question in its current state."""


class ReasonRequired(ValueError):
    """The answer needs a reason and none was given."""


@dataclass
class RefreshOutcome:
    created: list[Question]
    resolved: list[Question]
    withdrawn: list[Question]

    @property
    def changed(self) -> bool:
        return bool(self.created or self.resolved or self.withdrawn)


def questions_for(session: Session, claim_id: str) -> list[Question]:
    rows = session.scalars(select(Question).where(Question.claim_id == claim_id)).all()
    order = {status: index for index, status in enumerate(
        (QUESTION_OPEN, QUESTION_ANSWERED, QUESTION_DOCUMENTED_UNAVAILABLE, QUESTION_NOT_APPLICABLE, QUESTION_RESOLVED)
    )}
    severity_order = {"critical": 0, "review": 1, "warning": 2, "info": 3}
    return sorted(
        rows,
        key=lambda row: (order.get(row.status, 9), severity_order.get(row.severity, 9), row.requirement_key),
    )


def get_question_or_none(session: Session, question_id: str) -> Question | None:
    if not isinstance(question_id, str) or "\x00" in question_id:
        return None
    return session.get(Question, question_id)


def refresh(session: Session, claim: Claim, checklist: dict, *, actor: str | None = None) -> RefreshOutcome:
    """Bring the claim's questions in line with its checklist."""
    actor = actor or get_settings().operator_name
    stored = {row.requirement_key: row for row in questions_for(session, claim.id)}
    plan = question_engine.plan(checklist, {key: row.status for key, row in stored.items()})
    outcome = RefreshOutcome(created=[], resolved=[], withdrawn=[])
    if plan.empty:
        return outcome

    for ask in plan.ask:
        question = Question(
            claim_id=claim.id,
            requirement_key=ask.requirement_key,
            requirement_label=ask.requirement_label,
            procedure_key=ask.procedure_key,
            question=ask.question,
            reason=ask.reason,
            expected_document_type=ask.expected_document_type,
            expected_document_types=list(ask.expected_document_types),
            severity=ask.severity,
            status=QUESTION_OPEN,
        )
        session.add(question)
        outcome.created.append(question)
        record_event(
            session,
            "question_generated",
            f"Asked for the {ask.requirement_label.lower()}",
            claim_id=claim.id,
            actor="system",
            details={
                "requirement": ask.requirement_key,
                "expected_document_type": ask.expected_document_type,
                "question": ask.question,
                "reason": ask.reason,
            },
        )

    for key in plan.resolve:
        question = stored[key]
        document = _satisfying_document(session, claim.id, question)
        previous = question.status
        question.status = QUESTION_RESOLVED
        question.resolved_at = utcnow()
        if document is not None:
            question.resolved_document_id = document.id
        outcome.resolved.append(question)
        record_event(
            session,
            "question_resolved",
            f"The {question.requirement_label.lower()} is now in the claim",
            claim_id=claim.id,
            document_id=document.id if document else None,
            actor="system",
            details={
                "requirement": question.requirement_key,
                "question_id": question.id,
                "old_status": previous,
                "new_status": QUESTION_RESOLVED,
                "document": document.original_filename if document else None,
                "doc_type": document.doc_type if document else None,
            },
        )

    for key, why in plan.withdraw:
        question = stored[key]
        previous = question.status
        question.status = QUESTION_NOT_APPLICABLE
        question.answer_reason = why[:500]
        question.answered_at = utcnow()
        question.answered_by = "system"
        outcome.withdrawn.append(question)
        record_event(
            session,
            "question_marked_not_applicable",
            f"The {question.requirement_label.lower()} is no longer asked for",
            claim_id=claim.id,
            actor="system",
            details={
                "requirement": question.requirement_key,
                "question_id": question.id,
                "old_status": previous,
                "new_status": QUESTION_NOT_APPLICABLE,
                "reason": why,
            },
        )
    return outcome


def _satisfying_document(session: Session, claim_id: str, question: Question) -> Document | None:
    """The document that answers a question: the one uploaded for it, else the earliest of the type."""
    expected = set(question.expected_document_types or [question.expected_document_type])
    documents = session.scalars(
        select(Document).where(Document.claim_id == claim_id).order_by(Document.uploaded_at, Document.original_filename)
    ).all()
    usable = [
        document
        for document in documents
        if document.doc_type in expected and document.processing_status == "processed" and not document.excluded
    ]
    for document in usable:
        if document.question_id == question.id:
            return document
    return usable[0] if usable else None


def answer(
    session: Session,
    question: Question,
    response: str,
    *,
    actor: str,
    reason: str | None = None,
) -> Question:
    """Record what the operator answered.

    "Yes, I have it" is not a resolution: the question stays open for the document until one
    of the expected type is in the claim.
    """
    if question.status not in QUESTION_PENDING_STATUSES:
        raise AnswerNotAllowed(f"This question is {question.status.replace('_', ' ')} and takes no further answer.")
    reason = (reason or "").strip()
    if response in (ANSWER_NOT_AVAILABLE, ANSWER_NOT_APPLICABLE) and not reason:
        raise ReasonRequired("A reason is required so the decision is on the record.")

    previous = question.status
    question.answer = response
    question.answered_at = utcnow()
    question.answered_by = actor
    question.answer_reason = reason[:500] or None

    if response == ANSWER_YES_HAVE_IT:
        question.status = QUESTION_ANSWERED
        event, message = "document_requested", f"{question.requirement_label} requested from the operator"
    elif response == ANSWER_NOT_AVAILABLE:
        question.status = QUESTION_DOCUMENTED_UNAVAILABLE
        event, message = "question_marked_unavailable", f"{question.requirement_label} recorded as not available"
    else:
        question.status = QUESTION_NOT_APPLICABLE
        event, message = "question_marked_not_applicable", f"{question.requirement_label} recorded as not applicable"

    record_event(
        session,
        "question_answered",
        f"Answered: {question.requirement_label.lower()} — {response.replace('_', ' ')}",
        claim_id=question.claim_id,
        actor=actor,
        details={
            "question_id": question.id,
            "requirement": question.requirement_key,
            "answer": response,
            "reason": reason or None,
            "old_status": previous,
            "new_status": question.status,
        },
    )
    record_event(
        session,
        event,
        message,
        claim_id=question.claim_id,
        actor=actor,
        details={
            "question_id": question.id,
            "requirement": question.requirement_key,
            "expected_document_type": question.expected_document_type,
            "reason": reason or None,
        },
    )
    session.commit()
    return question


def attach_documents(session: Session, question: Question, documents: list[Document], *, actor: str) -> None:
    """Record that these documents were uploaded in answer to this question."""
    for document in documents:
        document.question_id = question.id
        record_event(
            session,
            "document_uploaded_for_question",
            f"{document.original_filename} uploaded for the {question.requirement_label.lower()}",
            claim_id=question.claim_id,
            document_id=document.id,
            actor=actor,
            details={
                "question_id": question.id,
                "requirement": question.requirement_key,
                "expected_document_type": question.expected_document_type,
            },
        )
    if question.status == QUESTION_OPEN:
        question.status = QUESTION_ANSWERED
        question.answer = ANSWER_YES_HAVE_IT
        question.answered_at = utcnow()
        question.answered_by = actor
    session.commit()


def review_upload(session: Session, document: Document) -> None:
    """After a document was processed, say whether it answers the question it was uploaded for.

    A document that classifies as something else does not resolve the question, and the
    classification is reported as it was made.
    """
    if not document.question_id:
        return
    question = session.get(Question, document.question_id)
    if question is None:
        return
    expected = set(question.expected_document_types or [question.expected_document_type])
    satisfies = document.doc_type in expected and not document.excluded
    question.last_upload = {
        "document_id": document.id,
        "document_name": document.original_filename,
        "doc_type": document.doc_type,
        "doc_type_label": type_label(document.doc_type) if document.doc_type else None,
        "expected_document_types": sorted(expected),
        "satisfies": satisfies,
        "message": (
            f"{document.original_filename} is the {type_label(document.doc_type).lower()} that was asked for."
            if satisfies
            else "Document type does not satisfy this request."
        ),
        "checked_at": utcnow().isoformat(),
    }
    if not satisfies:
        record_event(
            session,
            "question_upload_did_not_match",
            f"{document.original_filename} does not satisfy the request for the {question.requirement_label.lower()}",
            claim_id=question.claim_id,
            document_id=document.id,
            actor="system",
            details={
                "question_id": question.id,
                "requirement": question.requirement_key,
                "expected_document_types": sorted(expected),
                "detected_doc_type": document.doc_type,
                "detected_doc_type_label": type_label(document.doc_type) if document.doc_type else None,
            },
        )
    # Resolving is left to the checklist: a question closes when the claim carries the
    # document, which is refreshed once analysis finishes.


def summary(session: Session, claim_id: str) -> dict:
    rows = questions_for(session, claim_id)
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    return {
        "total": len(rows),
        "open": sum(1 for row in rows if row.status in QUESTION_PENDING_STATUSES),
        "by_status": dict(sorted(by_status.items())),
    }
