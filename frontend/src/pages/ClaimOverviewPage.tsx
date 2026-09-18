import {
  ArrowLeft,
  ClipboardList,
  FileStack,
  FlaskConical,
  Receipt,
  ScanText,
  SearchX,
  Stethoscope,
  UserRound,
} from 'lucide-react'
import { useState } from 'react'
import { useParams } from 'react-router'

import { BillsPanel } from '../components/canonical/BillsPanel'
import { CanonicalFieldList, CanonicalFieldRow, SourceChip } from '../components/canonical/CanonicalField'
import { DocumentInventory } from '../components/canonical/DocumentInventory'
import { EvidenceViewer, type EvidenceRequest } from '../components/canonical/EvidenceViewer'
import { ClaimStatusBadge } from '../components/claims/ClaimStatusBadge'
import { Badge } from '../components/ui/Badge'
import { ButtonLink } from '../components/ui/Button'
import { Card, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { Notice } from '../components/ui/Notice'
import { PageHeader } from '../components/ui/PageHeader'
import { Skeleton } from '../components/ui/Skeleton'
import { ApiError } from '../lib/api'
import { formatDate, formatDateTime, plural } from '../lib/format'
import { useClaimState } from '../lib/hooks'
import type { CanonicalValue, ClaimState, ProcedureItem } from '../lib/types'

export function ClaimOverviewPage() {
  const { claimId = '' } = useParams()
  const query = useClaimState(claimId)
  const [evidence, setEvidence] = useState<EvidenceRequest | null>(null)

  if (query.isPending) return <OverviewSkeleton />
  const notFound = query.error instanceof ApiError && query.error.status === 404
  if (!query.data || notFound) {
    return (
      <Card>
        <EmptyState
          icon={SearchX}
          title={notFound ? 'Claim not found' : 'The claim could not be loaded'}
          description={notFound ? 'It may have been removed by a demo reset.' : query.error?.message}
          action={<ButtonLink to="/claims">Back to My Claims</ButtonLink>}
        />
      </Card>
    )
  }

  const state = query.data
  const counts = state.meta.document_counts
  const processed = counts.processed ?? 0
  const analysed = processed > 0
  const values = [state.patient, state.admission, state.diagnosis, state.doctors]
  const presentValues = values.reduce((sum, section) => sum + section.present_count, 0)
  const totalValues = values.reduce((sum, section) => sum + section.field_count, 0)

  return (
    <>
      <PageHeader
        title={`Claim ${state.claim.claim_number}`}
        description="One structured claim, assembled from the documents. Every value keeps the page it was read from."
        actions={
          <>
            <ButtonLink to={`/claims/${claimId}/intake`} variant="secondary" size="sm">
              <FileStack className="size-4" />
              Documents
            </ButtonLink>
            <ButtonLink to="/claims" variant="ghost" size="sm">
              <ArrowLeft className="size-4" />
              My Claims
            </ButtonLink>
          </>
        }
      />

      {!analysed && (
        <Notice tone="info" className="mb-6">
          No documents have been analysed yet, so the canonical claim is empty. Upload documents and run the analysis
          from the <span className="font-medium">Documents</span> screen.
        </Notice>
      )}

      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          icon={FileStack}
          label="Documents analysed"
          value={`${processed}`}
          hint={`of ${plural(state.documents.count, 'document')}`}
        />
        <Stat
          icon={ClipboardList}
          label="Document types"
          value={`${Object.keys(state.documents.by_type).length}`}
          hint="recognised from content"
        />
        <Stat
          icon={Receipt}
          label="Bills read"
          value={`${state.bills.count}`}
          hint={Object.keys(state.bills.summary.by_type)
            .map((type) => type.replace('_', ' '))
            .join(', ')}
        />
        <Stat
          icon={ScanText}
          label="Values from documents"
          value={`${presentValues} / ${totalValues}`}
          hint="each with its source"
        />
      </div>

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-6">
          <Card data-testid="patient-panel">
            <CardHeader
              title="Patient"
              description="Read from the documents, not from the claim form."
              actions={<SectionBadge icon={UserRound} section={state.patient} />}
            />
            <CanonicalFieldList
              values={[
                state.patient.fields.name,
                state.patient.fields.age,
                state.patient.fields.gender,
                state.patient.fields.uhid,
                state.patient.fields.ipd,
                state.patient.fields.date_of_birth,
              ]}
              onOpen={setEvidence}
            />
          </Card>

          <Card data-testid="admission-panel">
            <CardHeader title="Admission and cover" description="Stay, ward and the insurance cover as documented." />
            <CanonicalFieldList
              values={[
                state.admission.fields.admission_date,
                state.admission.fields.discharge_date,
                state.admission.fields.surgery_date,
                state.admission.fields.ward,
                state.admission.fields.admission_type,
                state.admission.fields.insurer,
                state.admission.fields.tpa,
                state.admission.fields.policy_number,
                state.admission.fields.member_id,
                state.admission.fields.sum_insured,
              ]}
              onOpen={setEvidence}
            />
          </Card>

          <Card data-testid="clinical-panel">
            <CardHeader
              title="Diagnosis and procedure"
              actions={<SectionBadge icon={Stethoscope} section={state.diagnosis} />}
            />
            <dl className="divide-y divide-slate-100 px-5 py-1">
              {state.diagnosis.fields.primary && (
                <CanonicalFieldRow value={state.diagnosis.fields.primary} onOpen={setEvidence} />
              )}
              {state.diagnosis.fields.icd10 && (
                <CanonicalFieldRow value={state.diagnosis.fields.icd10} onOpen={setEvidence} />
              )}
              <ProcedureRows procedures={state.procedures.items} onOpen={setEvidence} />
              {state.procedures.fields.anaesthesia && (
                <CanonicalFieldRow value={state.procedures.fields.anaesthesia} onOpen={setEvidence} />
              )}
            </dl>
          </Card>

          <Card data-testid="doctors-panel">
            <CardHeader title="Doctors" />
            <CanonicalFieldList
              values={[state.doctors.fields.surgeon, state.doctors.fields.anaesthetist]}
              onOpen={setEvidence}
            />
          </Card>

          <Card data-testid="bills-panel">
            <CardHeader
              title="Bills"
              description={
                state.bills.count
                  ? `${plural(state.bills.count, 'bill')} · ${state.bills.items.reduce((sum, bill) => sum + bill.line_item_count, 0)} line items · open a row to see the lines`
                  : 'No bills read yet'
              }
            />
            <BillsPanel bills={state.bills.items} onOpen={setEvidence} />
          </Card>

          {state.investigations.count > 0 && (
            <Card data-testid="investigations-panel">
              <CardHeader title="Investigations" description="Reports and their identifiers, as documented." />
              <div className="space-y-4 p-5">
                {state.investigations.items.map((item) => (
                  <div key={item.document_id} className="rounded-lg border border-slate-200 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <p className="flex min-w-0 items-center gap-2 text-sm font-medium text-slate-900">
                        <FlaskConical className="size-4 shrink-0 text-slate-400" />
                        <span className="truncate" title={item.document_name}>
                          {item.document_name}
                        </span>
                      </p>
                      {item.doc_type_label && <Badge tone="brand">{item.doc_type_label}</Badge>}
                    </div>
                    <dl className="mt-2 divide-y divide-slate-100">
                      {Object.values(item.fields)
                        .filter((value) => value.present)
                        .map((value) => (
                          <CanonicalFieldRow key={value.key + item.document_id} value={value} onOpen={setEvidence} />
                        ))}
                    </dl>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card data-testid="documents-panel">
            <CardHeader
              title="Documents"
              description={`${plural(state.documents.count, 'document')} · ${Object.keys(state.documents.by_type).length} types`}
            />
            <DocumentInventory items={state.documents.items} claimId={claimId} />
          </Card>
        </div>

        <aside className="space-y-6 xl:sticky xl:top-24">
          <ClaimRecord state={state} />
          <Card className="p-5" data-testid="selection-panel">
            <p className="text-[15px] font-semibold text-slate-900">How values were chosen</p>
            <p className="mt-1 text-sm text-slate-500">{state.meta.value_selection.rule}</p>
            <ul className="mt-3 space-y-1.5 text-sm">
              {Object.entries(state.meta.value_selection.document_weights).map(([type, weight]) => (
                <li key={type} className="flex items-center justify-between gap-3">
                  <span className="text-slate-600">{type.replaceAll('_', ' ')}</span>
                  <span className="font-medium text-slate-900 tabular-nums">×{weight}</span>
                </li>
              ))}
              <li className="flex items-center justify-between gap-3">
                <span className="text-slate-600">every other document</span>
                <span className="font-medium text-slate-900 tabular-nums">
                  ×{state.meta.value_selection.default_weight}
                </span>
              </li>
              <li className="flex items-center justify-between gap-3 border-t border-slate-100 pt-1.5">
                <span className="text-slate-600">OCR confidence floor</span>
                <span className="font-medium text-slate-900 tabular-nums">
                  {Math.round(state.meta.value_selection.ocr_confidence_floor * 100)}%
                </span>
              </li>
            </ul>
          </Card>

          <Card className="p-5" data-testid="pending-panel">
            <p className="text-[15px] font-semibold text-slate-900">Still to come</p>
            <ul className="mt-2 space-y-2 text-sm text-slate-500">
              {Object.entries(state.meta.pending_sections).map(([section, note]) => (
                <li key={section} className="flex gap-2">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-slate-300" />
                  <span>
                    <span className="font-medium text-slate-700 capitalize">{section}</span> — {note}
                  </span>
                </li>
              ))}
            </ul>
          </Card>

          <Card className="p-5">
            <p className="text-[15px] font-semibold text-slate-900">Snapshot</p>
            <dl className="mt-2 space-y-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-500">Built</dt>
                <dd className="font-medium text-slate-900">{formatDateTime(state.snapshot.generated_at)}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-500">Content hash</dt>
                <dd className="font-mono text-xs text-slate-700" title={state.snapshot.content_sha256}>
                  {state.snapshot.content_sha256.slice(0, 12)}…
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-500">Audit events</dt>
                <dd className="font-medium text-slate-900 tabular-nums">{state.audit_events.count}</dd>
              </div>
            </dl>
          </Card>
        </aside>
      </div>

      {evidence && <EvidenceViewer request={evidence} onClose={() => setEvidence(null)} />}
    </>
  )
}

function Stat({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof FileStack
  label: string
  value: string
  hint?: string
}) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600">
        <Icon className="size-4.5" />
      </span>
      <div className="min-w-0">
        <p className="text-xs text-slate-500">{label}</p>
        <p className="text-[17px] leading-tight font-semibold text-slate-900 tabular-nums">{value}</p>
        {hint && <p className="truncate text-xs text-slate-400 capitalize">{hint}</p>}
      </div>
    </Card>
  )
}

function SectionBadge({ icon: Icon, section }: { icon: typeof UserRound; section: ClaimState['patient'] }) {
  return (
    <Badge tone={section.present_count === section.field_count ? 'success' : 'neutral'}>
      <Icon className="size-3.5" />
      {section.present_count}/{section.field_count} documented
    </Badge>
  )
}

function ProcedureRows({
  procedures,
  onOpen,
}: {
  procedures: ProcedureItem[]
  onOpen: (request: EvidenceRequest) => void
}) {
  if (procedures.length === 0) {
    return (
      <div className="flex items-start justify-between gap-4 py-2.5" data-testid="procedure-row" data-present="false">
        <dt className="text-sm text-slate-500">Procedure</dt>
        <dd className="text-sm text-slate-400">No procedure is named in the documents</dd>
      </div>
    )
  }
  return (
    <>
      {procedures.map((procedure) => (
        <div
          key={procedure.normalized_value}
          className="flex items-start justify-between gap-4 py-2.5"
          data-testid="procedure-row"
          data-procedure={procedure.normalized_value}
          data-selected={procedure.is_selected}
        >
          <dt className="shrink-0 pt-0.5 text-sm text-slate-500">
            Procedure
            {!procedure.is_selected && <span className="ml-1 text-xs text-slate-400">(also named)</span>}
          </dt>
          <dd className="min-w-0 text-right">
            <div className="text-sm font-medium text-slate-900">{procedure.label}</div>
            {procedure.value_variants.length > 1 && (
              <p className="text-xs text-slate-400">
                written as {procedure.value_variants.map((variant) => variant.value).join(' · ')}
              </p>
            )}
            <div className="mt-0.5 flex justify-end">
              <SourceChip
                label="Procedure"
                value={
                  {
                    key: `procedures.${procedure.normalized_value}`,
                    label: 'Procedure',
                    kind: 'procedure',
                    section: 'procedures',
                    present: true,
                    value: procedure.value,
                    normalized_value: procedure.normalized_value,
                    confidence: null,
                    weight: procedure.weight,
                    source_count: procedure.source_count,
                    value_variants: procedure.value_variants,
                    sources: procedure.sources,
                    evidence_available: procedure.sources.some((source) => source.evidence_available),
                    competing_values: [],
                    has_competing_values: false,
                    note: null,
                  } satisfies CanonicalValue
                }
                onOpen={onOpen}
              />
            </div>
          </dd>
        </div>
      ))}
    </>
  )
}

function ClaimRecord({ state }: { state: ClaimState }) {
  const form = state.claim.form
  const rows: Array<[string, string]> = [
    ['Patient', form.patient_name],
    ['UHID / IPD', form.uhid],
    ['Hospital', state.claim.hospital],
    ['Insurer', state.claim.insurer],
    ['TPA', state.claim.tpa ?? '—'],
    ['Admission', form.admission_date ? formatDate(form.admission_date) : '—'],
    ['Discharge', form.discharge_date ? formatDate(form.discharge_date) : '—'],
    ['Created by', state.claim.created_by],
  ]
  return (
    <Card data-testid="claim-record">
      <CardHeader
        title="Claim record"
        description="What was entered when the claim was created"
        actions={<ClaimStatusBadge status={state.claim.status} />}
      />
      <dl className="divide-y divide-slate-100 px-5 py-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-start justify-between gap-4 py-2.5">
            <dt className="shrink-0 text-slate-500">{label}</dt>
            <dd className="text-right font-medium text-slate-900" data-field={label}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

function OverviewSkeleton() {
  return (
    <div aria-busy className="space-y-6">
      <Skeleton className="h-8 w-72" />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {[0, 1, 2, 3].map((key) => (
          <Skeleton key={key} className="h-16 rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-6">
          <Skeleton className="h-64 rounded-xl" />
          <Skeleton className="h-80 rounded-xl" />
        </div>
        <Skeleton className="h-72 rounded-xl" />
      </div>
    </div>
  )
}
