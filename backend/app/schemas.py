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
    source: str
    demo_set: str | None
    uploaded_by: str
    uploaded_at: UTCDateTime


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
