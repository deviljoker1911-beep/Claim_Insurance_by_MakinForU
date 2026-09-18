import {
  CircleCheck,
  CircleSlash,
  Copy,
  EyeOff,
  FileQuestion,
  Info,
  Layers,
  LoaderCircle,
  RotateCcw,
  ShieldAlert,
  SquareCheck,
  TriangleAlert,
} from 'lucide-react'
import { useState, type ComponentType } from 'react'

import { cx } from '../../lib/cx'
import { formatDateTime } from '../../lib/format'
import type {
  EvidenceSource,
  Finding,
  FindingAction,
  FindingEvidence,
  FindingSummary,
  Severity,
} from '../../lib/types'
import type { EvidenceRequest } from '../canonical/EvidenceViewer'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import type { Tone } from '../ui/styles'

/** Severity keeps red for the few findings that truly need it. */
const SEVERITY: Record<Severity, { label: string; tone: Tone; icon: ComponentType<{ className?: string }>; bar: string }> = {
  critical: { label: 'Critical', tone: 'danger', icon: ShieldAlert, bar: 'bg-rose-500' },
  review: { label: 'Review', tone: 'warning', icon: TriangleAlert, bar: 'bg-amber-500' },
  warning: { label: 'Warning', tone: 'info', icon: FileQuestion, bar: 'bg-sky-500' },
  info: { label: 'Note', tone: 'neutral', icon: Info, bar: 'bg-slate-300' },
}

const STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: 'Open', tone: 'neutral' },
  reopened: { label: 'Reopened', tone: 'warning' },
  acknowledged: { label: 'Acknowledged', tone: 'info' },
  resolved: { label: 'Resolved', tone: 'success' },
  auto_closed: { label: 'Closed automatically', tone: 'success' },
}

const ACTION_LABELS: Record<FindingAction, string> = {
  review: 'Mark reviewed',
  resolve: 'Resolve',
  acknowledge: 'Acknowledge',
  reopen: 'Reopen',
  exclude_duplicate: 'Exclude duplicate',
}

const ACTION_ICONS: Record<FindingAction, ComponentType<{ className?: string }>> = {
  review: SquareCheck,
  resolve: CircleCheck,
  acknowledge: CircleSlash,
  reopen: RotateCcw,
  exclude_duplicate: Copy,
}

export type FilterKey = 'all' | 'open' | 'critical' | 'review' | 'warning' | 'resolved'

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'open', label: 'Open' },
  { key: 'critical', label: 'Critical' },
  { key: 'review', label: 'Review' },
  { key: 'warning', label: 'Warning' },
  { key: 'resolved', label: 'Resolved' },
]

function matches(finding: Finding, filter: FilterKey): boolean {
  switch (filter) {
    case 'open':
      return finding.is_active
    case 'critical':
    case 'review':
    case 'warning':
      return finding.severity === filter
    case 'resolved':
      return finding.status === 'resolved' || finding.status === 'auto_closed' || finding.status === 'acknowledged'
    default:
      return true
  }
}

function count(findings: Finding[], filter: FilterKey): number {
  return findings.filter((finding) => matches(finding, filter)).length
}

/** A finding's evidence, in the shape the evidence viewer shows. */
function toSource(evidence: FindingEvidence): EvidenceSource {
  const label =
    evidence.source_type === 'ocr' ? 'OCR' : evidence.source_type === 'pdf_text' ? 'Text layer' : 'Document'
  return {
    document_id: evidence.document_id ?? '',
    document_name: evidence.document_name ?? 'Document',
    document_type: evidence.document_type,
    document_type_label: evidence.document_type_label,
    page: evidence.page,
    bounding_box: evidence.bounding_box,
    snippet: evidence.snippet,
    method: evidence.method,
    source_type: evidence.source_type ?? 'unknown',
    source_type_label: label,
    extraction_method: evidence.kind.replaceAll('_', ' '),
    confidence: evidence.confidence,
    weight: null,
    eligible: true,
    excluded_reason: null,
    value: evidence.value,
    raw_value: null,
    field_key: evidence.field_key ?? evidence.kind,
    derived_from: null,
    detail: evidence.detail,
    evidence_available: evidence.evidence_available,
  }
}

interface FindingsPanelProps {
  findings: Finding[]
  summary: FindingSummary
  onOpenEvidence: (request: EvidenceRequest) => void
  onAction: (finding: Finding, action: FindingAction) => void
  pendingAction: string | null
}

export function FindingsPanel({ findings, summary, onOpenEvidence, onAction, pendingAction }: FindingsPanelProps) {
  const [filter, setFilter] = useState<FilterKey>('all')
  const visible = findings.filter((finding) => matches(finding, filter))

  if (findings.length === 0) {
    return (
      <EmptyState
        icon={CircleCheck}
        title="No findings"
        description="Nothing was raised against these documents. Findings appear here once documents are analysed."
      />
    )
  }

  return (
    <div data-testid="findings-panel">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-100 px-5 py-3">
        {FILTERS.map((item) => {
          const total = count(findings, item.key)
          const active = filter === item.key
          return (
            <button
              key={item.key}
              type="button"
              data-testid="findings-filter"
              data-filter={item.key}
              data-active={active}
              onClick={() => setFilter(item.key)}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition',
                active
                  ? 'border-brand-200 bg-brand-50 text-brand-800'
                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-900',
              )}
            >
              {item.label}
              <span className={cx('tabular-nums', active ? 'text-brand-500' : 'text-slate-400')}>{total}</span>
            </button>
          )
        })}
        <span className="ml-auto text-xs text-slate-400">
          {summary.active} of {summary.total} need attention
        </span>
      </div>

      {visible.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-slate-500">No findings match this filter.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {visible.map((finding) => (
            <FindingRow
              key={finding.id}
              finding={finding}
              onOpenEvidence={onOpenEvidence}
              onAction={onAction}
              pendingAction={pendingAction}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function FindingRow({
  finding,
  onOpenEvidence,
  onAction,
  pendingAction,
}: {
  finding: Finding
  onOpenEvidence: (request: EvidenceRequest) => void
  onAction: (finding: Finding, action: FindingAction) => void
  pendingAction: string | null
}) {
  const severity = SEVERITY[finding.severity]
  const status = STATUS[finding.status] ?? { label: finding.status, tone: 'neutral' as Tone }
  const Icon = severity.icon
  const sources = finding.evidence.filter((item) => item.document_id)
  const busy = pendingAction === finding.id

  return (
    <li
      className={cx('flex gap-0 transition-colors', !finding.is_active && 'bg-slate-50/40')}
      data-testid="finding"
      data-code={finding.code}
      data-severity={finding.severity}
      data-status={finding.status}
      data-finding-id={finding.id}
    >
      <span className={cx('w-1 shrink-0', finding.is_active ? severity.bar : 'bg-slate-200')} aria-hidden />
      <div className="min-w-0 flex-1 px-4 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={severity.tone}>
            <Icon className="size-3.5" />
            {severity.label}
          </Badge>
          <p className={cx('text-sm font-semibold', finding.is_active ? 'text-slate-900' : 'text-slate-500')}>
            {finding.title}
          </p>
          <Badge tone={status.tone} dot={finding.is_active}>
            {status.label}
          </Badge>
          {finding.attribution === 'source' && (
            <Badge tone="neutral" title="Measured while reading the document">
              From the document
            </Badge>
          )}
          <span className="ml-auto font-mono text-[11px] text-slate-400" title={`${finding.code} · ${finding.subject}`}>
            {finding.rule_id}
          </span>
        </div>

        <p className={cx('mt-1.5 text-sm', finding.is_active ? 'text-slate-600' : 'text-slate-500')}>
          {finding.explanation}
        </p>

        <p className="mt-2 flex items-start gap-1.5 text-sm text-slate-700">
          <span className="mt-0.5 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">Do</span>
          <span>{finding.action}</span>
        </p>

        {(finding.status_note || finding.reviewed_by) && (
          <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 ring-1 ring-slate-200 ring-inset">
            {finding.status_note}
            {finding.reviewed_by && (
              <span className="text-slate-400">
                {finding.status_note ? ' · ' : ''}
                reviewed by {finding.reviewed_by}
                {finding.reviewed_at ? ` on ${formatDateTime(finding.reviewed_at)}` : ''}
              </span>
            )}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {sources.length > 0 && (
            <button
              type="button"
              data-testid="finding-evidence"
              onClick={() =>
                onOpenEvidence({
                  title: finding.title,
                  value: null,
                  sources: sources.map(toSource),
                  note: finding.action,
                })
              }
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:bg-brand-50 hover:text-brand-700"
            >
              <Layers className="size-3.5" />
              {sources.length === 1
                ? `${sources[0].document_name} · p${sources[0].page ?? '—'}`
                : `${sources.length} sources`}
            </button>
          )}
          {finding.evidence.length === 0 && (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
              <EyeOff className="size-3.5" />
              No page evidence: this finding is about a document that is not in the claim
            </span>
          )}
          <span className="grow" />
          {finding.actions_available.map((action) => {
            const ActionIcon = ACTION_ICONS[action]
            return (
              <Button
                key={action}
                size="sm"
                variant={action === 'resolve' ? 'primary' : 'secondary'}
                disabled={busy}
                onClick={() => onAction(finding, action)}
                data-testid="finding-action"
                data-action={action}
              >
                {busy ? <LoaderCircle className="size-3.5 animate-spin" /> : <ActionIcon className="size-3.5" />}
                {ACTION_LABELS[action]}
              </Button>
            )
          })}
        </div>
      </div>
    </li>
  )
}
