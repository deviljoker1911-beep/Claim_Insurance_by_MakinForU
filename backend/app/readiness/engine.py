"""Documentation readiness: what the claim is still waiting for, counted once.

The score starts at 100 and every outstanding item deducts from it. Each deduction names the
thing that caused it, so a score can always be read back as a list of reasons. Nothing here
decides anything about the claim: readiness describes the paperwork, and a person decides what
happens next.

One issue is charged once. A required document the claim does not have is charged as a missing
document, and the findings the rules raise because it is missing — the missing-document finding
itself, and any rule that can only be satisfied by that document — are not charged again.
"""

from __future__ import annotations

from app.config_files import readiness_config, rules_config
from app.models import DOCUMENT_UNFINISHED_STATUSES, FINDING_ACTIVE_STATUSES, QUESTION_PENDING_STATUSES
from app.validation.rules import required_documents

INCOMPLETE = "incomplete"
NEEDS_ATTENTION = "needs_attention"
READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
STATUSES = (INCOMPLETE, NEEDS_ATTENTION, READY_FOR_HUMAN_REVIEW)

STATUS_LABELS = {
    INCOMPLETE: "Incomplete",
    NEEDS_ATTENTION: "Needs attention",
    READY_FOR_HUMAN_REVIEW: "Ready for human review",
}

MISSING_REQUIRED_DOCUMENT = "MISSING_REQUIRED_DOCUMENT"

# How a requirement's request was answered, from the readiness engine's point of view.
NO_RESPONSE = "no_response"
DOCUMENTED_UNAVAILABLE = "documented_unavailable"
NOT_APPLICABLE = "not_applicable"


def _amounts() -> dict[str, int]:
    return {key: int(value) for key, value in readiness_config()["deductions"].items()}


def _rule_dependencies() -> dict[str, tuple[str, ...]]:
    """The document types each rule can only be satisfied by, as the rules declare them."""
    return {
        rule["code"]: tuple(rule.get("depends_on_document_types") or ())
        for rule in rules_config()["rules"]
    }


def _response_for(requirement_key: str, questions: list[dict]) -> tuple[str, dict | None]:
    question = next((item for item in questions if item["requirement_key"] == requirement_key), None)
    if question is None:
        return NO_RESPONSE, None
    if question["status"] == "documented_unavailable":
        return DOCUMENTED_UNAVAILABLE, question
    if question["status"] == "not_applicable":
        return NOT_APPLICABLE, question
    if question["status"] in QUESTION_PENDING_STATUSES:
        return NO_RESPONSE, question
    return NO_RESPONSE, question


def _deduction(reason: str, amount: int, kind: str, key: str, label: str, **extra) -> dict:
    return {
        "reason": reason,
        "amount": amount,
        "source": {"kind": kind, "key": key, "label": label, **extra},
    }


def _covered_by_checklist(finding: dict, rule_requirement_types: dict[str, set], covered_types: set[str]) -> bool:
    """Whether a missing-document finding is about a document type the checklist charges for."""
    subject = finding.get("subject") or ""
    if not subject.startswith("requirement:"):
        return False
    return bool(rule_requirement_types.get(subject.split(":", 1)[1], set()) & covered_types)


def evaluate(state: dict, questions: list[dict]) -> dict:
    """The readiness of one claim, from its checklist, its findings and its questions."""
    config = readiness_config()
    amounts = _amounts()
    dependencies = _rule_dependencies()
    base = int(config["base_score"])
    floor = int(config["floor"])

    checklist = state.get("checklist") or {}
    items = checklist.get("items", []) if checklist.get("available") else []
    findings = state["findings"]["items"]
    active = [finding for finding in findings if finding["status"] in FINDING_ACTIVE_STATUSES]

    present_types = {
        document["doc_type"]
        for document in state["documents"]["items"]
        if document["doc_type"] and not document["excluded"] and document["processing_status"] == "processed"
    }
    # Documents of this claim that have not been read yet. What the checklist and the findings
    # describe is only part of the claim while any of these are outstanding.
    included = [document for document in state["documents"]["items"] if not document["excluded"]]
    still_reading = [
        document for document in included if document["processing_status"] in DOCUMENT_UNFINISHED_STATUSES
    ]

    deductions: list[dict] = []
    blocking: list[dict] = []
    missing_without_response = 0
    documented_unavailable = 0
    not_applicable = 0
    checklist_reviews = 0

    for item in items:
        if not item["required"]:
            continue
        if item["status"] == "missing":
            response, question = _response_for(item["key"], questions)
            if response == NOT_APPLICABLE:
                not_applicable += 1
                continue
            if response == DOCUMENTED_UNAVAILABLE:
                documented_unavailable += 1
                deductions.append(
                    _deduction(
                        f"{item['label']} is documented as unavailable",
                        amounts["required_document_documented_unavailable"],
                        "requirement",
                        item["key"],
                        item["label"],
                        detail=(question or {}).get("answer_reason"),
                    )
                )
                continue
            missing_without_response += 1
            deductions.append(
                _deduction(
                    f"{item['label']} is missing and the request for it has not been answered",
                    amounts["required_document_missing"],
                    "requirement",
                    item["key"],
                    item["label"],
                    question_id=(question or {}).get("id"),
                )
            )
            blocking.append(
                {
                    "kind": "requirement",
                    "key": item["key"],
                    "label": item["label"],
                    "detail": item["detail"],
                    "action": item["resolution"],
                }
            )
        elif item["status"] == "review_required":
            checklist_reviews += 1
            linked = [
                finding
                for finding in item["findings"]
                if finding["is_active"] and finding["code"] != MISSING_REQUIRED_DOCUMENT
            ]
            if not linked:
                deductions.append(
                    _deduction(
                        f"{item['label']} needs a person to look at it",
                        amounts["checklist_review_without_finding"],
                        "requirement",
                        item["key"],
                        item["label"],
                        detail=item["detail"],
                    )
                )
            blocking.append(
                {
                    "kind": "requirement",
                    "key": item["key"],
                    "label": item["label"],
                    "detail": item["detail"],
                    "action": item["resolution"],
                }
            )

    # The document types the checklist itself is responsible for. A missing-document finding
    # about one of them is already charged as that requirement; one about anything else — a
    # document the rules require but no checklist requirement covers — is charged here, so that
    # no required document can be missing for nothing.
    covered_types = {doc_type for item in items if item["required"] for doc_type in item["doc_types"]}
    rule_requirement_types = {item["key"]: set(item["doc_types"]) for item in required_documents()}

    counted_findings = []
    for finding in sorted(active, key=lambda item: (item["severity"], item["code"], item["id"])):
        if finding["code"] == MISSING_REQUIRED_DOCUMENT and _covered_by_checklist(
            finding, rule_requirement_types, covered_types
        ):
            continue  # charged as the checklist requirement it is about
        needed = dependencies.get(finding["code"]) or ()
        if needed and not (set(needed) & present_types):
            continue  # the consequence of a document the claim does not have, already charged
        amount = amounts.get(f"finding_{finding['severity']}", 0)
        counted_findings.append(finding)
        if amount:
            deductions.append(
                _deduction(
                    f"Open {finding['severity']} finding: {finding['title']}",
                    amount,
                    "finding",
                    finding["id"],
                    finding["title"],
                    code=finding["code"],
                    severity=finding["severity"],
                )
            )
        if finding["severity"] in ("critical", "review"):
            blocking.append(
                {
                    "kind": "finding",
                    "key": finding["id"],
                    "label": finding["title"],
                    "detail": finding["severity"],
                    "action": finding["action"],
                }
            )

    total = sum(deduction["amount"] for deduction in deductions)
    score = max(floor, base - total)

    nothing_read = not present_types
    status = INCOMPLETE
    detail = config["statuses"][INCOMPLETE]
    if nothing_read or not checklist.get("available"):
        # Readiness measures the documentation against the procedure's checklist. With nothing
        # read, or no checklist to measure against, the claim is not ready for anything yet.
        detail = (
            "No document of this claim has been read yet."
            if nothing_read
            else (checklist.get("note") or "No checklist applies to this claim yet.")
        )
        blocking.append(
            {
                "kind": "requirement",
                "key": "documents" if nothing_read else "procedure",
                "label": "Documents to read" if nothing_read else "A procedure the documents name",
                "detail": detail,
                "action": "Upload the claim documents and run the analysis."
                if nothing_read
                else "Upload the documents that name the procedure.",
            }
        )
    elif still_reading:
        # Some of the claim has been read and some has not. Whatever the part that was read adds
        # up to, it is not the claim, so the claim is not ready for a person to decide on and the
        # score is not the score it will settle at.
        detail = (
            f"Waiting for {len(still_reading)} of {len(included)} documents to be read. "
            "Readiness is counted from the documents as they are read."
        )
        blocking.append(
            {
                "kind": "document",
                "key": "reading",
                "label": "Documents still being read",
                "detail": detail,
                "action": "Wait for the analysis to finish; readiness is counted again as each document is read.",
            }
        )
    elif missing_without_response:
        status = INCOMPLETE
    elif checklist_reviews or any(finding["severity"] in ("critical", "review") for finding in counted_findings):
        status = NEEDS_ATTENTION
        detail = config["statuses"][NEEDS_ATTENTION]
    else:
        status = READY_FOR_HUMAN_REVIEW
        detail = config["statuses"][READY_FOR_HUMAN_REVIEW]

    severity_counts = {severity: 0 for severity in ("critical", "review", "warning", "info")}
    for finding in counted_findings:
        severity_counts[finding["severity"]] = severity_counts.get(finding["severity"], 0) + 1

    return {
        "score": score,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "status_detail": detail,
        "breakdown": {
            "base_score": base,
            "deductions": deductions,
            "deducted": total,
            "final_score": score,
            "status": status,
        },
        "blocking_items": blocking,
        "summary": {
            "required_missing": missing_without_response,
            "documented_unavailable": documented_unavailable,
            "not_applicable": not_applicable,
            "checklist_reviews": checklist_reviews,
            "open_findings": len(active),
            "counted_findings": len(counted_findings),
            "findings_by_severity": severity_counts,
            "open_questions": sum(1 for question in questions if question["status"] in QUESTION_PENDING_STATUSES),
            "checklist_available": bool(checklist.get("available")),
        },
    }


def can_be_approved(readiness: dict) -> bool:
    """Approval is offered only where the documentation is no longer waiting for anything."""
    return readiness["status"] == READY_FOR_HUMAN_REVIEW
