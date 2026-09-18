"""Analysis bookkeeping: queueing documents, storing results and reporting progress."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.analysis.classify import type_label  # re-exported for the API layer
from app.analysis.normalize import parse_date
from app.audit import record_event
from app.models import Claim, Document, DocumentBill, DocumentPage, ExtractedField, utcnow
from app.processing.pipeline import STAGE_LABELS, STAGES, ProcessingResult
from app.processing.types import normalise_bbox

logger = logging.getLogger("claimai.analysis")

STATUS_PENDING = "pending"
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_PROCESSED = "processed"
STATUS_FAILED = "failed"

ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_PROCESSING)
UNFINISHED_STATUSES = (STATUS_PENDING, STATUS_QUEUED, STATUS_PROCESSING)

CLAIM_PROCESSING = "processing"
CLAIM_PROCESSED = "processed"

STAGE_DEFINITIONS = [{"key": stage, "label": STAGE_LABELS[stage]} for stage in STAGES]


def stage_label(stage: str | None) -> str | None:
    return STAGE_LABELS.get(stage) if stage else None


# --- queueing ---------------------------------------------------------------------------


def queue_documents(session: Session, claim: Claim, *, actor: str | None = None, retry_failed: bool = True) -> list[str]:
    """Mark a claim's unprocessed documents as queued. Returns the document ids, in order."""
    statuses = [STATUS_PENDING, STATUS_FAILED] if retry_failed else [STATUS_PENDING]
    documents = session.scalars(
        select(Document)
        .where(Document.claim_id == claim.id, Document.processing_status.in_(statuses))
        .order_by(Document.uploaded_at, Document.original_filename)
    ).all()
    now = utcnow()
    for document in documents:
        document.processing_status = STATUS_QUEUED
        document.processing_stage = STAGES[0]
        document.queued_at = now
        document.processing_error = None
    if documents:
        claim.status = CLAIM_PROCESSING
        record_event(
            session,
            "claim_analysis_started",
            f"Queued {len(documents)} document(s) for analysis",
            claim_id=claim.id,
            actor=actor,
            details={"document_count": len(documents), "documents": [d.original_filename for d in documents]},
        )
    session.commit()
    return [document.id for document in documents]


def unfinished_document_ids(session: Session) -> list[str]:
    """Documents left queued or mid-processing, oldest first (used after a restart)."""
    return list(
        session.scalars(
            select(Document.id)
            .where(Document.processing_status.in_(ACTIVE_STATUSES))
            .order_by(Document.queued_at, Document.uploaded_at)
        ).all()
    )


def requeue_unfinished(session: Session) -> list[str]:
    """Put documents that were interrupted by a restart back on the queue."""
    documents = session.scalars(
        select(Document)
        .where(Document.processing_status.in_(ACTIVE_STATUSES))
        .order_by(Document.queued_at, Document.uploaded_at)
    ).all()
    if not documents:
        return []
    for document in documents:
        document.processing_status = STATUS_QUEUED
        document.processing_stage = STAGES[0]
        document.processing_started_at = None
    record_event(
        session,
        "processing_requeued",
        f"Requeued {len(documents)} document(s) that were interrupted",
        actor="system",
        details={"document_count": len(documents)},
    )
    session.commit()
    logger.info("Requeued %d unfinished document(s) after startup", len(documents))
    return [document.id for document in documents]


# --- results -----------------------------------------------------------------------------


def mark_started(session: Session, document: Document) -> None:
    document.processing_status = STATUS_PROCESSING
    document.processing_stage = STAGES[1]
    document.processing_started_at = utcnow()
    document.processing_attempts = (document.processing_attempts or 0) + 1
    document.processing_error = None
    session.commit()


def set_stage(session: Session, document: Document, stage: str) -> None:
    document.processing_stage = stage
    session.commit()


def clear_results(session: Session, document: Document) -> None:
    """Remove any previous analysis of this document before storing a new one."""
    for model in (DocumentPage, ExtractedField, DocumentBill):
        session.execute(delete(model).where(model.document_id == document.id))
    document.pages.clear()
    document.fields.clear()
    document.bill = None


def store_result(session: Session, document: Document, result: ProcessingResult) -> None:
    """Write a completed pipeline run to the database."""
    clear_results(session, document)
    content = result.content
    sizes = {page.number: (page.width, page.height) for page in content.pages}

    for page in content.pages:
        session.add(
            DocumentPage(
                document_id=document.id,
                claim_id=document.claim_id,
                page_number=page.number,
                width=page.width,
                height=page.height,
                image_path=page.image_path,
                image_width=page.image_width,
                image_height=page.image_height,
                text_source=page.text_source,
                ocr_engine=page.ocr_engine,
                ocr_confidence=page.ocr_confidence,
                effective_dpi=page.effective_dpi,
                char_count=len(page.text),
                word_count=len(page.words),
                concealed_count=len(page.concealed),
                text=page.text,
                quality=page.quality,
                quality_flags=page.quality_flags,
            )
        )

    for value in result.fields:
        width, height = sizes.get(value.page_number or 0, (1.0, 1.0))
        bbox = normalise_bbox(value.bbox, width, height) if value.bbox else None
        session.add(
            ExtractedField(
                document_id=document.id,
                claim_id=document.claim_id,
                field_key=value.key,
                field_label=value.label,
                field_group=value.group,
                value_text=(value.value or "")[:500],
                value_raw=(value.raw or "")[:500],
                value_type=value.kind,
                page_number=value.page_number,
                bbox=bbox,
                snippet=(value.snippet or "")[:300],
                method=value.method[:48],
                confidence=value.confidence,
                evidence_available=bool(value.page_number and bbox),
                details=value.details or {},
            )
        )

    if result.bill is not None:
        bill = result.bill
        number = next((f.value for f in result.fields if f.key == "billing.bill_number"), None)
        date_value = next((f.value for f in result.fields if f.key == "billing.bill_date"), None)
        session.add(
            DocumentBill(
                document_id=document.id,
                claim_id=document.claim_id,
                bill_type=result.classification.doc_type,
                bill_number=number,
                bill_date=parse_date(date_value) if date_value else None,
                page_number=bill.page_number,
                subtotal=bill.subtotal,
                tax=bill.tax,
                discount=bill.discount,
                total=bill.total,
                columns=bill.columns,
                notes=bill.notes,
                line_items=[
                    {
                        "line_no": line.line_no,
                        "description": line.description,
                        "quantity": line.quantity,
                        "rate": line.rate,
                        "amount": line.amount,
                        "batch": line.batch,
                        "expiry": line.expiry,
                        "page_number": line.page_number,
                        "bbox": normalise_bbox(line.bbox, *sizes.get(line.page_number, (1.0, 1.0)))
                        if line.bbox
                        else None,
                        "snippet": line.raw,
                    }
                    for line in bill.line_items
                ],
            )
        )

    classification = result.classification
    document.doc_type = classification.doc_type
    document.doc_type_confidence = classification.confidence
    document.classification_method = classification.method
    document.classification_signals = classification.signals
    document.classification_scores = classification.scores
    document.text_source = content.text_source
    document.ocr_engine = content.ocr_engine
    document.ocr_confidence = content.ocr_confidence
    document.page_render_dpi = content.page_render_dpi
    document.page_count = len(content.pages)
    document.quality_flags = result.quality_flags
    document.signature_slots = result.signatures
    document.concealed_spans = [
        {
            "page_number": page_number,
            "text": span.text,
            "coverage": span.coverage,
            "bbox": normalise_bbox(span.bbox, *sizes.get(page_number, (1.0, 1.0))),
        }
        for page_number, span in content.concealed
    ]
    document.processing_warnings = result.warnings
    document.processing_status = STATUS_PROCESSED
    document.processing_stage = STAGES[-1]
    document.processing_completed_at = utcnow()
    document.processing_duration_ms = result.duration_ms

    record_event(
        session,
        "document_processed",
        f"{document.original_filename} classified as {type_label(classification.doc_type)}",
        claim_id=document.claim_id,
        document_id=document.id,
        actor="system",
        details={
            "doc_type": classification.doc_type,
            "confidence": classification.confidence,
            "method": classification.method,
            "pages": len(content.pages),
            "text_source": content.text_source,
            "ocr_engine": content.ocr_engine,
            "fields": len(result.fields),
            "quality_flags": [flag["code"] for flag in result.quality_flags],
            "duration_ms": result.duration_ms,
        },
    )
    session.commit()


def mark_failed(session: Session, document: Document, message: str) -> None:
    document.processing_status = STATUS_FAILED
    document.processing_stage = "failed"
    document.processing_error = message[:500]
    document.processing_completed_at = utcnow()
    record_event(
        session,
        "document_processing_failed",
        f"{document.original_filename} could not be processed",
        claim_id=document.claim_id,
        document_id=document.id,
        actor="system",
        details={"error": message[:300]},
    )
    session.commit()


def finish_claim_if_done(session: Session, claim_id: str) -> None:
    """Move a claim to `processed` once none of its documents are waiting."""
    from app.services import canonical as canonical_service

    claim = session.get(Claim, claim_id)
    if claim is None:
        return
    counts = status_counts(session, claim_id)
    if any(counts.get(status) for status in UNFINISHED_STATUSES):
        return
    if not counts.get(STATUS_PROCESSED) and not counts.get(STATUS_FAILED):
        return
    claim.status = CLAIM_PROCESSED
    record_event(
        session,
        "claim_analysis_completed",
        "Document analysis finished",
        claim_id=claim.id,
        actor="system",
        details={"processed": counts.get(STATUS_PROCESSED, 0), "failed": counts.get(STATUS_FAILED, 0)},
    )
    session.commit()
    # Build the canonical claim from what was just extracted, then validate it, so both are
    # ready to be read. Neither failure may fail the analysis itself.
    try:
        payload, _ = canonical_service.refresh(session, claim)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not build the canonical claim for %s: %s", claim.claim_number, exc)
        session.rollback()
        return
    try:
        from app.services import validation as validation_service

        validation_service.refresh(session, claim, actor="system", state=payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not validate %s: %s", claim.claim_number, exc)
        session.rollback()


# --- reporting ---------------------------------------------------------------------------


def status_counts(session: Session, claim_id: str) -> dict[str, int]:
    rows = session.execute(
        select(Document.processing_status, func.count())
        .where(Document.claim_id == claim_id)
        .group_by(Document.processing_status)
    ).all()
    return {status: count for status, count in rows}


def _flag_counts(document: Document) -> dict[str, int]:
    flags = document.quality_flags or []
    return {
        "total": len(flags),
        "review": sum(1 for flag in flags if flag.get("severity") == "review"),
        "attention": sum(1 for flag in flags if flag.get("severity") == "attention"),
    }


def document_progress(document: Document) -> float:
    if document.processing_status == STATUS_PROCESSED:
        return 1.0
    if document.processing_status == STATUS_FAILED:
        return 1.0
    stage = document.processing_stage
    if document.processing_status == STATUS_PENDING or stage is None:
        return 0.0
    try:
        index = STAGES.index(stage)
    except ValueError:
        return 0.0
    return round(index / (len(STAGES) - 1), 3)


def document_state(document: Document) -> dict:
    return {
        "document_id": document.id,
        "filename": document.original_filename,
        "processing_status": document.processing_status,
        "processing_stage": document.processing_stage,
        "stage_label": stage_label(document.processing_stage),
        "progress": document_progress(document),
        "doc_type": document.doc_type,
        "doc_type_label": type_label(document.doc_type) if document.doc_type else None,
        "doc_type_confidence": document.doc_type_confidence,
        "page_count": document.page_count,
        "text_source": document.text_source,
        "ocr_engine": document.ocr_engine,
        "ocr_confidence": document.ocr_confidence,
        "quality_flag_counts": _flag_counts(document),
        "concealed_text_count": len(document.concealed_spans or []),
        "processing_error": document.processing_error,
        "processing_duration_ms": document.processing_duration_ms,
        "processing_started_at": document.processing_started_at,
        "processing_completed_at": document.processing_completed_at,
    }


def analysis_state(counts: dict[str, int]) -> str:
    total = sum(counts.values())
    if not total:
        return "idle"
    if any(counts.get(status) for status in ACTIVE_STATUSES):
        return "running"
    if counts.get(STATUS_PENDING):
        return "idle" if not (counts.get(STATUS_PROCESSED) or counts.get(STATUS_FAILED)) else "partial"
    if counts.get(STATUS_FAILED):
        return "completed_with_failures"
    return "completed"


def claim_state(session: Session, claim: Claim) -> dict:
    from app.worker import get_worker

    documents = session.scalars(
        select(Document)
        .where(Document.claim_id == claim.id)
        .order_by(Document.uploaded_at, Document.original_filename)
    ).all()
    counts = {status: 0 for status in (STATUS_PENDING, *ACTIVE_STATUSES, STATUS_PROCESSED, STATUS_FAILED)}
    for document in documents:
        counts[document.processing_status] = counts.get(document.processing_status, 0) + 1
    total = len(documents)
    progress = round(sum(document_progress(document) for document in documents) / total, 3) if total else 0.0
    started: datetime | None = min(
        (d.processing_started_at for d in documents if d.processing_started_at), default=None
    )
    completed: datetime | None = None
    if total and not any(counts.get(status) for status in UNFINISHED_STATUSES):
        completed = max((d.processing_completed_at for d in documents if d.processing_completed_at), default=None)
    worker = get_worker()
    return {
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "claim_status": claim.status,
        "state": analysis_state(counts),
        "counts": counts,
        "document_count": total,
        "progress": progress,
        "started_at": started,
        "completed_at": completed,
        "stages": STAGE_DEFINITIONS,
        "documents": [document_state(document) for document in documents],
        "worker": worker.stats(),
    }
