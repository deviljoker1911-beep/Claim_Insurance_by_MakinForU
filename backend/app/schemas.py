"""API response/request schemas."""

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; all stored timestamps are UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UTCDateTime = Annotated[datetime, AfterValidator(_as_utc)]
DemoSetName = Literal["initial", "operative_note", "anaesthesia_record"]


# --- System ----------------------------------------------------------------------------


class DatabaseStatus(BaseModel):
    ok: bool
    dialect: str
    database: str | None = None
    host: str | None = None
    port: int | None = None
    server_version: str | None = None
    error: str | None = None


class EngineStatus(BaseModel):
    key: str
    name: str
    role: str
    optional: bool
    available: bool
    version: str | None = None


class OcrStatus(BaseModel):
    preference: str
    engines: list[str]
    active: str | None
    offline: bool
    note: str


class LLMStatus(BaseModel):
    provider: str
    model: str
    api_key_configured: bool
    mode: Literal["offline-deterministic", "remote"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    environment: str
    demo_mode: bool
    server_time: datetime
    database: DatabaseStatus
    engines: list[EngineStatus]
    ocr: OcrStatus
    llm: LLMStatus


# --- Claims ------------------------------------------------------------------------------


class ClaimCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    patient_name: str = Field(min_length=2, max_length=200)
    uhid: str = Field(min_length=2, max_length=64, description="UHID / IPD number")
    hospital: str = Field(min_length=2, max_length=200)
    insurer: str = Field(min_length=2, max_length=200)
    tpa: str | None = Field(default=None, max_length=200)
    admission_date: date
    discharge_date: date
    is_demo: bool = False

    @field_validator("patient_name", "uhid", "hospital", "insurer", "tpa")
    @classmethod
    def _no_control_characters(cls, value: str | None) -> str | None:
        # PostgreSQL rejects NUL outright; other control characters have no place in these fields.
        if value is not None and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("must not contain control characters")
        return value

    @field_validator("tpa")
    @classmethod
    def _blank_tpa_is_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _check_dates(self) -> "ClaimCreate":
        if self.discharge_date < self.admission_date:
            raise ValueError("Discharge date cannot be before the admission date")
        return self


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_number: str
    patient_name: str
    uhid: str
    hospital: str
    insurer: str
    tpa: str | None
    admission_date: date
    discharge_date: date
    status: str
    is_demo: bool
    created_by: str
    created_at: UTCDateTime
    updated_at: UTCDateTime
    document_count: int = 0


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_id: str
    filename: str = Field(validation_alias=AliasChoices("original_filename", "filename"))
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    file_metadata: dict[str, Any]
    upload_status: str
    processing_status: str
    processing_stage: str | None = None
    stage_label: str | None = None
    processing_error: str | None = None
    doc_type: str | None = None
    doc_type_label: str | None = None
    doc_type_confidence: float | None = None
    text_source: str | None = None
    ocr_engine: str | None = None
    ocr_confidence: float | None = None
    quality_flags: list[dict[str, Any]] = []
    # Read from the row to count, never returned: the covered text itself belongs to the
    # document analysis response, not to a document listing.
    concealed_spans: list[dict[str, Any]] = Field(default=[], exclude=True)
    concealed_text_count: int = 0
    source: str
    demo_set: str | None
    uploaded_by: str
    uploaded_at: UTCDateTime

    @model_validator(mode="after")
    def _describe(self) -> "DocumentOut":
        from app.analysis.classify import type_label
        from app.services.analysis import stage_label

        if self.doc_type and not self.doc_type_label:
            object.__setattr__(self, "doc_type_label", type_label(self.doc_type))
        if self.processing_stage and not self.stage_label:
            object.__setattr__(self, "stage_label", stage_label(self.processing_stage))
        if self.concealed_spans and not self.concealed_text_count:
            object.__setattr__(self, "concealed_text_count", len(self.concealed_spans))
        return self


class ClaimDetail(ClaimOut):
    documents: list[DocumentOut]


class FileErrorOut(BaseModel):
    index: int
    filename: str
    error: str


class SkippedFile(BaseModel):
    filename: str
    reason: str


class UploadResult(BaseModel):
    claim_id: str
    documents: list[DocumentOut]
    skipped: list[SkippedFile] = []


class DemoAttachResult(UploadResult):
    set: DemoSetName
    attached_count: int
    skipped_count: int


# --- Document intelligence (phase 3) -----------------------------------------------------


class StageOut(BaseModel):
    key: str
    label: str


class QualityFlagOut(BaseModel):
    """A measured quality signal. Extra keys carry the measurement behind the flag."""

    model_config = ConfigDict(extra="allow")

    code: str
    severity: Literal["review", "attention", "info"]
    detail: str
    pages: list[int] = []


class FlagCountsOut(BaseModel):
    total: int = 0
    review: int = 0
    attention: int = 0


class DocumentProcessingOut(BaseModel):
    document_id: str
    filename: str
    processing_status: str
    processing_stage: str | None
    stage_label: str | None
    progress: float
    doc_type: str | None
    doc_type_label: str | None
    doc_type_confidence: float | None
    page_count: int | None
    text_source: str | None
    ocr_engine: str | None
    ocr_confidence: float | None
    quality_flag_counts: FlagCountsOut
    concealed_text_count: int
    processing_error: str | None
    processing_duration_ms: int | None
    processing_started_at: UTCDateTime | None
    processing_completed_at: UTCDateTime | None


class WorkerStatusOut(BaseModel):
    running: bool
    queue_depth: int
    current_document_id: str | None
    processed: int
    failed: int


class ClaimProcessingOut(BaseModel):
    claim_id: str
    claim_number: str
    claim_status: str
    state: Literal["idle", "running", "partial", "completed", "completed_with_failures"]
    counts: dict[str, int]
    document_count: int
    progress: float
    started_at: UTCDateTime | None
    completed_at: UTCDateTime | None
    stages: list[StageOut]
    documents: list[DocumentProcessingOut]
    worker: WorkerStatusOut


class ClassificationOut(BaseModel):
    doc_type: str | None
    label: str | None
    confidence: float | None
    method: str | None
    signals: list[dict[str, Any]] = []
    scores: dict[str, float] = {}


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    width: float
    height: float
    image_url: str | None = None
    image_width: int | None
    image_height: int | None
    text_source: str
    ocr_engine: str | None
    ocr_confidence: float | None
    effective_dpi: float | None
    char_count: int
    word_count: int
    concealed_count: int
    quality: dict[str, Any] = {}
    quality_flags: list[QualityFlagOut] = []


class ConcealedSpanOut(BaseModel):
    page_number: int
    text: str
    coverage: float
    bbox: list[float] | None = None


class PageDetailOut(PageOut):
    document_id: str
    text: str
    concealed_spans: list[ConcealedSpanOut] = []


class ExtractedFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str = Field(validation_alias=AliasChoices("field_key", "key"))
    label: str = Field(validation_alias=AliasChoices("field_label", "label"))
    group: str = Field(validation_alias=AliasChoices("field_group", "group"))
    value: str | None = Field(validation_alias=AliasChoices("value_text", "value"))
    raw: str | None = Field(default=None, validation_alias=AliasChoices("value_raw", "raw"))
    value_type: str
    page_number: int | None
    bbox: list[float] | None
    snippet: str | None
    method: str
    confidence: float
    evidence_available: bool
    details: dict[str, Any] = {}


class BillLineOut(BaseModel):
    line_no: int | None = None
    description: str
    quantity: str | None = None
    rate: str | None = None
    amount: str | None = None
    batch: str | None = None
    expiry: str | None = None
    page_number: int | None = None
    bbox: list[float] | None = None
    snippet: str | None = None


class BillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bill_type: str | None
    bill_number: str | None
    bill_date: date | None
    page_number: int | None
    currency: str
    subtotal: str | None
    tax: str | None
    discount: str | None
    total: str | None
    columns: list[str] = []
    line_items: list[BillLineOut] = []
    notes: list[str] = []


class SignatureSlotOut(BaseModel):
    key: str | None = None
    label: str | None = None
    caption: str | None = None
    required: bool = False
    found: bool = False
    checked: bool = False
    signed: bool | None = None
    stamp_detected: bool = False
    page_number: int | None = None
    bbox: list[float] | None = None
    method: str | None = None
    detail: str | None = None


class SignatureSummaryOut(BaseModel):
    method: str | None = None
    pages_analysed: list[int] = []
    pages_not_analysed: list[int] = []
    slots: list[SignatureSlotOut] = []


class DocumentAnalysisOut(BaseModel):
    document: DocumentOut
    processing: DocumentProcessingOut
    classification: ClassificationOut
    quality_flags: list[QualityFlagOut] = []
    signatures: SignatureSummaryOut = SignatureSummaryOut()
    concealed_spans: list[ConcealedSpanOut] = []
    warnings: list[str] = []
    page_render_dpi: int | None = None
    pages: list[PageOut] = []
    fields: list[ExtractedFieldOut] = []
    bill: BillOut | None = None


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_id: str | None
    document_id: str | None
    event_type: str
    actor: str
    message: str
    details: dict[str, Any]
    created_at: UTCDateTime


# --- Demo --------------------------------------------------------------------------------


class DemoClaimProfile(BaseModel):
    patient_name: str
    uhid: str
    hospital: str
    insurer: str
    tpa: str
    admission_date: date
    discharge_date: date


class DemoFileOut(BaseModel):
    filename: str
    label: str
    media_type: str
    pages: int
    size_bytes: int
    sha256: str
    download_url: str


class DemoFileSetOut(BaseModel):
    set: DemoSetName
    files: list[DemoFileOut]


class DemoDataStatus(BaseModel):
    files: int
    written: int
    verified: bool
    generator_matches_manifest: bool
    mismatched_files: list[str]
    manifest_sha256: str


class DemoResetRequest(BaseModel):
    confirm: Literal[True]


class DemoResetResult(BaseModel):
    status: Literal["ok"]
    deleted: dict[str, int]
    storage_cleared: bool
    demo_data: DemoDataStatus
    next_claim_number: str
    preserved: list[str]
    reset_at: UTCDateTime
