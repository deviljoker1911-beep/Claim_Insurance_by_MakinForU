"""Where a claim stands in the workflow, read from the claim rather than from a counter.

Each step reports what it is waiting for. A step is complete only when its own work is done, so
a later step never reports itself complete because an earlier one happens to be.
"""

from __future__ import annotations

from app.readiness import engine as readiness_engine

DOCUMENTS = "documents"
PROCESSING = "processing"
VALIDATION = "validation"
CHECKLIST = "checklist"
QUESTIONS = "questions"
READINESS = "readiness"
HUMAN_REVIEW = "human_review"

STEPS = (DOCUMENTS, PROCESSING, VALIDATION, CHECKLIST, QUESTIONS, READINESS, HUMAN_REVIEW)

LABELS = {
    DOCUMENTS: "Documents",
    PROCESSING: "Processing",
    VALIDATION: "Validation",
    CHECKLIST: "Checklist",
    QUESTIONS: "Questions",
    READINESS: "Readiness",
    HUMAN_REVIEW: "Human review",
}

PENDING = "pending"
CURRENT = "current"
COMPLETE = "complete"


def _step(key: str, status: str, detail: str) -> dict:
    return {"key": key, "label": LABELS[key], "status": status, "detail": detail}


def build(state: dict) -> list[dict]:
    """The seven steps, each with what it is waiting for."""
    counts = state["meta"]["document_counts"]
    documents = state["documents"]
    processed = counts.get("processed", 0)
    in_flight = sum(counts.get(status, 0) for status in ("pending", "queued", "processing"))
    findings = state["findings"]
    checklist = state["checklist"]
    questions = state["questions"]
    readiness = state["readiness"]
    review = state["review"]

    steps: list[dict] = []

    if documents["count"] == 0:
        steps.append(_step(DOCUMENTS, CURRENT, "No document has been uploaded yet."))
    else:
        steps.append(_step(DOCUMENTS, COMPLETE, f"{documents['count']} document(s) uploaded."))

    if documents["count"] == 0:
        steps.append(_step(PROCESSING, PENDING, "Waiting for documents."))
    elif in_flight:
        steps.append(_step(PROCESSING, CURRENT, f"{in_flight} document(s) still being read."))
    elif processed:
        steps.append(_step(PROCESSING, COMPLETE, f"{processed} document(s) read."))
    else:
        steps.append(_step(PROCESSING, CURRENT, "No document has been analysed yet."))

    validated = findings["available"] and processed > 0 and not in_flight
    if not processed:
        steps.append(_step(VALIDATION, PENDING, "Waiting for a processed document."))
    elif validated:
        steps.append(
            _step(VALIDATION, COMPLETE, f"{findings['count']} finding(s) raised, {findings['active']} still open.")
        )
    else:
        steps.append(_step(VALIDATION, CURRENT, "The rules have not finished with this claim."))

    if not checklist.get("available"):
        steps.append(
            _step(CHECKLIST, PENDING if not processed else CURRENT, checklist.get("note") or "No checklist applies yet.")
        )
    else:
        outstanding = checklist["summary"]["required_outstanding"]
        steps.append(
            _step(
                CHECKLIST,
                COMPLETE if outstanding == 0 else CURRENT,
                f"{outstanding} required requirement(s) outstanding."
                if outstanding
                else "Every required document of this procedure is in the claim.",
            )
        )

    open_questions = questions["open"]
    if questions["count"] == 0:
        steps.append(
            _step(QUESTIONS, COMPLETE if checklist.get("available") else PENDING, "Nothing is being asked for.")
        )
    elif open_questions:
        steps.append(_step(QUESTIONS, CURRENT, f"{open_questions} question(s) waiting for an answer."))
    else:
        steps.append(_step(QUESTIONS, COMPLETE, f"All {questions['count']} question(s) answered."))

    if readiness["status"] == readiness_engine.READY_FOR_HUMAN_REVIEW:
        steps.append(_step(READINESS, COMPLETE, f"{readiness['score']}% — {readiness['status_label'].lower()}."))
    elif processed:
        steps.append(_step(READINESS, CURRENT, f"{readiness['score']}% — {readiness['status_label'].lower()}."))
    else:
        steps.append(_step(READINESS, PENDING, "Waiting for the documents to be read."))

    if review["approved"]:
        steps.append(_step(HUMAN_REVIEW, COMPLETE, f"Approved by {review['approved_by']}."))
    elif readiness["status"] == readiness_engine.READY_FOR_HUMAN_REVIEW:
        steps.append(_step(HUMAN_REVIEW, CURRENT, "A person can review and approve this claim."))
    else:
        steps.append(_step(HUMAN_REVIEW, PENDING, "Available once the documentation is ready for review."))

    return steps
