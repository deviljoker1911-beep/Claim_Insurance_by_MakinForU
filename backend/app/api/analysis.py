"""Document intelligence: starting analysis, following it, and reading what it found."""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import Document, DocumentPage
from app.schemas import (
    BillOut,
    ClaimStateOut,
    ConcealedSpanOut,
    ClaimProcessingOut,
    ClassificationOut,
    DocumentAnalysisOut,
    DocumentOut,
    DocumentProcessingOut,
    ExtractedFieldOut,
    PageDetailOut,
    PageOut,
    SignatureSummaryOut,
)
from app.services import analysis as analysis_service
from app.services import canonical as canonical_service
from app.services.claims import get_claim_or_404, mine_or_404, is_uuid
from app.services.locks import WORKSPACE_LOCK
from app.worker import get_worker

router = APIRouter(tags=["analysis"])

PageNumber = Annotated[int, Path(ge=1, le=10_000, description="1-based page number")]


def _document_or_404(session: Session, document_id: str) -> Document:
    document = session.get(Document, document_id) if is_uuid(document_id) else None
    return mine_or_404(session, document, "Document")


def _page_image_url(document_id: str, page_number: int) -> str:
    return f"/api/documents/{document_id}/pages/{page_number}/image"


def _page_payload(page: DocumentPage) -> PageOut:
    return PageOut.model_validate(page).model_copy(
        update={"image_url": _page_image_url(page.document_id, page.page_number) if page.image_path else None}
    )


@router.post("/claims/{claim_id}/analyze", response_model=ClaimProcessingOut, status_code=202)
def start_analysis(claim_id: str, session: Session = Depends(get_session)) -> ClaimProcessingOut:
    """Queue every document of the claim that has not been processed yet.

    Returns immediately: the worker processes the documents one at a time and progress is
    available from `GET /api/claims/{claim_id}/processing`.
    """
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        settings = get_settings()
        document_ids = analysis_service.queue_documents(session, claim, actor=settings.operator_name)
        get_worker().submit(document_ids)
        return ClaimProcessingOut.model_validate(analysis_service.claim_state(session, claim))


@router.get("/claims/{claim_id}/processing", response_model=ClaimProcessingOut)
def claim_processing(claim_id: str, session: Session = Depends(get_session)) -> ClaimProcessingOut:
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        return ClaimProcessingOut.model_validate(analysis_service.claim_state(session, claim))


@router.get("/claims/{claim_id}/state", response_model=ClaimStateOut)
def claim_state(claim_id: str, session: Session = Depends(get_session)) -> ClaimStateOut:
    """The canonical claim: one structured claim assembled from the processed documents.

    Rebuilt from the current extracted values on every request and stored when it changes, so
    the answer is always a deterministic function of the documents as they stand.
    """
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        return ClaimStateOut.model_validate(canonical_service.snapshot(session, claim))


@router.get("/documents/{document_id}/processing", response_model=DocumentProcessingOut)
def document_processing(document_id: str, session: Session = Depends(get_session)) -> DocumentProcessingOut:
    with WORKSPACE_LOCK.shared():
        document = _document_or_404(session, document_id)
        return DocumentProcessingOut.model_validate(analysis_service.document_state(document))


@router.get("/documents/{document_id}/analysis", response_model=DocumentAnalysisOut)
def document_analysis(document_id: str, session: Session = Depends(get_session)) -> DocumentAnalysisOut:
    """Everything the pipeline found in one document, with the evidence for each value."""
    with WORKSPACE_LOCK.shared():
        document = _document_or_404(session, document_id)
        return DocumentAnalysisOut(
            document=DocumentOut.model_validate(document),
            processing=DocumentProcessingOut.model_validate(analysis_service.document_state(document)),
            classification=ClassificationOut(
                doc_type=document.doc_type,
                label=document.doc_type and analysis_service.type_label(document.doc_type),
                confidence=document.doc_type_confidence,
                method=document.classification_method,
                signals=document.classification_signals or [],
                scores=document.classification_scores or {},
            ),
            quality_flags=document.quality_flags or [],
            signatures=SignatureSummaryOut.model_validate(document.signature_slots or {}),
            concealed_spans=document.concealed_spans or [],
            warnings=document.processing_warnings or [],
            page_render_dpi=document.page_render_dpi,
            pages=[_page_payload(page) for page in document.pages],
            fields=[ExtractedFieldOut.model_validate(field) for field in document.fields],
            bill=BillOut.model_validate(document.bill) if document.bill else None,
        )


@router.get("/documents/{document_id}/fields", response_model=list[ExtractedFieldOut])
def document_fields(
    document_id: str, group: str | None = None, session: Session = Depends(get_session)
) -> list[ExtractedFieldOut]:
    with WORKSPACE_LOCK.shared():
        document = _document_or_404(session, document_id)
        fields = document.fields
        if group:
            fields = [field for field in fields if field.field_group == group]
        return [ExtractedFieldOut.model_validate(field) for field in fields]


@router.get("/documents/{document_id}/pages", response_model=list[PageOut])
def document_pages(document_id: str, session: Session = Depends(get_session)) -> list[PageOut]:
    with WORKSPACE_LOCK.shared():
        document = _document_or_404(session, document_id)
        return [_page_payload(page) for page in document.pages]


@router.get("/documents/{document_id}/pages/{page_number}", response_model=PageDetailOut)
def document_page(
    document_id: str, page_number: PageNumber, session: Session = Depends(get_session)
) -> PageDetailOut:
    with WORKSPACE_LOCK.shared():
        document = _document_or_404(session, document_id)
        page = _page_or_404(session, document, page_number)
        concealed = [
            ConcealedSpanOut.model_validate(span)
            for span in (document.concealed_spans or [])
            if span.get("page_number") == page_number
        ]
        return PageDetailOut.model_validate(page).model_copy(
            update={
                "document_id": document.id,
                "image_url": _page_image_url(document.id, page.page_number) if page.image_path else None,
                "concealed_spans": concealed,
            }
        )


def _page_or_404(session: Session, document: Document, page_number: int) -> DocumentPage:
    page = session.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document.id, DocumentPage.page_number == page_number
        )
    )
    if page is None:
        if document.processing_status != analysis_service.STATUS_PROCESSED:
            raise HTTPException(
                status_code=404,
                detail=f"This document has not been processed yet (status: {document.processing_status}).",
            )
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.get("/documents/{document_id}/pages/{page_number}/image")
def document_page_image(
    document_id: str, page_number: PageNumber, session: Session = Depends(get_session)
) -> StreamingResponse:
    """The rendered image of one page. The original file is never modified or served here."""
    with WORKSPACE_LOCK.shared():
        document = _document_or_404(session, document_id)
        page = _page_or_404(session, document, page_number)
        if not page.image_path:
            raise HTTPException(status_code=404, detail="No image was rendered for this page")
        path = get_settings().storage_dir / page.image_path
        try:
            # Opened under the lock, so the handle survives a reset that removes the file.
            handle = path.open("rb")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="The page image is missing from storage") from exc
        size = os.fstat(handle.fileno()).st_size
        headers = {
            "Content-Length": str(size),
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="{document_id}-p{page_number}.png"',
        }

    def chunks():
        with handle:
            while chunk := handle.read(256 * 1024):
                yield chunk

    return StreamingResponse(chunks(), media_type="image/png", headers=headers)
