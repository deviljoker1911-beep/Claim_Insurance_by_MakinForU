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

export interface HealthResponse {
  status: 'ok' | 'degraded'
  app: string
  version: string
  environment: string
  demo_mode: boolean
  server_time: string
  database: DatabaseStatus
  engines: EngineStatus[]
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
