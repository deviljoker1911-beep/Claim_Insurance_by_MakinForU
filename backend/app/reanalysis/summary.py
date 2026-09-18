"""What one pass of analysis changed, as a comparison of two structured states.

Changes are read from the states themselves — documents, findings, checklist requirements,
canonical values and questions — never from rendered text. The same two states always produce
the same list of changes, in the same order.
"""

from __future__ import annotations

from app.canonical import keys as canonical_keys
from app.models import FINDING_ACTIVE_STATUSES

# The canonical values a change is worth reporting for: the ones a reviewer reads.
TRACKED_FIELDS = (
    "patient.name",
    "patient.uhid",
    "patient.ipd",
    "admission.admission_date",
    "admission.discharge_date",
    "admission.surgery_date",
    "diagnosis.primary",
    "diagnosis.icd10",
    "doctors.surgeon",
    "doctors.anaesthetist",
)

KIND_DOCUMENT = "document"
KIND_FINDING = "finding"
KIND_CHECKLIST = "checklist"
KIND_CANONICAL = "canonical"
KIND_QUESTION = "question"
KIND_PROCEDURE = "procedure"


# A document that has not been read yet has changed nothing about the claim, so it is not in
# the state a pass compares against: it appears in the pass that reads it, with its type.
SETTLED_DOCUMENT_STATES = ("processed", "failed")


def state_summary(state: dict, questions: list) -> dict:
    """The structured state a re-analysis is compared against."""
    documents = {
        document["document_id"]: {
            "filename": document["filename"],
            "doc_type": document["doc_type"],
            "doc_type_label": document["doc_type_label"],
            "excluded": bool(document["excluded"]),
            "processing_status": document["processing_status"],
        }
        for document in state["documents"]["items"]
        if document["processing_status"] in SETTLED_DOCUMENT_STATES
    }
    findings = {
        item["id"]: {
            "code": item["code"],
            "title": item["title"],
            "severity": item["severity"],
            "status": item["status"],
            "active": item["status"] in FINDING_ACTIVE_STATUSES,
        }
        for item in state["findings"]["items"]
    }
    checklist = {
        item["key"]: {"label": item["label"], "status": item["status"], "severity": item["severity"]}
        for item in state["checklist"]["items"]
    }
    canonical = {}
    for key in TRACKED_FIELDS:
        section, name = key.split(".", 1)
        value = state.get(section, {}).get("fields", {}).get(name)
        canonical[key] = {
            "label": (value or {}).get("label", name.replace("_", " ").title()),
            "value": (value or {}).get("value"),
        }
    return {
        "documents": documents,
        "findings": findings,
        "checklist": checklist,
        "canonical": canonical,
        "questions": {
            question.id: {
                "requirement": question.requirement_key,
                "label": question.requirement_label,
                "status": question.status,
            }
            for question in questions
        },
        "procedure": {
            "key": (state["checklist"].get("procedure") or {}).get("key"),
            "label": (state["checklist"].get("procedure") or {}).get("label"),
        },
    }


def _change(kind: str, key: str, label: str, before, after, headline: str, **extra) -> dict:
    return {"kind": kind, "key": key, "label": label, "before": before, "after": after, "headline": headline, **extra}


def diff(before: dict, after: dict) -> list[dict]:
    """Every change between two states, in a fixed order."""
    changes: list[dict] = []
    first_pass = not before

    old_documents = before.get("documents", {})
    for document_id, document in sorted(after.get("documents", {}).items(), key=lambda item: item[1]["filename"]):
        previous = old_documents.get(document_id)
        if previous is None:
            changes.append(
                _change(
                    KIND_DOCUMENT,
                    document_id,
                    document["filename"],
                    None,
                    document["doc_type_label"] or document["doc_type"] or "unclassified",
                    f"{document['filename']} added"
                    + (f" and read as {document['doc_type_label'].lower()}" if document["doc_type_label"] else ""),
                    document_id=document_id,
                )
            )
        elif previous["excluded"] != document["excluded"] and document["excluded"]:
            changes.append(
                _change(
                    KIND_DOCUMENT,
                    document_id,
                    document["filename"],
                    "in the claim",
                    "excluded as a duplicate",
                    f"{document['filename']} excluded as a duplicate",
                    document_id=document_id,
                )
            )

    old_findings = before.get("findings", {})
    for finding_id, finding in sorted(after.get("findings", {}).items(), key=lambda item: (item[1]["code"], item[0])):
        previous = old_findings.get(finding_id)
        if previous is None:
            if first_pass:
                continue
            changes.append(
                _change(
                    KIND_FINDING,
                    finding_id,
                    finding["title"],
                    None,
                    finding["status"],
                    f"{finding['title']}: raised",
                    finding_id=finding_id,
                    code=finding["code"],
                    severity=finding["severity"],
                )
            )
        elif previous["status"] != finding["status"]:
            changes.append(
                _change(
                    KIND_FINDING,
                    finding_id,
                    finding["title"],
                    previous["status"],
                    finding["status"],
                    f"{finding['title']}: {_phrase(previous['status'])} → {_phrase(finding['status'])}",
                    finding_id=finding_id,
                    code=finding["code"],
                    severity=finding["severity"],
                )
            )

    old_checklist = before.get("checklist", {})
    for key, item in sorted(after.get("checklist", {}).items()):
        previous = old_checklist.get(key)
        if previous is None or previous["status"] == item["status"]:
            continue
        changes.append(
            _change(
                KIND_CHECKLIST,
                key,
                item["label"],
                previous["status"],
                item["status"],
                f"{item['label']}: {_phrase(previous['status'])} → {_phrase(item['status'])}",
                severity=item["severity"],
            )
        )

    old_canonical = before.get("canonical", {})
    for key, item in sorted(after.get("canonical", {}).items()):
        previous = old_canonical.get(key)
        if previous is None or previous["value"] == item["value"]:
            continue
        changes.append(
            _change(
                KIND_CANONICAL,
                key,
                item["label"],
                previous["value"],
                item["value"],
                f"{item['label']}: {previous['value'] or 'not documented'} → {item['value'] or 'not documented'}",
            )
        )

    old_questions = before.get("questions", {})
    for question_id, question in sorted(after.get("questions", {}).items(), key=lambda item: item[1]["requirement"]):
        previous = old_questions.get(question_id)
        if previous is None:
            changes.append(
                _change(
                    KIND_QUESTION,
                    question_id,
                    question["label"],
                    None,
                    question["status"],
                    f"{question['label']}: asked for",
                    question_id=question_id,
                    requirement=question["requirement"],
                )
            )
        elif previous["status"] != question["status"]:
            changes.append(
                _change(
                    KIND_QUESTION,
                    question_id,
                    question["label"],
                    previous["status"],
                    question["status"],
                    f"{question['label']} question: {_phrase(previous['status'])} → {_phrase(question['status'])}",
                    question_id=question_id,
                    requirement=question["requirement"],
                )
            )

    old_procedure = (before.get("procedure") or {}).get("key")
    new_procedure = (after.get("procedure") or {}).get("key")
    if old_procedure != new_procedure and not first_pass:
        changes.append(
            _change(
                KIND_PROCEDURE,
                "procedure",
                "Procedure",
                old_procedure,
                new_procedure,
                f"Procedure: {old_procedure or 'not named'} → {new_procedure or 'not named'}",
            )
        )
    return changes


def summarise(changes: list[dict], after: dict) -> dict:
    """Counts a reviewer can read at a glance, each one taken from the changes themselves."""
    findings = [change for change in changes if change["kind"] == KIND_FINDING]
    questions = [change for change in changes if change["kind"] == KIND_QUESTION]
    checklist = [change for change in changes if change["kind"] == KIND_CHECKLIST]
    return {
        "changes": len(changes),
        "documents_added": sum(1 for change in changes if change["kind"] == KIND_DOCUMENT and change["before"] is None),
        "findings_opened": sum(1 for change in findings if change["after"] in FINDING_ACTIVE_STATUSES and change["before"] not in FINDING_ACTIVE_STATUSES),
        "findings_auto_closed": sum(1 for change in findings if change["after"] == "auto_closed"),
        "questions_asked": sum(1 for change in questions if change["before"] is None),
        "questions_resolved": sum(1 for change in questions if change["after"] == "resolved"),
        "checklist_changed": len(checklist),
        "canonical_changed": sum(1 for change in changes if change["kind"] == KIND_CANONICAL),
        "outstanding_requirements": sum(
            1 for item in after.get("checklist", {}).values() if item["status"] in ("missing", "review_required")
        ),
    }


_PHRASES = {
    "auto_closed": "closed automatically",
    "documented_unavailable": "documented unavailable",
    "not_applicable": "not applicable",
    "review_required": "review required",
}


def _phrase(status: str | None) -> str:
    if status is None:
        return "not present"
    return _PHRASES.get(status, status.replace("_", " "))


# Kept so the tracked fields stay in step with the canonical field map.
def tracked_fields_exist() -> bool:
    known = {field.key for fields in canonical_keys.FIELDS_BY_SECTION.values() for field in fields}
    return all(key in known for key in TRACKED_FIELDS)
