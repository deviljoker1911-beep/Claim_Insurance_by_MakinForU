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


# --- Canonical claim (phase 4) -----------------------------------------------------------


class EvidenceSourceOut(BaseModel):
    """Where one canonical value came from. Never invented: a source without a page says so."""

    document_id: str
    document_name: str
    document_type: str | None = None
    document_type_label: str | None = None
    page: int | None = None
    bounding_box: list[float] | None = None
    snippet: str | None = None
    method: str
    source_type: str
    source_type_label: str
    extraction_method: str
    confidence: float
    weight: int
    eligible: bool
    excluded_reason: str | None = None
    value: str | None = None
    raw_value: str | None = None
    field_key: str
    derived_from: str | None = None
    evidence_available: bool


class ValueVariantOut(BaseModel):
    value: str
    source_count: int


class CompetingValueOut(BaseModel):
    value: str
    normalized_value: str
    weight: int
    source_count: int
    eligible_source_count: int
    value_variants: list[ValueVariantOut] = []
    sources: list[EvidenceSourceOut] = []


class CanonicalValueOut(BaseModel):
    key: str
    label: str
    kind: str
    section: str
    present: bool
    value: str | None = None
    normalized_value: str | None = None
    confidence: float | None = None
    weight: int | None = None
    source_count: int = 0
    value_variants: list[ValueVariantOut] = []
    sources: list[EvidenceSourceOut] = []
    evidence_available: bool = False
    competing_values: list[CompetingValueOut] = []
    has_competing_values: bool = False
    note: str | None = None


class CanonicalSectionOut(BaseModel):
    fields: dict[str, CanonicalValueOut]
    present_count: int
    field_count: int


class ProcedureItemOut(BaseModel):
    procedure_key: str | None = None
    label: str
    value: str
    normalized_value: str
    weight: int
    source_count: int
    value_variants: list[ValueVariantOut] = []
    sources: list[EvidenceSourceOut] = []
    is_selected: bool


class ProceduresSectionOut(BaseModel):
    selected_key: str | None = None
    selected: CanonicalValueOut | None = None
    items: list[ProcedureItemOut] = []
    fields: dict[str, CanonicalValueOut] = {}


class InvestigationItemOut(BaseModel):
    document_id: str
    document_name: str
    doc_type: str | None = None
    doc_type_label: str | None = None
    page_count: int | None = None
    fields: dict[str, CanonicalValueOut] = {}


class InvestigationsSectionOut(BaseModel):
    count: int
    items: list[InvestigationItemOut] = []


class DocumentInventoryItemOut(BaseModel):
    document_id: str
    filename: str
    doc_type: str | None = None
    doc_type_label: str | None = None
    classification_confidence: float | None = None
    classification_method: str | None = None
    processing_status: str
    processing_stage: str | None = None
    processing_error: str | None = None
    page_count: int | None = None
    quality_signals: list[QualityFlagOut] = []
    quality_signal_count: int = 0
    ocr_method: str | None = None
    ocr_engine: str | None = None
    ocr_confidence: float | None = None
    text_source: str | None = None
    concealed_text_count: int = 0
    unsigned_required_slots: list[str | None] = []
    extracted_field_count: int = 0
    source: str
    demo_set: str | None = None
    sha256: str
    size_bytes: int
    uploaded_at: UTCDateTime | None = None
    excluded: bool = False
    exclusion_reason: str | None = None
    duplicate_of: str | None = None
    duplicate_state: str


class DocumentsSectionOut(BaseModel):
    count: int
    items: list[DocumentInventoryItemOut] = []
    by_type: dict[str, int] = {}
    excluded_count: int = 0
    note: str | None = None


class CanonicalBillLineEvidenceOut(BaseModel):
    document_id: str
    document_name: str
    document_type: str | None = None
    page: int | None = None
    bounding_box: list[float] | None = None
    snippet: str | None = None
    method: str
    source_type: str
    confidence: float | None = None
    evidence_available: bool


class CanonicalBillLineOut(BaseModel):
    line_no: int | None = None
    description: str | None = None
    quantity: str | None = None
    rate: str | None = None
    amount: str | None = None
    batch: str | None = None
    expiry: str | None = None
    evidence: CanonicalBillLineEvidenceOut


class CanonicalBillOut(BaseModel):
    document_id: str
    document_name: str
    bill_type: str | None = None
    bill_type_label: str | None = None
    currency: str
    page_number: int | None = None
    columns: list[str] = []
    notes: list[str] = []
    line_item_count: int
    line_items: list[CanonicalBillLineOut] = []
    fields: dict[str, CanonicalValueOut] = {}


class BillTotalOut(BaseModel):
    document_id: str
    document_name: str
    bill_type: str | None = None
    bill_type_label: str | None = None
    bill_number: str | None = None
    bill_date: str | None = None
    total: str | None = None
    currency: str


class BillsSummaryOut(BaseModel):
    by_type: dict[str, int] = {}
    totals: list[BillTotalOut] = []


class BillsSectionOut(BaseModel):
    count: int
    items: list[CanonicalBillOut] = []
    summary: BillsSummaryOut
    note: str | None = None


class PendingSectionOut(BaseModel):
    """A section whose engine arrives in a later phase: present, empty and labelled."""

    available: bool = False
    count: int = 0
    items: list[Any] = []
    note: str


class CanonicalFindingItemOut(BaseModel):
    """A finding as the canonical claim lists it; the full record is on the findings endpoint."""

    id: str
    rule_id: str
    code: str
    category: str
    severity: str
    status: str
    title: str
    action: str
    subject: str
    attribution: str
    evidence_count: int


class CanonicalFindingsSectionOut(BaseModel):
    available: bool
    count: int
    active: int
    by_severity: dict[str, int]
    active_by_severity: dict[str, int]
    by_status: dict[str, int]
    items: list[CanonicalFindingItemOut] = []


class CanonicalAuditEventOut(BaseModel):
    id: int
    event_type: str
    actor: str
    message: str
    document_id: str | None = None
    created_at: UTCDateTime | None = None


class AuditEventsSectionOut(BaseModel):
    count: int
    included: int
    items: list[CanonicalAuditEventOut] = []


class ClaimFormOut(BaseModel):
    patient_name: str
    uhid: str
    hospital: str
    insurer: str
    tpa: str | None = None
    admission_date: date | None = None
    discharge_date: date | None = None


class ClaimHeaderOut(BaseModel):
    claim_id: str
    claim_number: str
    status: str
    is_demo: bool
    hospital: str
    insurer: str
    tpa: str | None = None
    created_by: str
    created_at: UTCDateTime | None = None
    form: ClaimFormOut


class ValueSelectionOut(BaseModel):
    document_weights: dict[str, int]
    default_weight: int
    ocr_confidence_floor: float
    rule: str


class CanonicalMetaOut(BaseModel):
    generator_version: int
    analysis_state: str
    document_counts: dict[str, int]
    value_selection: ValueSelectionOut
    pending_sections: dict[str, str]


class SnapshotOut(BaseModel):
    content_sha256: str
    generator_version: int
    generated_at: UTCDateTime
    document_count: int
    processed_count: int


# --- Procedure checklist (phase 6) --------------------------------------------------------


class ChecklistEvidenceOut(BaseModel):
    """The document that satisfies a requirement. A document has no page to cite of its own."""

    document_id: str
    document_name: str
    doc_type: str | None = None
    doc_type_label: str | None = None
    classification_confidence: float | None = None
    classification_method: str | None = None
    page_count: int | None = None
    page: int | None = None
    detail: str


class ChecklistFindingOut(BaseModel):
    """A finding the rules raised about this requirement; the full record is on /findings."""

    id: str
    rule_id: str
    code: str
    severity: str
    status: str
    title: str
    subject: str
    is_active: bool
    document_ids: list[str] = []


class ChecklistItemOut(BaseModel):
    key: str
    label: str
    description: str
    doc_types: list[str] = []
    doc_type_labels: list[str] = []
    required: bool
    severity: Literal["critical", "review", "warning", "info"]
    applies_when: str
    resolution: str
    question: str
    why: str
    status: Literal["found", "missing", "review_required", "not_applicable"]
    detail: str
    evidence: list[ChecklistEvidenceOut] = []
    findings: list[ChecklistFindingOut] = []


class ChecklistProcedureSourceOut(BaseModel):
    document_id: str
    document_name: str
    value: str | None = None
    page: int | None = None


class ChecklistProcedureNamedOut(BaseModel):
    key: str | None = None
    label: str
    source_count: int = 0


class ChecklistProcedureOut(BaseModel):
    """The procedure the checklist was built for, and what named it."""

    key: str | None = None
    label: str
    has_checklist: bool
    source_count: int = 0
    documents: list[ChecklistProcedureSourceOut] = []
    written_as: list[str] = []
    also_named: list[ChecklistProcedureNamedOut] = []


class ChecklistSectionOut(BaseModel):
    available: bool
    checklist_version: int
    procedure: ChecklistProcedureOut
    provisional: bool = False
    count: int
    summary: dict[str, Any] = {}
    items: list[ChecklistItemOut] = []
    configured_procedures: list[ChecklistProcedureNamedOut] = []
    note: str | None = None


class ChecklistResponse(ChecklistSectionOut):
    claim_id: str
    claim_number: str


# --- Questions, re-analysis and the assistant (phase 7) -----------------------------------


class CanonicalQuestionItemOut(BaseModel):
    id: str
    requirement_key: str
    requirement_label: str
    question: str
    reason: str
    status: str
    severity: str
    expected_document_type: str
    resolved_document_id: str | None = None
    created_at: UTCDateTime | None = None
    updated_at: UTCDateTime | None = None


class CanonicalQuestionsSectionOut(BaseModel):
    available: bool
    count: int
    open: int = 0
    by_status: dict[str, int] = {}
    items: list[CanonicalQuestionItemOut] = []


class CanonicalResolutionItemOut(BaseModel):
    question_id: str
    requirement_key: str
    requirement_label: str
    answer: str | None = None
    reason: str | None = None
    status: str
    actor: str | None = None
    answered_at: UTCDateTime | None = None
    resolved_document_id: str | None = None
    resolved_at: UTCDateTime | None = None


class CanonicalResolutionsSectionOut(BaseModel):
    available: bool
    count: int
    items: list[CanonicalResolutionItemOut] = []


class QuestionUploadOut(BaseModel):
    """What was offered for a question and whether it answered it."""

    document_id: str
    document_name: str
    doc_type: str | None = None
    doc_type_label: str | None = None
    expected_document_types: list[str] = []
    satisfies: bool
    message: str
    checked_at: str | None = None


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_id: str
    requirement_key: str
    requirement_label: str
    procedure_key: str | None = None
    question: str
    reason: str
    status: Literal["open", "answered", "resolved", "documented_unavailable", "not_applicable"]
    severity: str
    expected_document_type: str
    expected_document_types: list[str] = []
    answer: str | None = None
    answer_reason: str | None = None
    answered_at: UTCDateTime | None = None
    answered_by: str | None = None
    resolved_document_id: str | None = None
    resolved_at: UTCDateTime | None = None
    last_upload: QuestionUploadOut | None = None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    actions_available: list[str] = []

    @field_validator("last_upload", mode="before")
    @classmethod
    def _no_upload_yet(cls, value):
        """Nothing has been offered for this question yet."""
        return value or None


class QuestionsResponse(BaseModel):
    claim_id: str
    claim_number: str
    count: int
    summary: dict[str, Any] = {}
    items: list[QuestionOut] = []


class QuestionAnswerRequest(BaseModel):
    answer: Literal["yes_have_it", "not_available", "not_applicable"]
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("must not contain control characters")
        return value or None


class QuestionAnswerResult(BaseModel):
    question: QuestionOut
    # Present for "yes, I have it": where to send the document that answers the question.
    upload: dict[str, Any] | None = None


class ChangeOut(BaseModel):
    kind: Literal["document", "finding", "checklist", "canonical", "question", "procedure"]
    key: str
    label: str
    before: Any = None
    after: Any = None
    headline: str
    severity: str | None = None
    code: str | None = None
    document_id: str | None = None
    finding_id: str | None = None
    question_id: str | None = None
    requirement: str | None = None


class ReanalysisRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_id: str
    sequence: int
    trigger: str
    summary: dict[str, Any] = {}
    changes: list[ChangeOut] = []
    documents_added: list[dict[str, Any]] = []
    started_at: UTCDateTime
    completed_at: UTCDateTime | None = None
    duration_ms: int | None = None


class ReanalysisResponse(BaseModel):
    claim_id: str
    claim_number: str
    latest: ReanalysisRunOut | None = None
    history: list[ReanalysisRunOut] = []


class AssistantCitationOut(BaseModel):
    kind: Literal["finding", "document", "requirement", "question", "claim"]
    id: str
    label: str
    detail: str | None = None
    document_id: str | None = None
    page: int | None = None


class AssistantAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def _clean_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("must not contain control characters")
        return value


class AssistantAnswerOut(BaseModel):
    claim_id: str
    claim_number: str
    question: str
    intent: str
    answer: str
    citations: list[AssistantCitationOut] = []
    suggested_questions: list[str] = []
    provider: dict[str, Any] = {}
    notice: str
    removed_citations: list[str] = []


# --- Readiness, review and the dashboard (phase 8) -----------------------------------------


class ReadinessSourceOut(BaseModel):
    kind: Literal["requirement", "finding"]
    key: str
    label: str
    detail: str | None = None
    code: str | None = None
    severity: str | None = None
    question_id: str | None = None


class ReadinessDeductionOut(BaseModel):
    reason: str
    amount: int
    source: ReadinessSourceOut


class ReadinessBreakdownOut(BaseModel):
    base_score: int
    deductions: list[ReadinessDeductionOut] = []
    deducted: int
    final_score: int
    status: str


class ReadinessBlockingItemOut(BaseModel):
    # "document" is a document of the claim that has not been read yet: until it has, what the
    # claim adds up to is not known, so it is outstanding in its own right.
    kind: Literal["requirement", "finding", "document"]
    key: str
    label: str
    detail: str | None = None
    action: str | None = None


class ReadinessSectionOut(BaseModel):
    """What the documentation is still waiting for, and what that costs."""

    score: int
    status: Literal["incomplete", "needs_attention", "ready_for_human_review"]
    status_label: str
    status_detail: str
    breakdown: ReadinessBreakdownOut
    blocking_items: list[ReadinessBlockingItemOut] = []
    summary: dict[str, Any] = {}


class ReviewSectionOut(BaseModel):
    state: Literal["draft", "approved", "superseded"]
    approved: bool = False
    # The claim changed after it was approved: the approval is on the record, and no longer
    # stands for the claim as it is now.
    superseded: bool = False
    approved_by: str | None = None
    approved_at: UTCDateTime | None = None
    approval_note: str | None = None
    review_started_at: UTCDateTime | None = None
    superseded_at: UTCDateTime | None = None
    approved_readiness: dict[str, Any] = {}
    can_approve: bool = False


class ReadinessResponse(ReadinessSectionOut):
    claim_id: str
    claim_number: str
    review: ReviewSectionOut
    workflow: list[dict[str, Any]] = []


class ApprovalRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("must not contain control characters")
        return value or None


class ApprovalResult(BaseModel):
    claim_id: str
    claim_number: str
    review: ReviewSectionOut
    readiness: ReadinessSectionOut


class DashboardClaimOut(BaseModel):
    claim_id: str
    claim_number: str
    patient_name: str
    uhid: str
    hospital: str
    insurer: str
    procedure: str | None = None
    procedure_key: str | None = None
    document_count: int
    processed_count: int
    open_findings: int
    open_questions: int
    readiness_score: int
    readiness_status: str
    readiness_status_label: str
    review_state: str
    approved_by: str | None = None
    approved_at: UTCDateTime | None = None
    superseded_at: UTCDateTime | None = None
    status: str
    is_demo: bool
    created_at: UTCDateTime
    updated_at: UTCDateTime


class DashboardActivityOut(BaseModel):
    id: int
    event_type: str
    actor: str
    message: str
    claim_id: str | None = None
    document_id: str | None = None
    created_at: UTCDateTime | None = None


class DashboardResponse(BaseModel):
    totals: dict[str, int]
    claims: list[DashboardClaimOut] = []
    recent_activity: list[DashboardActivityOut] = []
    limit: int
    truncated: bool = False


class ReportReviewOut(ReviewSectionOut):
    """The human review as a report states it.

    `line` is the one sentence every rendering of the report uses, so the page, the PDF, the
    workbook and this JSON cannot describe the same review differently.
    """

    line: str


class ReportResponse(BaseModel):
    """The claim pre-submission report.

    Assembled from the canonical claim, the findings, the checks, the checklist, the questions,
    the readiness and the audit trail. The PDF, the workbook and the HTML page render this
    payload, so nothing can differ between them. Four kinds of statement are kept apart:
    documented facts, system findings, unresolved items and human decisions.
    """

    meta: dict[str, Any]
    claim: dict[str, Any]
    summary: dict[str, Any]
    readiness: ReadinessSectionOut
    review: ReportReviewOut
    documented_facts: list[dict[str, Any]] = []
    system_findings: list[dict[str, Any]] = []
    validation_checks: list[dict[str, Any]] = []
    checklist: dict[str, Any]
    questions: list[dict[str, Any]] = []
    human_decisions: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    bills: dict[str, Any]
    investigations: list[dict[str, Any]] = []
    audit_trail: list[dict[str, Any]] = []


class ClaimStateOut(BaseModel):
    """The canonical claim: one structured claim assembled from the documents."""

    claim: ClaimHeaderOut
    meta: CanonicalMetaOut
    patient: CanonicalSectionOut
    admission: CanonicalSectionOut
    diagnosis: CanonicalSectionOut
    procedures: ProceduresSectionOut
    doctors: CanonicalSectionOut
    investigations: InvestigationsSectionOut
    documents: DocumentsSectionOut
    bills: BillsSectionOut
    checklist: ChecklistSectionOut
    readiness: ReadinessSectionOut
    review: ReviewSectionOut
    findings: CanonicalFindingsSectionOut
    questions: CanonicalQuestionsSectionOut
    resolutions: CanonicalResolutionsSectionOut
    audit_events: AuditEventsSectionOut
    snapshot: SnapshotOut


# --- Validation and findings (phase 5) ---------------------------------------------------


class FindingEvidenceOut(BaseModel):
    """Where a finding's facts came from. A page it cannot point at is reported as unavailable."""

    kind: str
    document_id: str | None = None
    document_name: str | None = None
    document_type: str | None = None
    document_type_label: str | None = None
    page: int | None = None
    bounding_box: list[float] | None = None
    snippet: str | None = None
    method: str
    source_type: str | None = None
    confidence: float | None = None
    value: str | None = None
    field_key: str | None = None
    detail: str | None = None
    evidence_available: bool = False


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_id: str
    rule_id: str
    code: str
    category: str
    severity: Literal["critical", "review", "warning", "info"]
    title: str
    explanation: str
    action: str
    attribution: Literal["rule", "source", "ai"]
    subject: str
    fingerprint: str
    status: Literal["open", "resolved", "acknowledged", "auto_closed", "reopened"]
    status_note: str | None = None
    status_actor: str | None = None
    status_changed_at: UTCDateTime | None = None
    reviewed_at: UTCDateTime | None = None
    reviewed_by: str | None = None
    occurrences: int
    first_seen_at: UTCDateTime
    last_seen_at: UTCDateTime
    evidence: list[FindingEvidenceOut] = []
    context: dict[str, Any] = {}
    is_active: bool = False
    actions_available: list[str] = []


class FindingSummaryOut(BaseModel):
    total: int
    active: int
    by_severity: dict[str, int]
    active_by_severity: dict[str, int]
    by_status: dict[str, int]


class ValidationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rules_version: int
    input_fingerprint: str
    findings_raised: int
    findings_created: int
    findings_auto_closed: int
    findings_reopened: int
    duration_ms: int | None = None
    summary: dict[str, Any] = {}
    created_at: UTCDateTime
    updated_at: UTCDateTime


class FindingsResponse(BaseModel):
    claim_id: str
    claim_number: str
    count: int
    summary: FindingSummaryOut
    run: ValidationRunOut | None = None
    items: list[FindingOut] = []


class CheckOut(BaseModel):
    check_id: str
    title: str
    category: str
    status: Literal["pass", "fail", "pending", "not_applicable"]
    detail: str
    rule_ids: list[str] = []
    finding_count: int = 0
    finding_codes: list[str] = []
    finding_fingerprints: list[str] = []
    severity: str | None = None
    subjects_checked: int = 0


class ChecksResponse(BaseModel):
    claim_id: str
    claim_number: str
    rules_version: int
    count: int
    summary: dict[str, Any] = {}
    run: ValidationRunOut | None = None
    items: list[CheckOut] = []


class FindingActionRequest(BaseModel):
    action: Literal["review", "resolve", "acknowledge", "reopen", "exclude_duplicate"]
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("must not contain control characters")
        return value or None


class FindingActionResult(BaseModel):
    finding: FindingOut
    summary: FindingSummaryOut


class ValidationRefreshResult(BaseModel):
    claim_id: str
    claim_number: str
    ran: bool
    findings_raised: int
    findings_created: int
    findings_auto_closed: int
    findings_reopened: int
    summary: FindingSummaryOut
    run: ValidationRunOut | None = None


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
