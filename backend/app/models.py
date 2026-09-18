"""ORM models."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class AppSetting(Base):
    """Application configuration. Preserved across demo resets."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --- Claim workspace (dropped and recreated by a demo reset) ---------------------------


class ClaimCounter(Base):
    __tablename__ = "claim_counters"

    series: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer)


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_name: Mapped[str] = mapped_column(String(200))
    uhid: Mapped[str] = mapped_column(String(64))
    hospital: Mapped[str] = mapped_column(String(200))
    insurer: Mapped[str] = mapped_column(String(200))
    tpa: Mapped[str | None] = mapped_column(String(200))
    admission_date: Mapped[date] = mapped_column(Date)
    discharge_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="claim", order_by="Document.uploaded_at, Document.original_filename"
    )


class Document(Base):
    """An uploaded original. The stored file is written once and never modified."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    declared_content_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    page_count: Mapped[int | None] = mapped_column(Integer)
    file_metadata: Mapped[dict] = mapped_column(JSONType, default=dict)
    upload_status: Mapped[str] = mapped_column(String(32), default="uploaded")
    source: Mapped[str] = mapped_column(String(32))
    demo_set: Mapped[str | None] = mapped_column(String(64))
    uploaded_by: Mapped[str] = mapped_column(String(120))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # --- document intelligence (phase 3) ---
    # pending -> queued -> processing -> processed | failed
    processing_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    processing_stage: Mapped[str | None] = mapped_column(String(32))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_duration_ms: Mapped[int | None] = mapped_column(Integer)
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0)
    processing_error: Mapped[str | None] = mapped_column(String(500))
    processing_warnings: Mapped[list] = mapped_column(JSONType, default=list)

    doc_type: Mapped[str | None] = mapped_column(String(48), index=True)
    doc_type_confidence: Mapped[float | None] = mapped_column(Float)
    classification_method: Mapped[str | None] = mapped_column(String(48))
    classification_signals: Mapped[list] = mapped_column(JSONType, default=list)
    classification_scores: Mapped[dict] = mapped_column(JSONType, default=dict)

    text_source: Mapped[str | None] = mapped_column(String(16))
    ocr_engine: Mapped[str | None] = mapped_column(String(32))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    page_render_dpi: Mapped[int | None] = mapped_column(Integer)

    quality_flags: Mapped[list] = mapped_column(JSONType, default=list)
    signature_slots: Mapped[dict] = mapped_column(JSONType, default=dict)
    # Text present in the file but painted over. Kept apart from every extracted value.
    concealed_spans: Mapped[list] = mapped_column(JSONType, default=list)

    claim: Mapped[Claim] = relationship(back_populates="documents")
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_number"
    )
    fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="ExtractedField.id"
    )
    bill: Mapped["DocumentBill | None"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )


class DocumentPage(Base):
    """One page of a document: its rendering, its text and its quality measurements."""

    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_document_page"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    image_path: Mapped[str | None] = mapped_column(String(500))
    image_width: Mapped[int | None] = mapped_column(Integer)
    image_height: Mapped[int | None] = mapped_column(Integer)
    text_source: Mapped[str] = mapped_column(String(16), default="none")
    ocr_engine: Mapped[str | None] = mapped_column(String(32))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    effective_dpi: Mapped[float | None] = mapped_column(Float)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    concealed_count: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    quality: Mapped[dict] = mapped_column(JSONType, default=dict)
    quality_flags: Mapped[list] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="pages")


class ExtractedField(Base):
    """One value read out of a document, with the evidence it came from."""

    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), index=True)
    field_key: Mapped[str] = mapped_column(String(64), index=True)
    field_label: Mapped[str] = mapped_column(String(120))
    field_group: Mapped[str] = mapped_column(String(32))
    value_text: Mapped[str | None] = mapped_column(String(500))
    value_raw: Mapped[str | None] = mapped_column(String(500))
    value_type: Mapped[str] = mapped_column(String(16), default="text")
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list | None] = mapped_column(JSONType)
    snippet: Mapped[str | None] = mapped_column(String(300))
    method: Mapped[str] = mapped_column(String(48))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_available: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="fields")


class DocumentBill(Base):
    """A bill or invoice read out of a document: its line items and its totals."""

    __tablename__ = "document_bills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, unique=True
    )
    claim_id: Mapped[str] = mapped_column(String(36), index=True)
    bill_type: Mapped[str | None] = mapped_column(String(48))
    bill_number: Mapped[str | None] = mapped_column(String(120))
    bill_date: Mapped[date | None] = mapped_column(Date)
    page_number: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    subtotal: Mapped[str | None] = mapped_column(String(32))
    tax: Mapped[str | None] = mapped_column(String(32))
    discount: Mapped[str | None] = mapped_column(String(32))
    total: Mapped[str | None] = mapped_column(String(32))
    columns: Mapped[list] = mapped_column(JSONType, default=list)
    line_items: Mapped[list] = mapped_column(JSONType, default=list)
    notes: Mapped[list] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="bill")


class ClaimState(Base):
    """The canonical claim, rebuilt from the processed documents of one claim.

    The payload is a whole JSON document: it is always replaced with a new value, never
    mutated in place, so SQLAlchemy always sees the change.
    """

    __tablename__ = "claim_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True, unique=True)
    generator_version: Mapped[int] = mapped_column(Integer, default=1)
    content_sha256: Mapped[str] = mapped_column(String(64))
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


WORKSPACE_MODELS = (
    ClaimCounter,
    Claim,
    Document,
    DocumentPage,
    ExtractedField,
    DocumentBill,
    ClaimState,
    AuditEvent,
)

PROCESSING_STATUSES = ("pending", "queued", "processing", "processed", "failed")
