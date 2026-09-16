"""Document upload and retrieval."""

import os
from dataclasses import asdict
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Document
from app.schemas import DocumentOut, UploadResult
from app.services.claims import get_claim_or_404, is_uuid
from app.services.intake import IncomingFile, IntakeError, ingest_files
from app.services.locks import WORKSPACE_LOCK
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
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        incoming = [IncomingFile(upload.filename, upload.file, upload.content_type) for upload in files]
        try:
            documents = ingest_files(session, claim, incoming, source="upload")
        except IntakeError as exc:
            raise intake_http_error(exc) from exc
        return UploadResult(claim_id=claim.id, documents=[DocumentOut.model_validate(d) for d in documents])


def _document_or_404(session: Session, document_id: str) -> Document:
    document = session.get(Document, document_id) if is_uuid(document_id) else None
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, session: Session = Depends(get_session)) -> DocumentOut:
    with WORKSPACE_LOCK.shared():
        return DocumentOut.model_validate(_document_or_404(session, document_id))


def _inline_disposition(filename: str) -> str:
    quoted = quote(filename)
    return f'inline; filename="{filename}"' if quoted == filename else f"inline; filename*=utf-8''{quoted}"


@router.get("/documents/{document_id}/file")
def download_original(document_id: str, session: Session = Depends(get_session)) -> StreamingResponse:
    with WORKSPACE_LOCK.shared():
        document = _document_or_404(session, document_id)
        path = absolute_storage_path(document.storage_path)
        try:
            # Opened under the lock: the open handle stays readable even if a reset removes the file.
            handle = path.open("rb")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="The original file is missing from storage") from exc
        size = os.fstat(handle.fileno()).st_size
        headers = {"Content-Disposition": _inline_disposition(document.original_filename), "Content-Length": str(size)}
        media_type = document.content_type

    def chunks():
        with handle:
            while chunk := handle.read(1024 * 1024):
                yield chunk

    return StreamingResponse(chunks(), media_type=media_type, headers=headers)
