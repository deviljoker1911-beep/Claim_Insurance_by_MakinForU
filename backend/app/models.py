"""ORM models."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class Visitor(Base):
    """Someone who asked for access to the demo, and whether they proved the address.

    Kept out of the claim workspace on purpose: a demo reset clears the claims, and the people
    who asked to see them are not demo data. One row per address, so asking twice updates the
    row rather than adding another.
    """

    __tablename__ = "visitors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # What the address was asked from, kept so a flood of requests can be told apart from use.
    last_user_agent: Mapped[str | None] = mapped_column(String(400), default=None)

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None


class AccessChallenge(Base):
    """A code sent to an address, and what has been tried against it.

    The code itself is never stored — only its hash — so the table cannot hand anyone a way in.
    """

    __tablename__ = "access_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    requested_ip: Mapped[str | None] = mapped_column(String(64), default=None)


# --- Claim workspace (dropped and recreated by a demo reset) ---------------------------


class ClaimCounter(Base):
    """Next claim number, per series and per owner.

    Each workspace counts from the start of the series, so the first claim someone creates is
    CLM-2026-00123 for them whoever else has been here. Numbers are unique within a workspace,
    not across the database.
    """

    __tablename__ = "claim_counters"

    series: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(320), primary_key=True, default="")
    next_value: Mapped[int] = mapped_column(Integer)


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Whose workspace this claim is in: the address that was verified to reach it, or "" when
    # nothing gates the deployment and there is one shared workspace. Claim numbers restart per
    # owner, so the number is unique within a workspace rather than across the table.
    owner: Mapped[str] = mapped_column(String(320), default="", index=True)
    claim_number: Mapped[str] = mapped_column(String(32), index=True)
    patient_name: Mapped[str] = mapped_column(String(200))
    uhid: Mapped[str] = mapped_column(String(64))
    hospital: Mapped[str] = mapped_column(String(200))
    insurer: Mapped[str] = mapped_column(String(200))
    tpa: Mapped[str | None] = mapped_column(String(200))
    admission_date: Mapped[date] = mapped_column(Date)
    discharge_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- human review (phase 8) ---
    # A claim is a draft until a person approves it. Nothing but a person's action sets this.
    review_state: Mapped[str] = mapped_column(String(16), default="draft")
    review_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(String(500))
    # What the documentation looked like when it was approved, kept as it was.
    approved_readiness: Mapped[dict] = mapped_column(JSONType, default=dict)
    # The documents as they stood when it was approved. An approval speaks for the claim it
    # was given to; when that claim changes, the approval is superseded rather than carried on.
    approved_input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("owner", "claim_number", name="uq_claim_number_per_owner"),)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="claim", order_by="Document.uploaded_at, Document.original_filename, Document.segment_index"
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

    # --- claim bundles (phase 11) ---
    # One uploaded file can hold several documents: a claim packet is usually one PDF holding the
    # pre-authorisation form, the bills, the reports and the discharge summary one after another.
    # Every document read out of a file shares that file's id here and keeps the pages of the file
    # it was read from, so a value read from page 7 of a bundle still says page 7 of that bundle.
    # A file holding one document is the same thing with one segment covering every page.
    source_file_id: Mapped[str] = mapped_column(String(36), index=True)
    source_page_count: Mapped[int | None] = mapped_column(Integer)
    page_numbers: Mapped[list] = mapped_column(JSONType, default=list)
    segment_index: Mapped[int] = mapped_column(Integer, default=0)
    # How the pages came to be grouped as one document, for a person asking why.
    segment_basis: Mapped[dict] = mapped_column(JSONType, default=dict)

    @property
    def page_span(self) -> str | None:
        """"7" or "13-16": the pages of the uploaded file this document was read from."""
        pages = self.page_numbers or []
        if not pages:
            return None
        return str(pages[0]) if len(pages) == 1 else f"{pages[0]}-{pages[-1]}"

    @property
    def is_part_of_a_bundle(self) -> bool:
        """Whether the file this came from holds other documents as well."""
        pages = self.page_numbers or []
        return bool(pages) and self.source_page_count is not None and len(pages) < self.source_page_count

    @property
    def display_name(self) -> str:
        """What to call this document: the file it arrived in, and where in it, when that matters."""
        if not self.is_part_of_a_bundle:
            return self.original_filename
        pages = self.page_numbers or []
        label = "page" if len(pages) == 1 else "pages"
        return f"{self.original_filename} ({label} {self.page_span})"

    # --- questions (phase 7) ---
    # Set when the document was uploaded in answer to a question, so the audit trail can show
    # the request and the document that answered it as one story.
    question_id: Mapped[str | None] = mapped_column(String(36), index=True)

    # --- validation (phase 5) ---
    # Set when a duplicate copy is excluded from the claim; an excluded document stops
    # supplying values to the canonical claim.
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(300))
    duplicate_of: Mapped[str | None] = mapped_column(String(36))
    duplicate_state: Mapped[str] = mapped_column(String(24), default="not_evaluated")

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

    # --- claim bundles (phase 11) ---
    # What this page looks like read on its own, before the pages of a file are grouped into
    # documents. It is what the grouping is decided from, and it is kept so a person can see why
    # a page landed where it did.
    page_type: Mapped[str | None] = mapped_column(String(48))
    page_type_confidence: Mapped[float | None] = mapped_column(Float)
    page_type_method: Mapped[str | None] = mapped_column(String(32))
    # Where this page sits in the document it was placed in: it began the document, it continues
    # one for a reason that is recorded, or nothing said either way and it stayed with the page
    # before it.
    page_role: Mapped[str | None] = mapped_column(String(24))
    page_role_because: Mapped[str | None] = mapped_column(String(32))

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


class Finding(Base):
    """One validation finding, with the lifecycle a person moves it through.

    A finding is identified by its fingerprint (rule and subject), not by its evidence, so
    re-running validation updates the finding that already exists instead of creating another.
    """

    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("claim_id", "fingerprint", name="uq_finding_fingerprint"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(String(16), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(300))
    explanation: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(500))
    # rule = deterministic comparison, source = a measurement made while reading the document,
    # ai = produced by a language model (nothing in phase 5 is).
    attribution: Mapped[str] = mapped_column(String(16), default="rule")
    subject: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    evidence: Mapped[list] = mapped_column(JSONType, default=list)
    context: Mapped[dict] = mapped_column(JSONType, default=dict)

    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    status_note: Mapped[str | None] = mapped_column(String(500))
    status_actor: Mapped[str | None] = mapped_column(String(120))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(120))

    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ValidationRun(Base):
    """The record of the last validation pass over a claim: which checks ran and what they said."""

    __tablename__ = "validation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True, unique=True)
    rules_version: Mapped[int] = mapped_column(Integer, default=1)
    # Fingerprint of the processed documents this run was based on; used to tell a stale
    # record from a current one.
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    checks: Mapped[list] = mapped_column(JSONType, default=list)
    summary: Mapped[dict] = mapped_column(JSONType, default=dict)
    findings_raised: Mapped[int] = mapped_column(Integer, default=0)
    findings_created: Mapped[int] = mapped_column(Integer, default=0)
    findings_auto_closed: Mapped[int] = mapped_column(Integer, default=0)
    findings_reopened: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Question(Base):
    """A request to the operator for a document the claim needs.

    One question per checklist requirement of a claim: asking again about the same requirement
    updates the question that is already there rather than adding another.
    """

    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("claim_id", "requirement_key", name="uq_question_requirement"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    requirement_key: Mapped[str] = mapped_column(String(64), index=True)
    requirement_label: Mapped[str] = mapped_column(String(120))
    procedure_key: Mapped[str | None] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(String(500))
    reason: Mapped[str] = mapped_column(String(500))
    expected_document_type: Mapped[str] = mapped_column(String(48))
    expected_document_types: Mapped[list] = mapped_column(JSONType, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="review")

    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    answer: Mapped[str | None] = mapped_column(String(32))
    answer_reason: Mapped[str | None] = mapped_column(String(500))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_by: Mapped[str | None] = mapped_column(String(120))
    # The document that answered the question, and what was said about the last one offered.
    resolved_document_id: Mapped[str | None] = mapped_column(String(36))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_upload: Mapped[dict] = mapped_column(JSONType, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ReanalysisRun(Base):
    """What one pass of analysis changed, as a comparison of two structured states."""

    __tablename__ = "reanalysis_runs"
    # One pass per sequence number: two writers cannot both record "pass 4" of a claim.
    __table_args__ = (UniqueConstraint("claim_id", "sequence", name="uq_reanalysis_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    trigger: Mapped[str] = mapped_column(String(32), default="analysis")
    before_state: Mapped[dict] = mapped_column(JSONType, default=dict)
    after_state: Mapped[dict] = mapped_column(JSONType, default=dict)
    changes: Mapped[list] = mapped_column(JSONType, default=list)
    summary: Mapped[dict] = mapped_column(JSONType, default=dict)
    documents_added: Mapped[list] = mapped_column(JSONType, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)


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


# Everything the workspace holds for a claim. A table that belongs to a claim and is missing
# here is neither rebuilt nor dropped with the rest, so the list is checked by a test.
WORKSPACE_MODELS = (
    ClaimCounter,
    Claim,
    Document,
    DocumentPage,
    ExtractedField,
    DocumentBill,
    ClaimState,
    Finding,
    ValidationRun,
    Question,
    ReanalysisRun,
    AuditEvent,
)

PROCESSING_STATUSES = ("pending", "queued", "processing", "processed", "failed")

# Finding lifecycle. A finding is raised by a rule and moved on by a person.
FINDING_OPEN = "open"
FINDING_RESOLVED = "resolved"
FINDING_ACKNOWLEDGED = "acknowledged"
FINDING_AUTO_CLOSED = "auto_closed"
FINDING_REOPENED = "reopened"
FINDING_STATUSES = (FINDING_OPEN, FINDING_RESOLVED, FINDING_ACKNOWLEDGED, FINDING_AUTO_CLOSED, FINDING_REOPENED)
# Statuses that still need someone to act.
FINDING_ACTIVE_STATUSES = (FINDING_OPEN, FINDING_REOPENED)

REVIEW_DRAFT = "draft"
REVIEW_APPROVED = "approved"
# The claim changed after it was approved: the earlier approval is on the record but no longer
# speaks for the claim as it now stands.
REVIEW_SUPERSEDED = "superseded"
REVIEW_STATES = (REVIEW_DRAFT, REVIEW_APPROVED, REVIEW_SUPERSEDED)

QUESTION_OPEN = "open"
QUESTION_ANSWERED = "answered"
QUESTION_RESOLVED = "resolved"
QUESTION_DOCUMENTED_UNAVAILABLE = "documented_unavailable"
QUESTION_NOT_APPLICABLE = "not_applicable"
QUESTION_STATUSES = (
    QUESTION_OPEN,
    QUESTION_ANSWERED,
    QUESTION_RESOLVED,
    QUESTION_DOCUMENTED_UNAVAILABLE,
    QUESTION_NOT_APPLICABLE,
)
# A question still waiting for something from the operator.
QUESTION_PENDING_STATUSES = (QUESTION_OPEN, QUESTION_ANSWERED)

# A document still on its way through the pipeline. While a claim has one of these, what has been
# read of the claim is not yet the claim, so nothing derived from it is final.
DOCUMENT_UNFINISHED_STATUSES = ("pending", "queued", "processing")

ANSWER_YES_HAVE_IT = "yes_have_it"
ANSWER_NOT_AVAILABLE = "not_available"
ANSWER_NOT_APPLICABLE = "not_applicable"
ANSWERS = (ANSWER_YES_HAVE_IT, ANSWER_NOT_AVAILABLE, ANSWER_NOT_APPLICABLE)
SEVERITIES = ("critical", "review", "warning", "info")
# Most serious first. This is the order findings are listed in wherever a reader sees them, so it
# is written once: the same two findings must never come out in a different order in two places.
SEVERITY_ORDER = {severity: index for index, severity in enumerate(SEVERITIES)}
