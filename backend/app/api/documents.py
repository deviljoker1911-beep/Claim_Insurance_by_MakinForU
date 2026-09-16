"""Document upload and retrieval."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Document
from app.schemas import DocumentOut, UploadResult
from app.services.claims import get_claim_or_404
from app.services.intake import IncomingFile, IntakeError, ingest_files
from app.storage import absolute_storage_path

router = APIRouter(tags=["documents"])


def intake_http_error(exc: IntakeError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"message": exc.message, "errors": [asdict(error) for error in exc.errors]},
    )


@router.post("/claims/{claim_id}/documents", response_model=UploadResult, status_code=201)
def upload_documents(
    claim_id: str,
    files: Annotated[list[UploadFile], File(description="One or more PDF, PNG or JPG files")],
    session: Session = Depends(get_session),
) -> UploadResult:
    claim = get_claim_or_404(session, claim_id)
    incoming = [IncomingFile(upload.filename, upload.file, upload.content_type) for upload in files]
    try:
        documents = ingest_files(session, claim, incoming, source="upload")
    except IntakeError as exc:
        raise intake_http_error(exc) from exc
    return UploadResult(claim_id=claim.id, documents=[DocumentOut.model_validate(d) for d in documents])


def _document_or_404(session: Session, document_id: str) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, session: Session = Depends(get_session)) -> Document:
    return _document_or_404(session, document_id)


@router.get("/documents/{document_id}/file")
def download_original(document_id: str, session: Session = Depends(get_session)) -> FileResponse:
    document = _document_or_404(session, document_id)
    path = absolute_storage_path(document.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The original file is missing from storage")
    return FileResponse(
        path,
        media_type=document.content_type,
        filename=document.original_filename,
        content_disposition_type="inline",
    )
