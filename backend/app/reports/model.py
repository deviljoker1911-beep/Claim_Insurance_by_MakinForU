"""The claim pre-submission report: one assembly of what the claim already holds.

Nothing is decided here and nothing is calculated here. The report reads the canonical claim,
the findings the rules raised, the checks they ran, the procedure checklist, the questions and
their answers, the readiness the engine counted, the human review and the audit trail — and
arranges them for a reader. PDF, Excel and HTML all render this one payload, so the three can
never disagree with each other or with the claim.

Four kinds of statement are kept apart on purpose:

  documented facts   what the documents say, with the document and page it was read from
  system findings    what the deterministic rules concluded, with their evidence
  unresolved items   what the claim is still waiting for
  human decisions    what a person recorded: a finding dealt with, a question answered, an approval
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.models import FINDING_ACTIVE_STATUSES, AuditEvent, Claim, utcnow
from app.services import canonical as canonical_service
from app.services import reanalysis as reanalysis_service
from app.services import review as review_service
from app.services import validation as validation_service

REPORT_VERSION = 1
TITLE = "AI Claim Pre-Submission Validation Report"
DISCLAIMER = (
    "AI-generated validation assistance. Final claim submission requires authorized human review."
)
DEMO_NOTICE = (
    "Demo claim: the documents in it are synthetic and were generated for this prototype. "
    "No real patient record is used."
)
# Sections of the canonical claim that are reported as documented facts, in reading order.
FACT_SECTIONS = (
    ("patient", "Patient"),
    ("admission", "Admission and cover"),
    ("diagnosis", "Diagnosis"),
    ("doctors", "Doctors"),
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _sources(value: dict) -> list[dict]:
    return [
        {
            "document_name": source["document_name"],
            "document_type": source.get("document_type_label"),
            "page": source.get("page"),
            "method": source.get("source_type_label"),
            "value": source.get("value"),
        }
        for source in value.get("sources", [])
    ]


def _documented_facts(state: dict) -> list[dict]:
    """What the documents say, each value with where it was read from."""
    sections = []
    for key, label in FACT_SECTIONS:
        section = state.get(key) or {}
        values = []
        for value in section.get("fields", {}).values():
            values.append(
                {
                    "label": value["label"],
                    "value": value["value"],
                    "present": value["present"],
                    "source_count": value["source_count"],
                    "sources": _sources(value),
                    "competing_values": [
                        {"value": competing["value"], "source_count": competing["source_count"]}
                        for competing in value.get("competing_values", [])
                    ],
                    "note": value.get("note"),
                }
            )
        sections.append({"key": key, "label": label, "values": values})

    procedures = state.get("procedures") or {}
    sections.append(
        {
            "key": "procedures",
            "label": "Procedure",
            "values": [
                {
                    "label": "Procedure" if item.get("is_selected") else "Also named",
                    "value": item["label"],
                    "present": True,
                    "source_count": item["source_count"],
                    "sources": _sources(item),
                    "competing_values": [],
                    "note": None,
                }
                for item in procedures.get("items", [])
            ],
        }
    )
    return sections


def _findings(findings: list, state: dict) -> list[dict]:
    """Every finding the rules raised, with its evidence and what a person did about it."""
    rows = []
    for finding in findings:
        rows.append(
            {
                "id": finding.id,
                "code": finding.code,
                "rule_id": finding.rule_id,
                "category": finding.category,
                "severity": finding.severity,
                "status": finding.status,
                "is_active": finding.status in FINDING_ACTIVE_STATUSES,
                "title": finding.title,
                "explanation": finding.explanation,
                "action": finding.action,
                "attribution": finding.attribution,
                "subject": finding.subject,
                "occurrences": finding.occurrences,
                "first_seen_at": _iso(finding.first_seen_at),
                "last_seen_at": _iso(finding.last_seen_at),
                "evidence": [
                    {
                        "document_name": item.get("document_name"),
                        "page": item.get("page"),
                        "snippet": item.get("snippet"),
                        "method": item.get("method"),
                        "detail": item.get("detail"),
                        "value": item.get("value"),
                    }
                    for item in (finding.evidence or [])
                ],
                "decision": {
                    "status": finding.status,
                    "actor": finding.status_actor,
                    "note": finding.status_note,
                    "at": _iso(finding.status_changed_at),
                    "reviewed_by": finding.reviewed_by,
                    "reviewed_at": _iso(finding.reviewed_at),
                }
                if finding.status_actor or finding.reviewed_by
                else None,
            }
        )
    return rows


def _questions(state: dict) -> list[dict]:
    """What the claim asked for and what came back."""
    resolutions = {item["question_id"]: item for item in state["resolutions"]["items"]}
    rows = []
    for question in state["questions"]["items"]:
        resolution = resolutions.get(question["id"], {})
        rows.append(
            {
                "id": question["id"],
                "requirement_key": question["requirement_key"],
                "requirement_label": question["requirement_label"],
                "question": question["question"],
                "reason": question["reason"],
                "expected_document_type": question["expected_document_type"],
                "status": question["status"],
                "severity": question["severity"],
                "answer": resolution.get("answer"),
                "answer_reason": resolution.get("reason"),
                "answered_by": resolution.get("actor"),
                "answered_at": resolution.get("answered_at"),
                "resolved_document_id": question["resolved_document_id"],
                "created_at": question["created_at"],
            }
        )
    return rows


def _human_decisions(state: dict, findings: list[dict], questions: list[dict], claim: Claim) -> list[dict]:
    """Everything a person recorded, kept apart from what the system concluded."""
    decisions = []
    for finding in findings:
        decision = finding["decision"]
        if not decision or not (decision["actor"] or decision["reviewed_by"]):
            continue
        decisions.append(
            {
                "kind": "finding",
                "subject": finding["title"],
                "decision": finding["status"],
                "actor": decision["actor"] or decision["reviewed_by"],
                "at": decision["at"] or decision["reviewed_at"],
                "note": decision["note"],
                "reference": finding["code"],
            }
        )
    for question in questions:
        if not question["answer"]:
            continue
        decisions.append(
            {
                "kind": "question",
                "subject": question["requirement_label"],
                "decision": question["answer"],
                "actor": question["answered_by"],
                "at": question["answered_at"],
                "note": question["answer_reason"],
                "reference": question["requirement_key"],
            }
        )
    if claim.approved_at:
        decisions.append(
            {
                "kind": "approval",
                "subject": f"Claim {claim.claim_number}",
                "decision": claim.review_state,
                "actor": claim.approved_by,
                "at": _iso(claim.approved_at),
                "note": claim.approval_note,
                "reference": "human_approval",
            }
        )
    return sorted(decisions, key=lambda item: (item["at"] or "", item["kind"], item["subject"]))


def _unresolved(state: dict, questions: list[dict]) -> list[dict]:
    """What the claim is still waiting for, from the engines that are waiting for it."""
    items = [
        {
            "kind": item["kind"],
            "label": item["label"],
            "detail": item["detail"],
            "action": item["action"],
            "source": "readiness",
        }
        for item in state["readiness"]["blocking_items"]
    ]
    for question in questions:
        if question["status"] in ("open", "answered"):
            items.append(
                {
                    "kind": "question",
                    "label": question["requirement_label"],
                    "detail": question["question"],
                    "action": "Answer the request, or upload the document it asks for.",
                    "source": "questions",
                }
            )
    return items


def _documents(state: dict) -> list[dict]:
    return [
        {
            "filename": document["filename"],
            "doc_type": document["doc_type"],
            "doc_type_label": document["doc_type_label"],
            "classification_confidence": document["classification_confidence"],
            "page_count": document["page_count"],
            "processing_status": document["processing_status"],
            "text_source": document["text_source"],
            "ocr_engine": document["ocr_engine"],
            "quality_signals": [signal.get("code") for signal in document.get("quality_signals", [])],
            "quality_signal_count": document["quality_signal_count"],
            "concealed_text_count": document["concealed_text_count"],
            "unsigned_required_slots": document["unsigned_required_slots"],
            "extracted_field_count": document["extracted_field_count"],
            "excluded": document["excluded"],
            "exclusion_reason": document["exclusion_reason"],
            "duplicate_state": document["duplicate_state"],
            "sha256": document["sha256"],
            "size_bytes": document["size_bytes"],
            "source": document["source"],
            "uploaded_at": document["uploaded_at"],
        }
        for document in state["documents"]["items"]
    ]


def _bills(state: dict) -> dict:
    bills = state["bills"]
    return {
        "count": bills["count"],
        "items": [
            {
                "document_name": bill["document_name"],
                "bill_type_label": bill["bill_type_label"],
                "number": (bill["fields"].get("number") or {}).get("value"),
                "date": (bill["fields"].get("date") or {}).get("value"),
                "subtotal": (bill["fields"].get("subtotal") or {}).get("value"),
                "tax": (bill["fields"].get("tax") or {}).get("value"),
                "discount": (bill["fields"].get("discount") or {}).get("value"),
                "total": (bill["fields"].get("total") or {}).get("value"),
                "line_item_count": bill["line_item_count"],
                "currency": bill["currency"],
            }
            for bill in bills["items"]
        ],
        "note": bills.get("note"),
    }


def _audit(events: list[AuditEvent]) -> list[dict]:
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "actor": event.actor,
            "message": event.message,
            "document_id": event.document_id,
            "details": dict(event.details or {}),
            "created_at": _iso(event.created_at),
        }
        for event in events
    ]


def build(session: Session, claim: Claim, *, generated_at: datetime | None = None) -> dict:
    """The report payload for one claim, read from the state the earlier phases produced."""
    settings = get_settings()
    reanalysis_service.ensure_current(session, claim, actor=settings.operator_name)
    # The approval is checked against the claim as it stands before the report is written, so a
    # report can never show an approval the claim has moved past. The plain build is used for
    # that check: it is the JSON-ready state, without the snapshot bookkeeping.
    current = canonical_service.build(session, claim)
    review_service.refresh_approval(session, claim, current, current["readiness"])
    state = canonical_service.snapshot(session, claim)

    findings = validation_service.findings_for(session, claim.id)
    run = validation_service.stored_run(session, claim.id)
    events = list(
        session.scalars(
            select(AuditEvent).where(AuditEvent.claim_id == claim.id).order_by(AuditEvent.id)
        ).all()
    )

    finding_rows = _findings(findings, state)
    question_rows = _questions(state)
    readiness = state["readiness"]
    checklist = state["checklist"]

    return {
        "meta": {
            "report_version": REPORT_VERSION,
            "title": TITLE,
            "generated_at": _iso(generated_at or utcnow()),
            "claim_id": claim.id,
            "claim_number": claim.claim_number,
            "is_demo": bool(claim.is_demo),
            "disclaimer": DISCLAIMER,
            "demo_notice": DEMO_NOTICE if claim.is_demo else None,
            "generator": f"ClaimAI {__version__}",
            "content_sha256": state["snapshot"]["content_sha256"],
            "rules_version": run.rules_version if run else None,
            "checklist_version": checklist.get("checklist_version"),
            "generator_version": state["meta"]["generator_version"],
        },
        "claim": {
            "claim_number": claim.claim_number,
            "status": claim.status,
            "patient_name": claim.patient_name,
            "uhid": claim.uhid,
            "hospital": claim.hospital,
            "insurer": claim.insurer,
            "tpa": claim.tpa,
            "admission_date": claim.admission_date.isoformat(),
            "discharge_date": claim.discharge_date.isoformat(),
            "created_by": claim.created_by,
            "created_at": _iso(claim.created_at),
            "is_demo": bool(claim.is_demo),
        },
        "summary": {
            "readiness_score": readiness["score"],
            "readiness_status": readiness["status"],
            "readiness_status_label": readiness["status_label"],
            "review_state": state["review"]["state"],
            "documents": state["documents"]["count"],
            "documents_excluded": sum(1 for item in state["documents"]["items"] if item["excluded"]),
            "findings_total": state["findings"]["count"],
            "findings_open": state["findings"]["active"],
            "findings_by_severity": state["findings"]["by_severity"],
            "requirements_outstanding": checklist.get("summary", {}).get("required_outstanding", 0),
            "questions_open": state["questions"]["open"],
            "questions_total": state["questions"]["count"],
            "checks_total": len(run.checks or []) if run else 0,
            "bills": state["bills"]["count"],
            "audit_events": len(events),
        },
        "readiness": {
            "score": readiness["score"],
            "status": readiness["status"],
            "status_label": readiness["status_label"],
            "status_detail": readiness["status_detail"],
            "breakdown": readiness["breakdown"],
            "blocking_items": readiness["blocking_items"],
            "summary": readiness["summary"],
        },
        "review": {
            **state["review"],
            "approved_readiness": state["review"].get("approved_readiness", {}),
        },
        "documented_facts": _documented_facts(state),
        "system_findings": finding_rows,
        "validation_checks": list(run.checks or []) if run else [],
        "checklist": {
            "available": checklist.get("available", False),
            "procedure": checklist.get("procedure"),
            "note": checklist.get("note"),
            "summary": checklist.get("summary", {}),
            "items": [
                {
                    "key": item["key"],
                    "label": item["label"],
                    "status": item["status"],
                    "severity": item["severity"],
                    "required": item["required"],
                    "detail": item["detail"],
                    "resolution": item["resolution"],
                    "documents": [source["document_name"] for source in item["evidence"]],
                    "findings": [finding["code"] for finding in item["findings"]],
                }
                for item in checklist.get("items", [])
            ],
        },
        "questions": question_rows,
        "human_decisions": _human_decisions(state, finding_rows, question_rows, claim),
        "unresolved": _unresolved(state, question_rows),
        "documents": _documents(state),
        "bills": _bills(state),
        "investigations": [
            {
                "document_name": item["document_name"],
                "doc_type_label": item.get("doc_type_label"),
                "values": {
                    key: value.get("value") for key, value in item.get("fields", {}).items() if value.get("present")
                },
            }
            for item in state["investigations"]["items"]
        ],
        "audit_trail": _audit(events),
    }
