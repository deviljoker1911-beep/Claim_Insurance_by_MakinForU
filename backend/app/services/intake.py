"""Document intake — the single code path that stores uploaded originals.

Used by manual uploads and by the demo document packs alike.
"""

from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.audit import record_event
from app.config import get_settings
from app.models import Claim, Document, new_id, utcnow
from app.storage import InvalidFile, StagedFile, clean_filename, stage_file

UPLOAD_SOURCES = ("upload", "demo_pack")


@dataclass
class IncomingFile:
    filename: str | None
    stream: BinaryIO
    declared_content_type: str | None = None


@dataclass
class FileError:
    index: int  # position of the file in the upload request (names are not unique)
    filename: str
    error: str


class IntakeError(Exception):
    def __init__(self, message: str, errors: list[FileError] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []


def ingest_files(
    session: Session,
    claim: Claim,
    files: list[IncomingFile],
    *,
    source: str,
    demo_set: str | None = None,
    actor: str | None = None,
) -> list[Document]:
    """Validate and store every file, or none of them, then record one audit event per document."""
    if source not in UPLOAD_SOURCES:
        raise ValueError(f"Unknown upload source: {source}")
    settings = get_settings()
    if not files:
        raise IntakeError("No files were provided")
    if len(files) > settings.max_upload_files:
        raise IntakeError(f"Too many files: upload at most {settings.max_upload_files} files at once")

    actor = actor or settings.operator_name
    staged: list[StagedFile] = []
    errors: list[FileError] = []
    try:
        for index, incoming in enumerate(files):
            # The client-declared type is informational only; keep it storable (column is 128 chars).
            declared = "".join(ch for ch in (incoming.declared_content_type or "") if ch.isprintable())[:128] or None
            try:
                staged.append(stage_file(incoming.stream, incoming.filename, declared, claim.id, new_id()))
            except InvalidFile as exc:
                errors.append(FileError(index=index, filename=clean_filename(incoming.filename), error=str(exc)))
        if errors:
            raise IntakeError(
                f"{len(errors)} of {len(files)} file(s) could not be accepted. No files were stored.", errors
            )

        uploaded_at = utcnow()
        documents = []
        for item in staged:
            document = Document(
                id=item.document_id,
                claim=claim,
                original_filename=item.filename,
                content_type=item.content_type,
                declared_content_type=item.declared_content_type,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                storage_path=item.storage_path,
                page_count=item.page_count,
                file_metadata=item.metadata,
                upload_status="uploaded",
                processing_status="pending",
                source=source,
                demo_set=demo_set,
                uploaded_by=actor,
                uploaded_at=uploaded_at,
            )
            session.add(document)
            documents.append(document)
        claim.status = "documents_uploaded"
        claim.updated_at = uploaded_at
        session.flush()

        for item in staged:
            item.publish()
        for document in documents:
            record_event(
                session,
                "document_uploaded",
                f"Uploaded {document.original_filename}",
                claim_id=claim.id,
                document_id=document.id,
                actor=actor,
                details={
                    "filename": document.original_filename,
                    "sha256": document.sha256,
                    "size_bytes": document.size_bytes,
                    "content_type": document.content_type,
                    "page_count": document.page_count,
                    "source": source,
                    "demo_set": demo_set,
                },
            )
        session.commit()
    except BaseException:
        session.rollback()
        for item in staged:
            item.discard()
        raise
    return documents
