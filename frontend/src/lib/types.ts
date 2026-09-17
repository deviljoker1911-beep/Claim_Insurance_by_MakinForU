export interface DatabaseStatus {
  ok: boolean
  dialect: string
  database: string | null
  host: string | null
  port: number | null
  server_version: string | null
  error: string | null
}

export interface EngineStatus {
  key: string
  name: string
  role: string
  optional: boolean
  available: boolean
  version: string | null
}

export interface LLMStatus {
  provider: 'demo' | 'anthropic' | 'openai'
  model: string
  api_key_configured: boolean
  mode: 'offline-deterministic' | 'remote'
}

export interface OcrStatus {
  preference: string
  engines: string[]
  active: string | null
  offline: boolean
  note: string
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  app: string
  version: string
  environment: string
  demo_mode: boolean
  server_time: string
  database: DatabaseStatus
  engines: EngineStatus[]
  ocr: OcrStatus
  llm: LLMStatus
}

export interface Claim {
  id: string
  claim_number: string
  patient_name: string
  uhid: string
  hospital: string
  insurer: string
  tpa: string | null
  admission_date: string
  discharge_date: string
  status: string
  is_demo: boolean
  created_by: string
  created_at: string
  updated_at: string
  document_count: number
}

export interface QualityFlag {
  code: string
  severity: 'review' | 'attention' | 'info'
  detail: string
  pages: number[]
  [measurement: string]: unknown
}

export interface ClaimDocument {
  id: string
  claim_id: string
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  page_count: number | null
  file_metadata: Record<string, unknown>
  upload_status: string
  processing_status: string
  processing_stage: string | null
  stage_label: string | null
  processing_error: string | null
  doc_type: string | null
  doc_type_label: string | null
  doc_type_confidence: number | null
  text_source: string | null
  ocr_engine: string | null
  ocr_confidence: number | null
  quality_flags: QualityFlag[]
  concealed_text_count: number
  source: string
  demo_set: string | null
  uploaded_by: string
  uploaded_at: string
}

export interface ClaimDetail extends Claim {
  documents: ClaimDocument[]
}

export interface ClaimInput {
  patient_name: string
  uhid: string
  hospital: string
  insurer: string
  tpa: string | null
  admission_date: string
  discharge_date: string
  is_demo: boolean
}

export interface FileError {
  /** Position of the file in the upload request (file names are not unique). */
  index: number
  filename: string
  error: string
}

export interface UploadResult {
  claim_id: string
  documents: ClaimDocument[]
  skipped: { filename: string; reason: string }[]
}

export type DemoSet = 'initial' | 'operative_note' | 'anaesthesia_record'

export interface DemoAttachResult extends UploadResult {
  set: DemoSet
  attached_count: number
  skipped_count: number
}

export interface DemoClaimProfile {
  patient_name: string
  uhid: string
  hospital: string
  insurer: string
  tpa: string
  admission_date: string
  discharge_date: string
}

export interface DemoResetResult {
  status: 'ok'
  deleted: { claims: number; documents: number; audit_events: number }
  storage_cleared: boolean
  demo_data: {
    files: number
    written: number
    verified: boolean
    generator_matches_manifest: boolean
    mismatched_files: string[]
    manifest_sha256: string
  }
  next_claim_number: string
  preserved: string[]
  reset_at: string
}

/** --- Document intelligence (phase 3) --- */

export interface ProcessingStage {
  key: string
  label: string
}

export interface FlagCounts {
  total: number
  review: number
  attention: number
}

export interface DocumentProcessing {
  document_id: string
  filename: string
  processing_status: 'pending' | 'queued' | 'processing' | 'processed' | 'failed'
  processing_stage: string | null
  stage_label: string | null
  progress: number
  doc_type: string | null
  doc_type_label: string | null
  doc_type_confidence: number | null
  page_count: number | null
  text_source: string | null
  ocr_engine: string | null
  ocr_confidence: number | null
  quality_flag_counts: FlagCounts
  concealed_text_count: number
  processing_error: string | null
  processing_duration_ms: number | null
  processing_started_at: string | null
  processing_completed_at: string | null
}

export interface WorkerStatus {
  running: boolean
  queue_depth: number
  current_document_id: string | null
  processed: number
  failed: number
}

export interface ClaimProcessing {
  claim_id: string
  claim_number: string
  claim_status: string
  state: 'idle' | 'running' | 'partial' | 'completed' | 'completed_with_failures'
  counts: Record<string, number>
  document_count: number
  progress: number
  started_at: string | null
  completed_at: string | null
  stages: ProcessingStage[]
  documents: DocumentProcessing[]
  worker: WorkerStatus
}
