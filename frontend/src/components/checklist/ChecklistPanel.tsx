import { CircleCheck, CircleMinus, CircleX, FileText, TriangleAlert } from 'lucide-react'
import { useState, type ComponentType } from 'react'

import { cx } from '../../lib/cx'
import { formatDateTime } from '../../lib/format'
import type { ChecklistItem, ChecklistSection, ChecklistStatus, Severity } from '../../lib/types'
import { Badge } from '../ui/Badge'
import type { Tone } from '../ui/styles'

const STATUS: Record<ChecklistStatus, { label: string; tone: Tone; icon: ComponentType<{ className?: string }>; ring: string }> = {
  found: { label: 'Found', tone: 'success', icon: CircleCheck, ring: 'bg-emerald-50 text-emerald-600' },
  missing: { label: 'Missing', tone: 'danger', icon: CircleX, ring: 'bg-rose-50 text-rose-600' },
  review_required: { label: 'Review required', tone: 'warning', icon: TriangleAlert, ring: 'bg-amber-50 text-amber-700' },
  not_applicable: { label: 'Not applicable', tone: 'neutral', icon: CircleMinus, ring: 'bg-slate-100 text-slate-400' },
}

const SEVERITY: Record<Severity, Tone> = { critical: 'danger', review: 'warning', warning: 'info', info: 'neutral' }

const ORDER: ChecklistStatus[] = ['missing', 'review_required', 'found', 'not_applicable']

/** The requirements of the detected procedure, and what this claim has against each of them. */
export function ChecklistPanel({ checklist }: { checklist: ChecklistSection }) {
  const [open, setOpen] = useState(false)

  if (!checklist.available) {
    return (
      <div className="px-5 py-6" data-testid="checklist-panel" data-available="false">
        <p className="text-sm text-slate-600">{checklist.note}</p>
        {checklist.configured_procedures.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            Checklists are configured for {checklist.configured_procedures.map((item) => item.label).join(', ')}.
          </p>
        )}
      </div>
    )
  }

  const outstanding = checklist.items.filter(
    (item) => item.status === 'missing' || item.status === 'review_required',
  )
  const visible = open ? checklist.items : outstanding.length > 0 ? outstanding : checklist.items
  const counts = ORDER.map((status) => ({
    status,
    total: checklist.items.filter((item) => item.status === status).length,
  })).filter((entry) => entry.total > 0)

  return (
    <div data-testid="checklist-panel" data-available="true" data-procedure={checklist.procedure.key ?? ''}>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
        {counts.map((entry) => (
          <Badge key={entry.status} tone={STATUS[entry.status].tone} data-testid={`checklist-count-${entry.status}`}>
            {entry.total} {STATUS[entry.status].label.toLowerCase()}
          </Badge>
        ))}
        {checklist.provisional && (
          <Badge tone="info">Provisional — documents are still being processed</Badge>
        )}
        <button
          type="button"
          data-testid="checklist-toggle"
          onClick={() => setOpen(!open)}
          className="ml-auto text-xs font-medium text-brand-700 hover:underline"
        >
          {open ? 'Show only what is outstanding' : `Show all ${checklist.count} requirements`}
        </button>
      </div>

      <ul className="divide-y divide-slate-100">
        {visible.map((item) => (
          <ChecklistRow key={item.key} item={item} />
        ))}
      </ul>

      {visible.length === 0 && (
        <p className="px-5 py-6 text-center text-sm text-slate-500">
          Every requirement of this procedure is covered.
        </p>
      )}
    </div>
  )
}

function ChecklistRow({ item }: { item: ChecklistItem }) {
  const status = STATUS[item.status]
  const Icon = status.icon
  const outstanding = item.status === 'missing' || item.status === 'review_required'
  return (
    <li
      className="flex items-start gap-3 px-5 py-3.5"
      data-testid="checklist-item"
      data-requirement={item.key}
      data-status={item.status}
      data-required={item.required}
    >
      <span className={cx('mt-0.5 grid size-6 shrink-0 place-items-center rounded-full', status.ring)}>
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-slate-900">{item.label}</p>
          <Badge tone={status.tone}>{status.label}</Badge>
          {outstanding && <Badge tone={SEVERITY[item.severity]}>{item.severity}</Badge>}
          {!item.required && <Badge tone="neutral">Supporting</Badge>}
        </div>
        <p className="mt-0.5 text-sm text-slate-600">{item.detail}</p>
        {item.evidence.length > 0 && (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {item.evidence.map((source) => (
              <li key={source.document_id}>
                <span
                  title={source.detail}
                  className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-600 ring-1 ring-slate-200 ring-inset"
                >
                  <FileText className="size-3.5 shrink-0 text-slate-400" />
                  <span className="truncate">{source.document_name}</span>
                  {source.doc_type_label && <span className="text-slate-400">· {source.doc_type_label}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
        {item.findings.length > 0 && (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {item.findings.map((finding) => (
              <li key={finding.id}>
                <Badge
                  tone={finding.is_active ? SEVERITY[finding.severity] : 'neutral'}
                  title={finding.title}
                  className="font-normal"
                >
                  {finding.code.replaceAll('_', ' ').toLowerCase()}
                  <span className="text-slate-500">· {finding.status.replaceAll('_', ' ')}</span>
                </Badge>
              </li>
            ))}
          </ul>
        )}
        {outstanding && (
          <p className="mt-1.5 text-xs text-slate-500">
            <span className="font-medium text-slate-600">Do</span> {item.resolution}
          </p>
        )}
      </div>
    </li>
  )
}

/** The procedure the checklist was built for, and what named it. */
export function ProcedureSummary({ checklist }: { checklist: ChecklistSection }) {
  const { procedure } = checklist
  return (
    <div className="px-5 py-4" data-testid="procedure-summary">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <p className="text-[15px] font-semibold text-slate-900">{procedure.label}</p>
        {procedure.key && <span className="font-mono text-xs text-slate-400">{procedure.key}</span>}
      </div>
      {procedure.source === 'declared' && procedure.declared ? (
        // Said, not read. The whole product rests on not presenting one as the other.
        <p className="mt-1 text-sm text-slate-500" data-testid="procedure-declared">
          <Badge tone="info">Declared by {procedure.declared.by ?? 'the operator'}</Badge>{' '}
          No document names an operation, so this is the operator&rsquo;s answer
          {procedure.declared.at ? ` from ${formatDateTime(procedure.declared.at)}` : ''}, not something read from the
          documents.
        </p>
      ) : (
        <p className="mt-1 text-sm text-slate-500">
          {procedure.source_count > 0
            ? `Named by ${procedure.source_count} document${procedure.source_count === 1 ? '' : 's'}`
            : 'Not named by any document yet'}
          {procedure.written_as.length === 1 && `, written as “${procedure.written_as[0]}”`}
          {procedure.written_as.length > 1 &&
            `, written as ${procedure.written_as.slice(0, 3).join(' · ')}${
              procedure.written_as.length > 3 ? ` and ${procedure.written_as.length - 3} more` : ''
            }`}
          .
        </p>
      )}
      {procedure.declaration_superseded && procedure.declared && (
        <p className="mt-1.5 text-xs text-amber-800" data-testid="procedure-superseded">
          The operator earlier answered &ldquo;{procedure.declared.label}&rdquo;. A document has since named this
          operation, so the document is what the claim is checked against.
        </p>
      )}
      {procedure.also_named.length > 0 && (
        <p className="mt-1 text-xs text-slate-500">
          Also named: {procedure.also_named.map((other) => `${other.label} (${other.source_count})`).join(', ')}.
        </p>
      )}
      {checklist.note && <p className="mt-2 text-xs text-slate-500">{checklist.note}</p>}
    </div>
  )
}
