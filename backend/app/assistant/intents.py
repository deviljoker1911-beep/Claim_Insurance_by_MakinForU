"""What the operator asked, and the answer the claim itself supports.

Each intent has one composer that writes from the claim and cites what it used. The wording
states what the documents show and what a person should look at; it never concludes anything
about the treatment, the patient or whether the claim will be accepted.
"""

from __future__ import annotations

import json

from app.assistant.context import ClaimContext
from app.readiness.workflow import plural

MISSING_DOCUMENTS = "missing_documents"
OPEN_ISSUES = "open_issues"
DOCUMENTATION_STATE = "documentation_state"
NEXT_STEPS = "next_steps"
BILLING = "billing"
DOCUMENTS = "documents"
SUMMARY = "summary"
CHANGES = "changes"
UNKNOWN = "unknown"

INTENTS = (
    MISSING_DOCUMENTS,
    OPEN_ISSUES,
    DOCUMENTATION_STATE,
    NEXT_STEPS,
    BILLING,
    DOCUMENTS,
    SUMMARY,
    CHANGES,
)

SUGGESTED_QUESTIONS = (
    "What documents are missing?",
    "What issues need my attention?",
    "What changed after my last upload?",
    "Summarise this claim.",
    "Explain the billing concerns.",
    "What should I do next?",
)

# Ordered: the first intent whose words appear decides. Kept small and legible on purpose.
_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CHANGES, ("what changed", "changed after", "since i uploaded", "re-analysis", "reanalysis", "what has changed")),
    (MISSING_DOCUMENTS, ("missing", "not uploaded", "what do you need", "what is needed", "outstanding document")),
    (BILLING, ("bill", "billing", "amount", "charge", "invoice", "tariff", "total")),
    (OPEN_ISSUES, ("issue", "problem", "attention", "finding", "wrong", "mismatch", "discrepan")),
    (NEXT_STEPS, ("next step", "what should i do", "what do i do", "how do i proceed", "what now")),
    (DOCUMENTATION_STATE, ("ready", "readiness", "complete", "completeness", "state of", "how complete")),
    (DOCUMENTS, ("document", "uploaded", "file", "what do we have", "which papers")),
    (SUMMARY, ("summar", "overview", "tell me about", "brief")),
)


def classify(question: str) -> str:
    """Which intent a question is asking for."""
    text = " ".join(question.lower().split())
    for intent, words in _KEYWORDS:
        if any(word in text for word in words):
            return intent
    return UNKNOWN


def _document_citation(context: ClaimContext, document_id: str) -> str:
    return f"[[document:{document_id}]]"


def _claim_line(context: ClaimContext) -> str:
    who = context.patient_name or "the patient named in the documents"
    procedure = f" for {context.procedure_label.lower()}" if context.procedure_label else ""
    dates = ""
    if context.admission_date and context.discharge_date:
        dates = f", admitted {context.admission_date} and discharged {context.discharge_date}"
    return f"Claim {context.claim_number} documents {who}{procedure}{dates}. [[claim:{context.claim_id}]]"


def _missing(context: ClaimContext) -> str:
    missing = [item for item in context.missing_requirements if item["required"]]
    supporting = [item for item in context.missing_requirements if not item["required"]]
    if not context.checklist_available:
        return (
            "No procedure checklist applies to this claim yet, so there is no list of expected "
            f"documents to compare against. {plural(len(context.documents), 'document')} read so far."
        )
    if not missing and not supporting:
        return (
            f"Every document the {context.procedure_label.lower()} checklist expects is in the claim. "
            f"{len(context.review_requirements)} of them carry an open finding, so a person still needs to look."
        )
    lines = []
    if missing:
        lines.append("The documents the checklist expects and the claim does not have:")
        for item in missing:
            question = next(
                (q for q in context.open_questions if q["requirement_key"] == item["key"]),
                None,
            )
            marker = f" [[question:{question['id']}]]" if question else ""
            lines.append(f"- {item['label']} ({item['severity']}) — {item['resolution']} [[requirement:{item['key']}]]{marker}")
    if supporting:
        names = ", ".join(item["label"] for item in supporting)
        lines.append(f"Supporting documents not in the claim: {names}.")
    return "\n".join(lines)


def _issues(context: ClaimContext) -> str:
    active = context.active_findings
    if not active:
        if not context.findings:
            return "No finding has been raised on this claim: the rules found nothing to report."
        return (
            "No finding is open on this claim. "
            f"{plural(len(context.findings), 'finding')} raised in total, and each has been dealt with."
        )
    by_severity: dict[str, list[dict]] = {}
    for finding in active:
        by_severity.setdefault(finding["severity"], []).append(finding)
    lines = [f"{plural(len(active), 'finding')} open and waiting for a person to look at:"]
    for severity in ("critical", "review", "warning", "info"):
        for finding in by_severity.get(severity, []):
            lines.append(f"- {finding['title']} ({severity}) — {finding['action']} [[finding:{finding['id']}]]")
    return "\n".join(lines)


def _documentation_state(context: ClaimContext) -> str:
    if not context.checklist_available:
        return (
            f"{plural(len(context.documents), 'document')} read. No procedure checklist applies to this "
            "claim yet, so the documentation cannot be measured against one."
        )
    found = [item for item in context.checklist if item["status"] == "found"]
    missing = [item for item in context.checklist if item["status"] == "missing" and item["required"]]
    review = context.review_requirements
    lines = [
        f"Against the {context.procedure_label.lower()} checklist, {len(found)} of {len(context.checklist)} "
        f"requirements are covered by a document, {len(missing)} required ones are not in the claim, and "
        f"{len(review)} carry an open finding.",
    ]
    if missing:
        lines.append("Not in the claim: " + ", ".join(f"{item['label']} [[requirement:{item['key']}]]" for item in missing) + ".")
    if review:
        lines.append("Present but needing review: " + ", ".join(f"{item['label']} [[requirement:{item['key']}]]" for item in review) + ".")
    lines.append(
        "This describes the documentation only. Whether the claim is complete enough to send is a "
        "decision for the person reviewing it."
    )
    return "\n".join(lines)


def _next_steps(context: ClaimContext) -> str:
    steps: list[str] = []
    for question in context.open_questions:
        steps.append(
            f"- Answer the request for the {question['requirement_label'].lower()}: "
            f"{question['question']} [[question:{question['id']}]]"
        )
    for finding in context.active_findings:
        if finding["severity"] in ("critical", "review"):
            steps.append(f"- {finding['action']} [[finding:{finding['id']}]]")
    if not steps:
        return (
            "Nothing is outstanding on this claim: no question is open and no finding needs attention. "
            "A person still reviews it before it goes anywhere."
        )
    lines = ["What is outstanding, in the order the claim raised it:"]
    lines.extend(steps[:8])
    if len(steps) > 8:
        lines.append(f"- and {plural(len(steps) - 8, 'more open item')}.")
    return "\n".join(lines)


def _billing(context: ClaimContext) -> str:
    if not context.bills:
        return "No bill has been read for this claim yet."
    lines = [f"{plural(len(context.bills), 'bill')} read:"]
    for bill in context.bills:
        total = bill["total"] or "no total read"
        number = bill["number"] or "no number read"
        lines.append(
            f"- {bill['bill_type_label'] or 'Bill'} {bill['document_name']}: total {total}, "
            f"number {number} {_document_citation(context, bill['document_id'])}"
        )
    billing_findings = context.billing_findings
    if billing_findings:
        lines.append("Open billing findings:")
        for finding in billing_findings:
            lines.append(f"- {finding['title']} — {finding['action']} [[finding:{finding['id']}]]")
    else:
        lines.append("No billing finding is open on these bills.")
    return "\n".join(lines)


def _documents(context: ClaimContext) -> str:
    usable = [document for document in context.documents if not document["excluded"]]
    excluded = [document for document in context.documents if document["excluded"]]
    lines = [f"{plural(len(usable), 'document')} in this claim:"]
    for document in usable[:20]:
        kind = document["doc_type_label"] or "not classified"
        lines.append(f"- {document['filename']} — {kind} {_document_citation(context, document['document_id'])}")
    if len(usable) > 20:
        lines.append(f"- and {len(usable) - 20} more.")
    if excluded:
        names = ", ".join(document["filename"] for document in excluded)
        lines.append(f"Excluded as duplicates and supplying no values: {names}.")
    return "\n".join(lines)


def _summary(context: ClaimContext) -> str:
    lines = [_claim_line(context)]
    lines.append(
        f"{plural(len([d for d in context.documents if not d['excluded']]), 'document')} read and "
        f"{plural(len(context.active_findings), 'finding')} open."
    )
    if context.checklist_available:
        missing = [item for item in context.checklist if item["status"] == "missing" and item["required"]]
        lines.append(
            f"The {context.procedure_label.lower()} checklist has {plural(len(missing), 'required document')} outstanding "
            f"and {plural(len(context.review_requirements), 'requirement')} a person should look at."
        )
    if context.open_questions:
        lines.append(f"{plural(len(context.open_questions), 'question')} waiting for an answer from you.")
    lines.append("Every statement here comes from the documents in the claim; a person makes the decision.")
    return "\n".join(lines)


def _changes(context: ClaimContext) -> str:
    if not context.last_changes:
        return "Nothing has changed since the last analysis of this claim."
    summary = context.last_change_summary
    lines = [
        f"The last analysis made {plural(summary.get('changes', len(context.last_changes)), 'change')}: "
        f"{plural(summary.get('documents_added', 0), 'document')} added, "
        f"{plural(summary.get('questions_resolved', 0), 'question')} resolved, "
        f"{plural(summary.get('findings_auto_closed', 0), 'finding')} closed automatically."
    ]
    for change in context.last_changes[:8]:
        marker = ""
        if change.get("document_id"):
            marker = f" [[document:{change['document_id']}]]"
        elif change.get("finding_id"):
            marker = f" [[finding:{change['finding_id']}]]"
        elif change["kind"] == "checklist":
            marker = f" [[requirement:{change['key']}]]"
        elif change.get("question_id"):
            marker = f" [[question:{change['question_id']}]]"
        lines.append(f"- {change['headline']}{marker}")
    return "\n".join(lines)


_COMPOSERS = {
    MISSING_DOCUMENTS: _missing,
    OPEN_ISSUES: _issues,
    DOCUMENTATION_STATE: _documentation_state,
    NEXT_STEPS: _next_steps,
    BILLING: _billing,
    DOCUMENTS: _documents,
    SUMMARY: _summary,
    CHANGES: _changes,
}


def compose(intent: str, context: ClaimContext) -> str:
    """The answer for an intent, written from the claim."""
    composer = _COMPOSERS.get(intent)
    if composer is None:
        return (
            "I can answer from this claim's documents, findings, checklist and questions. "
            "Ask what is missing, what needs attention, what changed, about the bills or the documents, "
            "or for a summary.\n\n" + _summary(context)
        )
    return composer(context)


def prompt(question: str, intent: str, context: ClaimContext) -> str:
    """The grounded context a model is given, and the question to answer from it."""
    payload = {
        "claim": {
            "claim_id": context.claim_id,
            "claim_number": context.claim_number,
            "patient_name": context.patient_name,
            "uhid": context.uhid,
            "admission_date": context.admission_date,
            "discharge_date": context.discharge_date,
            "procedure": context.procedure_label,
        },
        "documents": context.documents,
        "findings": context.findings,
        "checklist": context.checklist,
        "questions": context.questions,
        "bills": context.bills,
        "last_changes": context.last_changes[:10],
    }
    return (
        f"CLAIM CONTEXT (the only facts you may use):\n{json.dumps(payload, indent=1, sort_keys=True)}\n\n"
        f"The operator asks: {question}\n"
        f"The intent detected for this question is: {intent}\n"
        "Answer from the context above, and cite the ids you relied on."
    )
