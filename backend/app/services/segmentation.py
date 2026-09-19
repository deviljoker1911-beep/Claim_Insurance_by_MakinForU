"""Reading one uploaded file as the documents it actually holds.

A claim packet arrives as a single PDF holding the pre-authorisation form, the case papers, the
bills, the reports and the discharge summary one after another. Read as one document it becomes
whatever its first page looks like, and every document inside it is then reported as missing.

This is the step between the file and the pipeline the rest of the system already has. The file is
read once — rendered, OCR'd and measured — its pages are grouped into the documents they belong
to, and each group then goes through the ordinary document pipeline. Nothing downstream is aware
that a bundle was involved: it sees documents, as it always has.

The pages keep the numbers they have in the uploaded file. A value read from page 7 of a bundle
says page 7 of that bundle, and the page image behind it is that page, so a reviewer following a
piece of evidence arrives where it was actually read.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.config_files import quality_config
from app.models import Document
from app.processing.pipeline import STAGE_CLASSIFICATION, ReadFile, analyse_pages
from app.segmentation.engine import Segment
from app.text import plural
from app.services import analysis as analysis_service

logger = logging.getLogger("claimai.segmentation")


def _siblings(session: Session, source: Document) -> dict[int, Document]:
    """Documents already read out of this file, by their position in it."""
    rows = session.scalars(
        select(Document).where(
            Document.claim_id == source.claim_id,
            Document.source_file_id == source.source_file_id,
        )
    ).all()
    return {row.segment_index: row for row in rows}


def _document_for(session: Session, source: Document, index: int, existing: dict[int, Document]) -> Document:
    """The row for one document of a file: the file's own row first, then its siblings.

    Reading a file again reuses the rows it produced before, so a document that a person has
    already acted on — excluded as a duplicate, or attached to a question — keeps its identity and
    its decisions instead of coming back as something new.
    """
    if index in existing:
        return existing[index]
    document = Document(
        claim_id=source.claim_id,
        source_file_id=source.source_file_id,
        segment_index=index,
        original_filename=source.original_filename,
        content_type=source.content_type,
        declared_content_type=source.declared_content_type,
        size_bytes=source.size_bytes,
        sha256=source.sha256,
        storage_path=source.storage_path,
        file_metadata=dict(source.file_metadata or {}),
        upload_status=source.upload_status,
        source=source.source,
        demo_set=source.demo_set,
        uploaded_by=source.uploaded_by,
        uploaded_at=source.uploaded_at,
    )
    session.add(document)
    session.flush()
    return document


def _note_uncertainty(document: Document, segment: Segment) -> None:
    """Say so when pages were placed here for want of anywhere else to put them.

    Nothing about the page said it began a document and nothing said it continued one, so it
    stayed with the page before it. That is a reasonable thing to do and a bad thing to do
    silently: the document carries a signal saying which pages they were, and a reader can see
    that the system had no evidence rather than a quiet wrong answer.

    It is a signal, not a finding. A page the system could not place is not a defect in the
    paperwork, and nothing about the claim's readiness or its approval changes because of it.
    """
    pages = segment.ambiguous_pages
    if not pages:
        return
    severities = quality_config()["severity"]
    listed = ", ".join(str(number) for number in pages)
    document.quality_flags = [
        *(document.quality_flags or []),
        {
            "code": "classification_uncertain",
            "severity": severities.get("classification_uncertain", "attention"),
            "detail": (
                f"Classification uncertain — requires review. {plural(len(pages), 'page')} "
                f"({listed}) named no document and carried nothing tying them to this one, so they "
                "were kept with the page they follow."
            ),
            "pages": list(pages),
        },
    ]


def store(session: Session, source: Document, read: ReadFile, segments: list[Segment]) -> list[Document]:
    """Analyse each document found in the file and write it as a document of the claim.

    The file's own row becomes the first document in it, so a file holding one document is stored
    exactly as it always has been.
    """
    existing = _siblings(session, source)
    page_count = len(read.pages)
    stored: dict[int, Document] = {}

    # While its documents are being classified, that is the stage the file is at: it was left
    # showing the last stage of reading it, which is behind the work actually going on.
    if len(segments) > 1:
        analysis_service.set_stage(session, source, STAGE_CLASSIFICATION)

    # The file's own row is finished last. Everything that asks whether a claim has been read
    # asks its documents, and each document is written as it is analysed, so finishing the
    # file's row first would leave the claim reporting itself completely read at the moment the
    # first of its documents landed — with the rest of them still to come. Held open until the
    # last one is written, the claim says it is still being read for exactly as long as it is.
    for index in [*range(1, len(segments)), 0]:
        segment = segments[index]
        document = source if index == 0 else _document_for(session, source, index, existing)
        result = analyse_pages(read, segment.pages)
        if index == 0:
            result.duration_ms += read.duration_ms
        document.source_file_id = source.source_file_id
        document.segment_index = index
        document.page_numbers = segment.page_numbers
        document.source_page_count = page_count
        document.segment_basis = segment.basis()
        analysis_service.store_result(
            session,
            document,
            result,
            page_reads={item.number: item for item in segment.page_reads},
        )
        _note_uncertainty(document, segment)
        stored[index] = document

    # Back into the order they appear in the file, which is the order everything downstream
    # reports them in.
    documents: list[Document] = [stored[index] for index in range(len(segments))]

    # A file read again may hold fewer documents than it did before: anything left over belonged to
    # a reading that no longer stands.
    for index, stale in existing.items():
        if index >= len(segments) and stale.id != source.id:
            session.delete(stale)
    session.commit()

    if len(segments) > 1:
        record_event(
            session,
            "bundle_segmented",
            f"{source.original_filename} holds {len(segments)} documents across {page_count} pages",
            claim_id=source.claim_id,
            document_id=source.id,
            actor="system",
            details={
                "pages": page_count,
                "documents": [
                    {
                        "doc_type": document.doc_type,
                        "pages": document.page_numbers,
                        "started_because": (document.segment_basis or {}).get("started_because"),
                    }
                    for document in documents
                ],
            },
        )
        session.commit()
        logger.info(
            "%s read as %d documents across %d pages", source.original_filename, len(segments), page_count
        )
    return documents


__all__ = ["store"]
