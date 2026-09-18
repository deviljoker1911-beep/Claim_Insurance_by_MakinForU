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
from app.models import AuditEvent, Claim, Document, DocumentBill, ExtractedField
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
        if document is None:
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
                # Nothing excludes or deduplicates documents yet; both are evaluated in phase 5.
                "excluded": False,
                "exclusion_reason": None,
                "duplicate_of": None,
                "duplicate_state": "not_evaluated",
            }
        )
    return {
        "count": len(items),
        "items": items,
        "by_type": {
            doc_type: sum(1 for item in items if item["doc_type"] == doc_type)
            for doc_type in sorted({item["doc_type"] for item in items if item["doc_type"]})
        },
        "note": "Duplicate and exclusion states are evaluated in phase 5.",
    }


def _investigations(documents: list[Document], fields: list[ExtractedField], by_id: dict[str, Document]) -> dict:
    items = []
    for document in documents:
        if document.doc_type not in canonical_keys.INVESTIGATION_DOC_TYPES:
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
        if document is None:
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
        "audit_events": _audit_events(events),
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
