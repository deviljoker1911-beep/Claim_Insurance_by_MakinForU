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

/** --- Canonical claim (phase 4) --- */

export interface EvidenceSource {
  document_id: string
  document_name: string
  document_type: string | null
  document_type_label: string | null
  page: number | null
  bounding_box: number[] | null
  snippet: string | null
  method: string
  source_type: string
  source_type_label: string
  extraction_method: string
  confidence: number | null
  /** How much this document counted in canonical value selection; absent for finding evidence. */
  weight: number | null
  eligible: boolean
  excluded_reason: string | null
  value: string | null
  raw_value: string | null
  field_key: string
  derived_from: string | null
  detail?: string | null
  evidence_available: boolean
}

export interface ValueVariant {
  value: string
  source_count: number
}

export interface CompetingValue {
  value: string
  normalized_value: string
  weight: number
  source_count: number
  eligible_source_count: number
  value_variants: ValueVariant[]
  sources: EvidenceSource[]
}

export interface CanonicalValue {
  key: string
  label: string
  kind: string
  section: string
  present: boolean
  value: string | null
  normalized_value: string | null
  confidence: number | null
  weight: number | null
  source_count: number
  value_variants: ValueVariant[]
  sources: EvidenceSource[]
  evidence_available: boolean
  competing_values: CompetingValue[]
  has_competing_values: boolean
  note: string | null
}

export interface CanonicalSection {
  fields: Record<string, CanonicalValue>
  present_count: number
  field_count: number
}

export interface ProcedureItem {
  procedure_key: string | null
  label: string
  value: string
  normalized_value: string
  weight: number
  source_count: number
  value_variants: ValueVariant[]
  sources: EvidenceSource[]
  is_selected: boolean
}

export interface CanonicalBillLine {
  line_no: number | null
  description: string | null
  quantity: string | null
  rate: string | null
  amount: string | null
  batch: string | null
  expiry: string | null
  evidence: {
    document_id: string
    document_name: string
    document_type: string | null
    page: number | null
    bounding_box: number[] | null
    snippet: string | null
    method: string
    source_type: string
    confidence: number | null
    evidence_available: boolean
  }
}

export interface CanonicalBill {
  document_id: string
  document_name: string
  bill_type: string | null
  bill_type_label: string | null
  currency: string
  page_number: number | null
  columns: string[]
  notes: string[]
  line_item_count: number
  line_items: CanonicalBillLine[]
  fields: Record<string, CanonicalValue>
}

export interface BillTotal {
  document_id: string
  document_name: string
  bill_type: string | null
  bill_type_label: string | null
  bill_number: string | null
  bill_date: string | null
  total: string | null
  currency: string
}

export interface DocumentInventoryItem {
  document_id: string
  filename: string
  doc_type: string | null
  doc_type_label: string | null
  classification_confidence: number | null
  classification_method: string | null
  processing_status: string
  processing_stage: string | null
  processing_error: string | null
  page_count: number | null
  quality_signals: QualityFlag[]
  quality_signal_count: number
  ocr_method: string | null
  ocr_engine: string | null
  ocr_confidence: number | null
  text_source: string | null
  concealed_text_count: number
  unsigned_required_slots: (string | null)[]
  extracted_field_count: number
  source: string
  demo_set: string | null
  sha256: string
  size_bytes: number
  uploaded_at: string | null
  excluded: boolean
  exclusion_reason: string | null
  duplicate_of: string | null
  duplicate_state: string
}

export interface PendingSection {
  available: boolean
  count: number
  items: unknown[]
  note: string
}

export interface ClaimState {
  claim: {
    claim_id: string
    claim_number: string
    status: string
    is_demo: boolean
    hospital: string
    insurer: string
    tpa: string | null
    created_by: string
    created_at: string | null
    form: {
      patient_name: string
      uhid: string
      hospital: string
      insurer: string
      tpa: string | null
      admission_date: string | null
      discharge_date: string | null
    }
  }
  meta: {
    generator_version: number
    analysis_state: string
    document_counts: Record<string, number>
    value_selection: {
      document_weights: Record<string, number>
      default_weight: number
      ocr_confidence_floor: number
      rule: string
    }
    pending_sections: Record<string, string>
  }
  patient: CanonicalSection
  admission: CanonicalSection
  diagnosis: CanonicalSection
  procedures: {
    selected_key: string | null
    selected: CanonicalValue | null
    items: ProcedureItem[]
    fields: Record<string, CanonicalValue>
  }
  doctors: CanonicalSection
  investigations: {
    count: number
    items: {
      document_id: string
      document_name: string
      doc_type: string | null
      doc_type_label: string | null
      page_count: number | null
      fields: Record<string, CanonicalValue>
    }[]
  }
  documents: {
    count: number
    items: DocumentInventoryItem[]
    by_type: Record<string, number>
    excluded_count: number
    note: string | null
  }
  bills: {
    count: number
    items: CanonicalBill[]
    summary: { by_type: Record<string, number>; totals: BillTotal[] }
    note: string | null
  }
  checklist: ChecklistSection
  findings: PendingSection
  questions: PendingSection
  resolutions: PendingSection
  audit_events: {
    count: number
    included: number
    items: { id: number; event_type: string; actor: string; message: string; document_id: string | null; created_at: string | null }[]
  }
  snapshot: {
    content_sha256: string
    generator_version: number
    generated_at: string
    document_count: number
    processed_count: number
  }
}

/** --- Validation and findings (phase 5) --- */

export type Severity = 'critical' | 'review' | 'warning' | 'info'
export type FindingStatus = 'open' | 'resolved' | 'acknowledged' | 'auto_closed' | 'reopened'
export type FindingAction = 'review' | 'resolve' | 'acknowledge' | 'reopen' | 'exclude_duplicate'
export type CheckStatus = 'pass' | 'fail' | 'pending' | 'not_applicable'

export interface FindingEvidence {
  kind: string
  document_id: string | null
  document_name: string | null
  document_type: string | null
  document_type_label: string | null
  page: number | null
  bounding_box: number[] | null
  snippet: string | null
  method: string
  source_type: string | null
  confidence: number | null
  value: string | null
  field_key: string | null
  detail: string | null
  evidence_available: boolean
}

export interface Finding {
  id: string
  claim_id: string
  rule_id: string
  code: string
  category: string
  severity: Severity
  title: string
  explanation: string
  action: string
  attribution: 'rule' | 'source' | 'ai'
  subject: string
  fingerprint: string
  status: FindingStatus
  status_note: string | null
  status_actor: string | null
  status_changed_at: string | null
  reviewed_at: string | null
  reviewed_by: string | null
  occurrences: number
  first_seen_at: string
  last_seen_at: string
  evidence: FindingEvidence[]
  context: Record<string, unknown>
  is_active: boolean
  actions_available: FindingAction[]
}

export interface FindingSummary {
  total: number
  active: number
  by_severity: Record<string, number>
  active_by_severity: Record<string, number>
  by_status: Record<string, number>
}

export interface ValidationRun {
  rules_version: number
  input_fingerprint: string
  findings_raised: number
  findings_created: number
  findings_auto_closed: number
  findings_reopened: number
  duration_ms: number | null
  summary: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface FindingsResponse {
  claim_id: string
  claim_number: string
  count: number
  summary: FindingSummary
  run: ValidationRun | null
  items: Finding[]
}

export interface ValidationCheck {
  check_id: string
  title: string
  category: string
  status: CheckStatus
  detail: string
  rule_ids: string[]
  finding_count: number
  finding_codes: string[]
  finding_fingerprints: string[]
  severity: Severity | null
  subjects_checked: number
}

export interface ChecksResponse {
  claim_id: string
  claim_number: string
  rules_version: number
  count: number
  summary: Record<string, number>
  run: ValidationRun | null
  items: ValidationCheck[]
}

export interface FindingActionResult {
  finding: Finding
  summary: FindingSummary
}

/** --- Procedure checklist (phase 6) --- */

export type ChecklistStatus = 'found' | 'missing' | 'review_required' | 'not_applicable'

export interface ChecklistEvidence {
  document_id: string
  document_name: string
  doc_type: string | null
  doc_type_label: string | null
  classification_confidence: number | null
  classification_method: string | null
  page_count: number | null
  page: number | null
  detail: string
}

export interface ChecklistFindingRef {
  id: string
  rule_id: string
  code: string
  severity: Severity
  status: FindingStatus
  title: string
  subject: string
  is_active: boolean
  document_ids: string[]
}

export interface ChecklistItem {
  key: string
  label: string
  description: string
  doc_types: string[]
  doc_type_labels: string[]
  required: boolean
  severity: Severity
  applies_when: string
  resolution: string
  status: ChecklistStatus
  detail: string
  evidence: ChecklistEvidence[]
  findings: ChecklistFindingRef[]
}

export interface ChecklistProcedure {
  key: string | null
  label: string
  has_checklist: boolean
  source_count: number
  documents: { document_id: string; document_name: string; value: string | null; page: number | null }[]
  written_as: string[]
  also_named: { key: string | null; label: string; source_count: number }[]
}

export interface ChecklistSummary {
  found: number
  missing: number
  review_required: number
  not_applicable: number
  total: number
  required: number
  required_outstanding: number
  by_severity: Record<Severity, number>
}

export interface ChecklistSection {
  available: boolean
  checklist_version: number
  procedure: ChecklistProcedure
  provisional: boolean
  count: number
  summary: ChecklistSummary
  items: ChecklistItem[]
  configured_procedures: { key: string | null; label: string; source_count: number }[]
  note: string | null
}

export interface ChecklistResponse extends ChecklistSection {
  claim_id: string
  claim_number: string
}

/** --- Questions, re-analysis and the assistant (phase 7) --- */

export type QuestionStatus = 'open' | 'answered' | 'resolved' | 'documented_unavailable' | 'not_applicable'
export type QuestionAnswer = 'yes_have_it' | 'not_available' | 'not_applicable'

export interface QuestionUpload {
  document_id: string
  document_name: string
  doc_type: string | null
  doc_type_label: string | null
  expected_document_types: string[]
  satisfies: boolean
  message: string
  checked_at: string | null
}

export interface Question {
  id: string
  claim_id: string
  requirement_key: string
  requirement_label: string
  procedure_key: string | null
  question: string
  reason: string
  status: QuestionStatus
  severity: Severity
  expected_document_type: string
  expected_document_types: string[]
  answer: QuestionAnswer | null
  answer_reason: string | null
  answered_at: string | null
  answered_by: string | null
  resolved_document_id: string | null
  resolved_at: string | null
  last_upload: QuestionUpload | null
  created_at: string
  updated_at: string
  actions_available: QuestionAnswer[]
}

export interface QuestionsResponse {
  claim_id: string
  claim_number: string
  count: number
  summary: { total: number; open: number; by_status: Record<string, number> }
  items: Question[]
}

export interface QuestionAnswerResult {
  question: Question
  upload: {
    endpoint: string
    expected_document_type: string
    expected_document_types: string[]
    instruction: string
  } | null
}

export type ChangeKind = 'document' | 'finding' | 'checklist' | 'canonical' | 'question' | 'procedure'

export interface Change {
  kind: ChangeKind
  key: string
  label: string
  before: string | null
  after: string | null
  headline: string
  severity: Severity | null
  code: string | null
  document_id: string | null
  finding_id: string | null
  question_id: string | null
  requirement: string | null
}

export interface ReanalysisRun {
  id: string
  claim_id: string
  sequence: number
  trigger: string
  summary: {
    changes: number
    documents_added: number
    findings_opened: number
    findings_auto_closed: number
    questions_asked: number
    questions_resolved: number
    checklist_changed: number
    canonical_changed: number
    outstanding_requirements: number
  }
  changes: Change[]
  documents_added: { document_id: string; filename: string }[]
  started_at: string
  completed_at: string | null
  duration_ms: number | null
}

export interface ReanalysisResponse {
  claim_id: string
  claim_number: string
  latest: ReanalysisRun | null
  history: ReanalysisRun[]
}

export interface AssistantCitation {
  kind: 'finding' | 'document' | 'requirement' | 'question' | 'claim'
  id: string
  label: string
  detail: string | null
  document_id: string | null
  page: number | null
}

export interface AssistantAnswer {
  claim_id: string
  claim_number: string
  question: string
  intent: string
  answer: string
  citations: AssistantCitation[]
  suggested_questions: string[]
  provider: { name: string; model: string; mode: string; api_key_configured: boolean; fell_back_to?: string }
  notice: string
  removed_citations: string[]
}

/** --- Readiness, review and the dashboard (phase 8) --- */

export type ReadinessStatus = 'incomplete' | 'needs_attention' | 'ready_for_human_review'

export interface ReadinessDeduction {
  reason: string
  amount: number
  source: {
    kind: 'requirement' | 'finding'
    key: string
    label: string
    detail?: string | null
    code?: string | null
    severity?: Severity | null
    question_id?: string | null
  }
}

export interface ReadinessBreakdown {
  base_score: number
  deductions: ReadinessDeduction[]
  deducted: number
  final_score: number
  /** False while nothing of the claim has been read: there is no documentation to count yet. */
  counted: boolean
  status: ReadinessStatus
}

export interface ReadinessBlockingItem {
  /** 'document' is a document of the claim that has not been read yet. */
  kind: 'requirement' | 'finding' | 'document'
  key: string
  label: string
  detail: string | null
  action: string | null
}

export interface ReadinessSection {
  score: number
  status: ReadinessStatus
  status_label: string
  status_detail: string
  breakdown: ReadinessBreakdown
  blocking_items: ReadinessBlockingItem[]
  summary: {
    required_missing: number
    documented_unavailable: number
    not_applicable: number
    checklist_reviews: number
    open_findings: number
    counted_findings: number
    findings_by_severity: Record<Severity, number>
    open_questions: number
    checklist_available: boolean
  }
}

export interface ReviewSection {
  state: 'draft' | 'approved' | 'superseded'
  approved: boolean
  /** The claim changed after it was approved, so the approval no longer stands for it. */
  superseded: boolean
  approved_by: string | null
  approved_at: string | null
  approval_note: string | null
  review_started_at: string | null
  superseded_at: string | null
  approved_readiness: { score?: number; status?: string; deducted?: number; counted_findings?: number }
  can_approve: boolean
}

export type WorkflowStepStatus = 'pending' | 'current' | 'complete'

export interface WorkflowStep {
  key: string
  label: string
  status: WorkflowStepStatus
  detail: string
}

export interface ReadinessResponse extends ReadinessSection {
  claim_id: string
  claim_number: string
  review: ReviewSection
  workflow: WorkflowStep[]
}

export interface ApprovalResult {
  claim_id: string
  claim_number: string
  review: ReviewSection
  readiness: ReadinessSection
}

export interface DashboardClaim {
  claim_id: string
  claim_number: string
  patient_name: string
  uhid: string
  hospital: string
  insurer: string
  procedure: string | null
  procedure_key: string | null
  document_count: number
  processed_count: number
  open_findings: number
  open_questions: number
  readiness_score: number
  readiness_status: ReadinessStatus
  readiness_status_label: string
  review_state: 'draft' | 'approved' | 'superseded'
  approved_by: string | null
  approved_at: string | null
  superseded_at: string | null
  status: string
  is_demo: boolean
  created_at: string
  updated_at: string
}

export interface DashboardResponse {
  totals: {
    claims: number
    incomplete: number
    needs_attention: number
    ready_for_human_review: number
    approved: number
    average_readiness: number
    open_findings: number
    open_questions: number
    documents: number
  }
  claims: DashboardClaim[]
  recent_activity: {
    id: number
    event_type: string
    actor: string
    message: string
    claim_id: string | null
    document_id: string | null
    created_at: string | null
  }[]
  limit: number
  truncated: boolean
}
