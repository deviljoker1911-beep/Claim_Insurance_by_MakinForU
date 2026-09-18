import { FileText, Layers, ScanText, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { cx } from '../../lib/cx'
import type { CompetingValue, EvidenceSource } from '../../lib/types'
import { Badge } from '../ui/Badge'

export interface EvidenceRequest {
  /** What the canonical claim states, and where it came from. */
  title: string
  value: string | null
  sources: EvidenceSource[]
  competing?: CompetingValue[]
  note?: string | null
}

function pageImageUrl(source: EvidenceSource): string | null {
  if (!source.page) return null
  return `/api/documents/${encodeURIComponent(source.document_id)}/pages/${source.page}/image`
}

/** The region of the page a value was read from, drawn over the page image. */
function PageWithRegion({ source }: { source: EvidenceSource }) {
  const url = pageImageUrl(source)
  const box = source.bounding_box
  const frame = useRef<HTMLDivElement>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!loaded || !box || !frame.current) return
    const container = frame.current
    const target = container.scrollHeight * box[1] - container.clientHeight / 2
    container.scrollTo({ top: Math.max(0, target), behavior: 'smooth' })
  }, [loaded, box])

  if (!url) {
    return (
      <div className="grid h-64 place-items-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm text-slate-500">
        No page image is available for this source.
      </div>
    )
  }

  return (
    <div
      ref={frame}
      className="max-h-[52vh] overflow-auto rounded-lg border border-slate-200 bg-slate-100"
      data-testid="evidence-page"
    >
      <div className="relative">
        <img
          src={url}
          alt={`${source.document_name} page ${source.page}`}
          className="block w-full"
          onLoad={() => setLoaded(true)}
          data-testid="evidence-page-image"
        />
        {box && (
          <div
            data-testid="evidence-region"
            data-box={box.join(',')}
            className="pointer-events-none absolute rounded-[2px] bg-amber-300/25 ring-2 ring-amber-500 ring-offset-1"
            style={{
              left: `${box[0] * 100}%`,
              top: `${box[1] * 100}%`,
              width: `${Math.max(box[2] - box[0], 0.004) * 100}%`,
              height: `${Math.max(box[3] - box[1], 0.004) * 100}%`,
            }}
          />
        )}
      </div>
    </div>
  )
}

function SourceSummary({ source }: { source: EvidenceSource }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm">
      <div className="col-span-2">
        <dt className="text-xs text-slate-500">Document</dt>
        <dd className="flex items-center gap-2 font-medium text-slate-900">
          <FileText className="size-4 shrink-0 text-slate-400" />
          <span className="truncate" title={source.document_name}>
            {source.document_name}
          </span>
          {source.document_type_label && <Badge tone="brand">{source.document_type_label}</Badge>}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-slate-500">Page</dt>
        <dd className="font-medium text-slate-900 tabular-nums" data-testid="evidence-page-number">
          {source.page ?? '—'}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-slate-500">Source type</dt>
        <dd className="flex items-center gap-1.5 font-medium text-slate-900">
          {source.source_type === 'ocr' ? (
            <ScanText className="size-3.5 text-slate-400" />
          ) : (
            <Layers className="size-3.5 text-slate-400" />
          )}
          {source.source_type_label}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-slate-500">Extraction method</dt>
        <dd className="font-medium text-slate-900">{source.extraction_method.replaceAll('_', ' ')}</dd>
      </div>
      <div>
        <dt className="text-xs text-slate-500">Confidence</dt>
        <dd className="font-medium text-slate-900 tabular-nums">
          {source.confidence === null ? '—' : `${Math.round(source.confidence * 100)}%`}
        </dd>
      </div>
      {source.weight !== null && (
        <div>
          <dt className="text-xs text-slate-500">Document weight in selection</dt>
          <dd className="font-medium text-slate-900 tabular-nums">×{source.weight}</dd>
        </div>
      )}
      <div>
        <dt className="text-xs text-slate-500">Value on this page</dt>
        <dd className="font-medium text-slate-900">{source.value ?? '—'}</dd>
      </div>
      {source.derived_from && (
        <div className="col-span-2">
          <dt className="text-xs text-slate-500">Read from</dt>
          <dd className="font-medium text-slate-900">{source.derived_from}</dd>
        </div>
      )}
      {source.detail && (
        <div className="col-span-2">
          <dt className="text-xs text-slate-500">Note</dt>
          <dd className="font-medium text-slate-900">{source.detail}</dd>
        </div>
      )}
      {source.snippet && (
        <div className="col-span-2">
          <dt className="text-xs text-slate-500">Extracted text</dt>
          <dd
            className="mt-1 rounded-lg bg-slate-50 px-3 py-2 font-mono text-[12.5px] leading-relaxed text-slate-700 ring-1 ring-slate-200 ring-inset"
            data-testid="evidence-snippet"
          >
            {source.snippet}
          </dd>
        </div>
      )}
      {!source.eligible && source.excluded_reason && (
        <div className="col-span-2">
          <dd className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200 ring-inset">
            Excluded from value selection: {source.excluded_reason}
          </dd>
        </div>
      )}
    </dl>
  )
}

/** Connects a canonical value to the document, page and region it was read from. */
export function EvidenceViewer({ request, onClose }: { request: EvidenceRequest; onClose: () => void }) {
  const competing = request.competing ?? []
  const groups = [
    { label: request.value ?? 'Value', sources: request.sources, selected: true },
    ...competing.map((item) => ({ label: item.value, sources: item.sources, selected: false })),
  ].filter((group) => group.sources.length > 0)
  const [active, setActive] = useState(0)
  const [index, setIndex] = useState(0)
  const closeButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeButton.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const group = groups[active] ?? groups[0]
  const source = group?.sources[Math.min(index, group.sources.length - 1)]

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 backdrop-blur-[1px] sm:p-8">
      <button
        type="button"
        aria-label="Close evidence"
        className="absolute inset-0 cursor-default"
        onClick={onClose}
        tabIndex={-1}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Evidence for ${request.title}`}
        data-testid="evidence-viewer"
        className="animate-fade-in relative z-10 w-full max-w-4xl rounded-xl bg-white shadow-xl ring-1 ring-slate-200"
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-wider text-slate-500 uppercase">Evidence</p>
            <h2 className="mt-0.5 text-[15px] font-semibold text-slate-900">
              {request.title}
              {request.value && <span className="ml-2 font-normal text-slate-500">{request.value}</span>}
            </h2>
            {request.note && <p className="mt-1 text-xs text-slate-500">{request.note}</p>}
          </div>
          <button
            ref={closeButton}
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="size-4" />
          </button>
        </header>

        {groups.length > 1 && (
          <div className="flex flex-wrap gap-2 border-b border-slate-100 bg-slate-50/60 px-5 py-3">
            {groups.map((item, position) => (
              <button
                key={item.label}
                type="button"
                data-testid="evidence-group"
                onClick={() => {
                  setActive(position)
                  setIndex(0)
                }}
                className={cx(
                  'rounded-lg border px-2.5 py-1 text-xs font-medium transition',
                  position === active
                    ? 'border-brand-300 bg-white text-brand-800 shadow-sm'
                    : 'border-transparent text-slate-600 hover:bg-white hover:text-slate-900',
                )}
              >
                {item.label}
                <span className="ml-1.5 text-slate-400 tabular-nums">
                  {item.sources.length} {item.sources.length === 1 ? 'source' : 'sources'}
                </span>
              </button>
            ))}
          </div>
        )}

        <div className="grid grid-cols-1 gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div>{source ? <PageWithRegion source={source} /> : null}</div>
          <div className="space-y-4">
            {group && group.sources.length > 1 && (
              <div>
                <p className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
                  Supporting documents ({group.sources.length})
                </p>
                <ul className="mt-2 max-h-40 space-y-1 overflow-auto pr-1">
                  {group.sources.map((item, position) => (
                    <li key={`${item.document_id}-${item.field_key}-${item.page}`}>
                      <button
                        type="button"
                        data-testid="evidence-source-option"
                        onClick={() => setIndex(position)}
                        className={cx(
                          'flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition',
                          position === Math.min(index, group.sources.length - 1)
                            ? 'bg-brand-50 text-brand-900'
                            : 'text-slate-600 hover:bg-slate-50',
                        )}
                      >
                        <span className="truncate" title={item.document_name}>
                          {item.document_name}
                        </span>
                        <span className="shrink-0 text-slate-400 tabular-nums">p{item.page ?? '—'}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {source && <SourceSummary source={source} />}
          </div>
        </div>
      </div>
    </div>
  )
}
