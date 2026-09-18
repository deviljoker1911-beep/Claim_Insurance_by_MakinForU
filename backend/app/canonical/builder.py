"""Assembling the canonical claim from the processed documents of one claim.

Every value in the result comes from a Phase 3 extracted field: nothing is restated here,
and nothing is filled in from the claim form or from knowledge of the demo data. A value the
documents do not carry is reported as absent.

The result is a plain JSON-serialisable dictionary, ordered and rounded so that building it
twice from the same stored state produces exactly the same document.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.classify import type_label
from app.checklist import engine as checklist_engine
from app.readiness import engine as readiness_engine
from app.canonical import keys as canonical_keys
from app.canonical.selection import (
    Candidate,
    absent,
    document_weight,
    eligibility,
    normalise,
    select_value,
)
from app.config_files import canonical_config
from app.models import (
    AuditEvent,
    Claim,
    Document,
    DocumentBill,
    ExtractedField,
    FINDING_ACTIVE_STATUSES,
    Finding,
    QUESTION_PENDING_STATUSES,
    Question,
    SEVERITIES,
)
from app.services import analysis as analysis_service


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _candidates(
    spec: canonical_keys.CanonicalField,
    fields: list[ExtractedField],
    documents: dict[str, Document],
    *,
    document_id: str | None = None,
) -> list[Candidate]:
    """Every extracted value offered for one canonical field."""
    out: list[Candidate] = []
    for row in fields:
        if row.field_key not in spec.sources:
            continue
        if document_id is not None and row.document_id != document_id:
            continue
        document = documents.get(row.document_id)
        if document is None or document.excluded:
            # A document excluded from the claim (a duplicate copy, say) no longer states values.
            continue
        details = row.details or {}
        value = details.get(spec.detail_key) if spec.detail_key else row.value_text
        if value is None or str(value).strip() == "":
            continue
        value = str(value)
        is_eligible, reason = eligibility(row.method, row.confidence or 0.0)
        out.append(
            Candidate(
                document_id=document.id,
                document_name=document.original_filename,
                document_type=document.doc_type,
                document_type_label=type_label(document.doc_type) if document.doc_type else None,
                weight=document_weight(document.doc_type),
                field_key=row.field_key,
                value=value,
                raw_value=row.value_raw,
                normalized=normalise(spec.kind, value),
                page=row.page_number,
                bounding_box=list(row.bbox) if row.bbox else None,
                snippet=row.snippet,
                method=row.method,
                confidence=float(row.confidence or 0.0),
                eligible=is_eligible,
                excluded_reason=reason,
                derived_from=row.field_key if spec.detail_key else None,
                details=details,
            )
        )
    return out


def _value(
    spec: canonical_keys.CanonicalField,
    fields: list[ExtractedField],
    documents: dict[str, Document],
    *,
    document_id: str | None = None,
) -> dict:
    candidates = _candidates(spec, fields, documents, document_id=document_id)
    return select_value(spec, candidates) if candidates else absent(spec)


def _section(
    section: str, fields: list[ExtractedField], documents: dict[str, Document]
) -> dict:
    values = {
        spec.name: _value(spec, fields, documents)
        for spec in canonical_keys.FIELDS_BY_SECTION.get(section, ())
    }
    return {
        "fields": values,
        "present_count": sum(1 for value in values.values() if value["present"]),
        "field_count": len(values),
    }


def _procedures(fields: list[ExtractedField], documents: dict[str, Document]) -> dict:
    """The procedures the documents name, grouped by the procedure they mean.

    "Lap Chole" and "Laparoscopic Cholecystectomy" are the same operation, so they form one
    entry with both documents as sources. A genuinely different procedure forms its own entry.
    """
    spec = canonical_keys.PROCEDURE_FIELD
    candidates = _candidates(spec, fields, documents)
    labels: dict[str, tuple[str | None, str | None]] = {}
    for candidate in candidates:
        if candidate.normalized and candidate.normalized not in labels:
            labels[candidate.normalized] = (
                candidate.details.get("procedure_key"),
                candidate.details.get("procedure_label"),
            )

    if not candidates:
        return {
            "selected_key": None,
            "items": [],
            "fields": {
                spec.name: _value(spec, fields, documents)
                for spec in canonical_keys.FIELDS_BY_SECTION.get("procedures", ())
            },
        }

    chosen = select_value(spec, candidates)
    groups = [chosen, *chosen["competing_values"]] if chosen["present"] else chosen["competing_values"]
    items = []
    for index, group in enumerate(groups):
        procedure_key, procedure_label = labels.get(group["normalized_value"], (None, None))
        items.append(
            {
                "procedure_key": procedure_key,
                "label": procedure_label or group["value"],
                "value": group["value"],
                "normalized_value": group["normalized_value"],
                "weight": group["weight"],
                "source_count": group["source_count"],
                "value_variants": group["value_variants"],
                "sources": group["sources"],
                "is_selected": index == 0 and chosen["present"],
            }
        )
    return {
        "selected_key": items[0]["normalized_value"] if items and items[0]["is_selected"] else None,
        "selected": chosen,
        "items": items,
        "fields": {
            field.name: _value(field, fields, documents)
            for field in canonical_keys.FIELDS_BY_SECTION.get("procedures", ())
        },
    }


def _documents_section(documents: list[Document], fields: list[ExtractedField]) -> dict:
    field_counts: dict[str, int] = {}
    for row in fields:
        field_counts[row.document_id] = field_counts.get(row.document_id, 0) + 1
    items = []
    for document in documents:
        signatures = (document.signature_slots or {}).get("slots", [])
        items.append(
            {
                "document_id": document.id,
                "filename": document.original_filename,
                "doc_type": document.doc_type,
                "doc_type_label": type_label(document.doc_type) if document.doc_type else None,
                "classification_confidence": document.doc_type_confidence,
                "classification_method": document.classification_method,
                "processing_status": document.processing_status,
                "processing_stage": document.processing_stage,
                "processing_error": document.processing_error,
                "page_count": document.page_count,
                "quality_signals": list(document.quality_flags or []),
                "quality_signal_count": len(document.quality_flags or []),
                "ocr_method": document.ocr_engine or document.text_source,
                "ocr_engine": document.ocr_engine,
                "ocr_confidence": document.ocr_confidence,
                "text_source": document.text_source,
                "concealed_text_count": len(document.concealed_spans or []),
                "unsigned_required_slots": [
                    slot.get("label")
                    for slot in signatures
                    if slot.get("required") and slot.get("checked") and not slot.get("signed")
                ],
                "extracted_field_count": field_counts.get(document.id, 0),
                "source": document.source,
                "demo_set": document.demo_set,
                "sha256": document.sha256,
                "size_bytes": document.size_bytes,
                "uploaded_at": _iso(document.uploaded_at),
                "excluded": bool(document.excluded),
                "exclusion_reason": document.exclusion_reason,
                "duplicate_of": document.duplicate_of,
                "duplicate_state": document.duplicate_state,
            }
        )
    return {
        "count": len(items),
        "items": items,
        "by_type": {
            doc_type: sum(1 for item in items if item["doc_type"] == doc_type)
            for doc_type in sorted({item["doc_type"] for item in items if item["doc_type"]})
        },
        "excluded_count": sum(1 for item in items if item["excluded"]),
        "note": "An excluded document stays in the claim record but no longer states values.",
    }


def _investigations(documents: list[Document], fields: list[ExtractedField], by_id: dict[str, Document]) -> dict:
    items = []
    for document in documents:
        if document.excluded or document.doc_type not in canonical_keys.INVESTIGATION_DOC_TYPES:
            continue
        values = {
            spec.name: _value(spec, fields, by_id, document_id=document.id)
            for spec in canonical_keys.INVESTIGATION_FIELDS
        }
        items.append(
            {
                "document_id": document.id,
                "document_name": document.original_filename,
                "doc_type": document.doc_type,
                "doc_type_label": type_label(document.doc_type),
                "page_count": document.page_count,
                "fields": values,
            }
        )
    return {"count": len(items), "items": items}


def _bills(bills: list[DocumentBill], fields: list[ExtractedField], by_id: dict[str, Document]) -> dict:
    items = []
    for bill in sorted(bills, key=lambda row: (by_id[row.document_id].original_filename if row.document_id in by_id else "")):
        document = by_id.get(bill.document_id)
        if document is None or document.excluded:
            # An excluded document states nothing: not its values, and not its bill.
            continue
        values = {
            spec.name.removeprefix("bill_"): _value(spec, fields, by_id, document_id=document.id)
            for spec in canonical_keys.BILL_FIELDS
        }
        line_items = []
        for line in bill.line_items or []:
            line_items.append(
                {
                    "line_no": line.get("line_no"),
                    "description": line.get("description"),
                    "quantity": line.get("quantity"),
                    "rate": line.get("rate"),
                    "amount": line.get("amount"),
                    "batch": line.get("batch"),
                    "expiry": line.get("expiry"),
                    "evidence": {
                        "document_id": document.id,
                        "document_name": document.original_filename,
                        "document_type": document.doc_type,
                        "page": line.get("page_number"),
                        "bounding_box": line.get("bbox"),
                        "snippet": line.get("snippet"),
                        "method": "bill_table",
                        "source_type": document.text_source or "unknown",
                        "confidence": None,
                        "evidence_available": bool(line.get("page_number") and line.get("bbox")),
                    },
                }
            )
        items.append(
            {
                "document_id": document.id,
                "document_name": document.original_filename,
                "bill_type": bill.bill_type,
                "bill_type_label": type_label(bill.bill_type) if bill.bill_type else None,
                "currency": bill.currency,
                "page_number": bill.page_number,
                "columns": list(bill.columns or []),
                "notes": list(bill.notes or []),
                "line_item_count": len(line_items),
                "line_items": line_items,
                "fields": values,
            }
        )
    return {
        "count": len(items),
        "items": items,
        "summary": {
            "by_type": {
                bill_type: sum(1 for item in items if item["bill_type"] == bill_type)
                for bill_type in sorted({item["bill_type"] for item in items if item["bill_type"]})
            },
            # Per-bill totals as extracted. Arithmetic checks across bills belong to phase 5.
            "totals": [
                {
                    "document_id": item["document_id"],
                    "document_name": item["document_name"],
                    "bill_type": item["bill_type"],
                    "bill_type_label": item["bill_type_label"],
                    "bill_number": item["fields"]["number"]["value"],
                    "bill_date": item["fields"]["date"]["value"],
                    "total": item["fields"]["total"]["value"],
                    "currency": item["currency"],
                }
                for item in items
            ],
        },
        "note": "Totals are reported as extracted; cross-checking them is phase 5.",
    }


def _findings_section(findings: list[Finding]) -> dict:
    """The findings of this claim as they stand. The rules that raise them run in phase 5."""
    by_severity = {severity: 0 for severity in SEVERITIES}
    active_by_severity = {severity: 0 for severity in SEVERITIES}
    by_status: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        by_status[finding.status] = by_status.get(finding.status, 0) + 1
        if finding.status in FINDING_ACTIVE_STATUSES:
            active_by_severity[finding.severity] = active_by_severity.get(finding.severity, 0) + 1
    order = {severity: index for index, severity in enumerate(SEVERITIES)}
    ordered = sorted(
        findings,
        key=lambda finding: (
            0 if finding.status in FINDING_ACTIVE_STATUSES else 1,
            order.get(finding.severity, 9),
            finding.rule_id,
            finding.subject,
        ),
    )
    return {
        "available": True,
        "count": len(findings),
        "active": sum(active_by_severity.values()),
        "by_severity": by_severity,
        "active_by_severity": active_by_severity,
        "by_status": dict(sorted(by_status.items())),
        "items": [
            {
                "id": finding.id,
                "rule_id": finding.rule_id,
                "code": finding.code,
                "category": finding.category,
                "severity": finding.severity,
                "status": finding.status,
                "title": finding.title,
                "action": finding.action,
                "subject": finding.subject,
                "attribution": finding.attribution,
                "evidence_count": len(finding.evidence or []),
            }
            for finding in ordered
        ],
    }


def _finding_refs(findings: list[Finding]) -> list[dict]:
    """What the checklist needs in order to link a requirement to the findings about it."""
    return [
        {
            "id": finding.id,
            "rule_id": finding.rule_id,
            "code": finding.code,
            "severity": finding.severity,
            "status": finding.status,
            "title": finding.title,
            "subject": finding.subject,
            "is_active": finding.status in FINDING_ACTIVE_STATUSES,
            "document_ids": sorted(
                {item.get("document_id") for item in (finding.evidence or []) if item.get("document_id")}
            ),
        }
        for finding in sorted(findings, key=lambda row: (row.rule_id, row.subject))
    ]


def _questions_section(questions: list[Question]) -> dict:
    """The requests made to the operator and where each one stands."""
    by_status: dict[str, int] = {}
    for question in questions:
        by_status[question.status] = by_status.get(question.status, 0) + 1
    return {
        "available": True,
        "count": len(questions),
        "open": sum(1 for question in questions if question.status in QUESTION_PENDING_STATUSES),
        "by_status": dict(sorted(by_status.items())),
        "items": [
            {
                "id": question.id,
                "requirement_key": question.requirement_key,
                "requirement_label": question.requirement_label,
                "question": question.question,
                "reason": question.reason,
                "status": question.status,
                "severity": question.severity,
                "expected_document_type": question.expected_document_type,
                "answer": question.answer,
                "answer_reason": question.answer_reason,
                "resolved_document_id": question.resolved_document_id,
                "created_at": _iso(question.created_at),
                "updated_at": _iso(question.updated_at),
            }
            for question in questions
        ],
    }


def _resolutions_section(questions: list[Question]) -> dict:
    """What a person answered, kept as they gave it."""
    answered = [question for question in questions if question.answer or question.answer_reason]
    return {
        "available": True,
        "count": len(answered),
        "items": [
            {
                "question_id": question.id,
                "requirement_key": question.requirement_key,
                "requirement_label": question.requirement_label,
                "answer": question.answer,
                "reason": question.answer_reason,
                "status": question.status,
                "actor": question.answered_by,
                "answered_at": _iso(question.answered_at),
                "resolved_document_id": question.resolved_document_id,
                "resolved_at": _iso(question.resolved_at),
            }
            for question in answered
        ],
    }


def _audit_events(events: list[AuditEvent]) -> dict:
    limit = int(canonical_config().get("max_audit_events", 100))
    tail = events[-limit:]
    return {
        "count": len(events),
        "included": len(tail),
        "items": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "actor": event.actor,
                "message": event.message,
                "document_id": event.document_id,
                "created_at": _iso(event.created_at),
            }
            for event in tail
        ],
    }


def build_claim_state(session: Session, claim: Claim) -> dict:
    """Build the canonical claim for one claim from its processed documents."""
    documents = list(
        session.scalars(
            select(Document)
            .where(Document.claim_id == claim.id)
            .order_by(Document.uploaded_at, Document.original_filename)
        ).all()
    )
    by_id = {document.id: document for document in documents}
    fields = list(
        session.scalars(
            select(ExtractedField).where(ExtractedField.claim_id == claim.id).order_by(ExtractedField.id)
        ).all()
    )
    bills = list(session.scalars(select(DocumentBill).where(DocumentBill.claim_id == claim.id)).all())
    events = list(
        session.scalars(select(AuditEvent).where(AuditEvent.claim_id == claim.id).order_by(AuditEvent.id)).all()
    )
    findings = list(session.scalars(select(Finding).where(Finding.claim_id == claim.id)).all())
    questions = list(
        session.scalars(
            select(Question).where(Question.claim_id == claim.id).order_by(Question.created_at, Question.requirement_key)
        ).all()
    )

    counts = {status: 0 for status in ("pending", "queued", "processing", "processed", "failed")}
    for document in documents:
        counts[document.processing_status] = counts.get(document.processing_status, 0) + 1
    config = canonical_config()

    state: dict = {
        "claim": {
            "claim_id": claim.id,
            "claim_number": claim.claim_number,
            "status": claim.status,
            "is_demo": claim.is_demo,
            "hospital": claim.hospital,
            "insurer": claim.insurer,
            "tpa": claim.tpa,
            "created_by": claim.created_by,
            "created_at": _iso(claim.created_at),
            # What the operator entered when the claim was created, kept separate from what
            # the documents say so the two can be compared in phase 5.
            "form": {
                "patient_name": claim.patient_name,
                "uhid": claim.uhid,
                "hospital": claim.hospital,
                "insurer": claim.insurer,
                "tpa": claim.tpa,
                "admission_date": _iso(claim.admission_date),
                "discharge_date": _iso(claim.discharge_date),
            },
        },
        "meta": {
            "generator_version": int(config.get("generator_version", 1)),
            "analysis_state": analysis_service.analysis_state(counts),
            "document_counts": counts,
            "value_selection": {
                "document_weights": dict(sorted(config["document_weights"].items())),
                "default_weight": int(config["default_weight"]),
                "ocr_confidence_floor": float(config["ocr_confidence_floor"]),
                "rule": (
                    "Values are compared in a normalised form. Each supporting document contributes its "
                    "weight; every source stays listed, and OCR values below the confidence floor are "
                    "listed but excluded from selection."
                ),
            },
            "pending_sections": dict(sorted(canonical_keys.PENDING_SECTIONS.items())),
        },
        "patient": _section("patient", fields, by_id),
        "admission": _section("admission", fields, by_id),
        "diagnosis": _section("diagnosis", fields, by_id),
        "procedures": _procedures(fields, by_id),
        "doctors": _section("doctors", fields, by_id),
        "investigations": _investigations(documents, fields, by_id),
        "documents": _documents_section(documents, fields),
        "bills": _bills(bills, fields, by_id),
        "findings": _findings_section(findings),
        "questions": _questions_section(questions),
        "resolutions": _resolutions_section(questions),
        "audit_events": _audit_events(events),
    }
    # The checklist reads the sections above, so it is built once they are all there.
    state["checklist"] = checklist_engine.build_checklist(state, _finding_refs(findings))
    # Readiness reads the checklist, the findings and the questions: it counts what is still
    # outstanding and never decides anything about the claim.
    state["readiness"] = readiness_engine.evaluate(state, state["questions"]["items"])
    state["review"] = {
        "state": claim.review_state,
        "approved": claim.review_state == "approved",
        "superseded": claim.review_state == "superseded",
        "approved_by": claim.approved_by,
        "approved_at": _iso(claim.approved_at),
        "approval_note": claim.approval_note,
        "review_started_at": _iso(claim.review_started_at),
        "superseded_at": _iso(claim.superseded_at),
        "approved_readiness": dict(claim.approved_readiness or {}),
        # An approval speaks for the claim it was given to; a superseded one no longer does.
        "can_approve": claim.review_state != "approved"
        and readiness_engine.can_be_approved(state["readiness"]),
    }
    for section, note in canonical_keys.PENDING_SECTIONS.items():
        state[section] = {"available": False, "count": 0, "items": [], "note": note}
    return state


def json_ready(value):
    """Convert anything the builder may have picked up into plain JSON types."""
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
