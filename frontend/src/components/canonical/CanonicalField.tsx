import { GitCompareArrows, Layers } from 'lucide-react'
import type { ReactNode } from 'react'

import { formatCanonicalValue } from '../../lib/canonical'
import { cx } from '../../lib/cx'
import type { CanonicalValue, EvidenceSource } from '../../lib/types'
import { Badge } from '../ui/Badge'

export type EvidenceOpener = (request: {
  title: string
  value: string | null
  sources: EvidenceSource[]
  competing?: CanonicalValue['competing_values']
  note?: string | null
}) => void

/** The chip that opens the evidence for a value: "SOURCE · Admission record · p1". */
export function SourceChip({
  value,
  onOpen,
  label,
}: {
  value: CanonicalValue
  onOpen: EvidenceOpener
  label?: string
}) {
  const sources = value.sources
  if (!value.present || sources.length === 0) {
    return (
      <span className="text-[11px] font-medium tracking-wide text-slate-400 uppercase" data-testid="source-missing">
        No source
      </span>
    )
  }
  const first = sources[0]
  const single = sources.length === 1
  const text = single
    ? `${first.document_type_label ?? first.document_name} · p${first.page ?? '—'}`
    : `${sources.length} sources`
  return (
    <button
      type="button"
      data-testid="source-chip"
      data-field={value.key}
      data-source-count={sources.length}
      onClick={() =>
        onOpen({
          title: label ?? value.label,
          value: value.value,
          sources,
          competing: value.competing_values,
          note: value.note,
        })
      }
      className="group inline-flex max-w-full items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium tracking-wide text-slate-500 uppercase transition hover:bg-brand-50 hover:text-brand-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500"
      title={single ? `${first.document_name}, page ${first.page}` : `${sources.length} supporting documents`}
    >
      <Layers className="size-3 shrink-0 opacity-70" />
      <span className="truncate">Source · {text}</span>
    </button>
  )
}

/** One canonical value with its provenance. */
export function CanonicalFieldRow({
  value,
  onOpen,
  children,
}: {
  value: CanonicalValue
  onOpen: EvidenceOpener
  children?: ReactNode
}) {
  return (
    <div
      className="flex items-start justify-between gap-4 py-2.5"
      data-testid="canonical-field"
      data-field={value.key}
      data-present={value.present}
      data-value={value.value ?? ''}
    >
      <dt className="shrink-0 pt-0.5 text-sm text-slate-500">{value.label}</dt>
      <dd className="min-w-0 text-right">
        <div className={cx('text-sm font-medium', value.present ? 'text-slate-900' : 'text-slate-400')}>
          {children ?? formatCanonicalValue(value)}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
          <SourceChip value={value} onOpen={onOpen} />
          {value.has_competing_values && (
            <button
              type="button"
              data-testid="competing-values"
              data-field={value.key}
              onClick={() =>
                onOpen({
                  title: value.label,
                  value: value.value,
                  sources: value.sources,
                  competing: value.competing_values,
                  note: value.note,
                })
              }
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-amber-800 transition hover:bg-amber-50"
              title="Several documents carry different values for this field"
            >
              <GitCompareArrows className="size-3" />
              Multiple source values
            </button>
          )}
          {!value.present && value.note && <span className="text-[11px] text-slate-400">{value.note}</span>}
        </div>
      </dd>
    </div>
  )
}

export function CanonicalFieldList({
  values,
  onOpen,
}: {
  values: (CanonicalValue | undefined)[]
  onOpen: EvidenceOpener
}) {
  return (
    <dl className="divide-y divide-slate-100 px-5 py-1">
      {values.filter(Boolean).map((value) => (
        <CanonicalFieldRow key={(value as CanonicalValue).key} value={value as CanonicalValue} onOpen={onOpen} />
      ))}
    </dl>
  )
}

export function ConfidenceBadge({ value }: { value: CanonicalValue }) {
  if (!value.present || value.confidence === null) return null
  return <Badge tone={value.confidence >= 0.9 ? 'success' : 'warning'}>{Math.round(value.confidence * 100)}%</Badge>
}
