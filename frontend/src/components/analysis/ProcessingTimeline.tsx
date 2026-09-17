import {
  CircleCheck,
  Clock,
  Crosshair,
  Gauge,
  Image as ImageIcon,
  LoaderCircle,
  ScanText,
  Table2,
  Tags,
  TriangleAlert,
} from 'lucide-react'
import type { ComponentType } from 'react'

import { cx } from '../../lib/cx'
import type { ClaimProcessing } from '../../lib/types'

const STAGE_ICONS: Record<string, ComponentType<{ className?: string }>> = {
  queued: Clock,
  rendering: ImageIcon,
  ocr: ScanText,
  quality: Gauge,
  classification: Tags,
  extraction: Table2,
  evidence: Crosshair,
  completed: CircleCheck,
}

/** Which stage each document of the claim is on right now. */
function stageCounts(state: ClaimProcessing): Map<string, number> {
  const counts = new Map<string, number>()
  for (const document of state.documents) {
    if (document.processing_status !== 'processing') continue
    const stage = document.processing_stage ?? 'queued'
    counts.set(stage, (counts.get(stage) ?? 0) + 1)
  }
  return counts
}

function reachedIndex(state: ClaimProcessing): number {
  // The furthest stage any document has reached, so the timeline moves forward as work lands.
  const order = state.stages.map((stage) => stage.key)
  let furthest = -1
  for (const document of state.documents) {
    const index =
      document.processing_status === 'processed' || document.processing_status === 'failed'
        ? order.length - 1
        : order.indexOf(document.processing_stage ?? '')
    if (index > furthest) furthest = index
  }
  return furthest
}

export function ProcessingTimeline({ state }: { state: ClaimProcessing }) {
  const active = stageCounts(state)
  const furthest = reachedIndex(state)
  const running = state.state === 'running'

  return (
    <ol className="space-y-1" data-testid="processing-timeline" aria-label="Processing stages">
      {state.stages.map((stage, index) => {
        const Icon = STAGE_ICONS[stage.key] ?? Clock
        const busy = active.get(stage.key) ?? 0
        const done = index < furthest || (!running && furthest >= 0)
        const current = busy > 0 || (running && index === furthest)
        return (
          <li
            key={stage.key}
            data-stage={stage.key}
            data-state={current ? 'active' : done ? 'done' : 'waiting'}
            className={cx(
              'flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors',
              current && 'bg-brand-50 text-brand-900',
              !current && done && 'text-slate-700',
              !current && !done && 'text-slate-400',
            )}
          >
            <span
              className={cx(
                'grid size-6 shrink-0 place-items-center rounded-full',
                current && 'bg-brand-600 text-white',
                !current && done && 'bg-emerald-50 text-emerald-600',
                !current && !done && 'bg-slate-100 text-slate-400',
              )}
            >
              {current ? <LoaderCircle className="size-3.5 animate-spin" /> : <Icon className="size-3.5" />}
            </span>
            <span className="flex-1 font-medium">{stage.label}</span>
            {busy > 0 && <span className="text-xs tabular-nums text-brand-700">{busy}</span>}
          </li>
        )
      })}
    </ol>
  )
}

export function ProcessingProgress({ state }: { state: ClaimProcessing }) {
  const processed = state.counts.processed ?? 0
  const failed = state.counts.failed ?? 0
  const finished = processed + failed
  const percent = Math.round(state.progress * 100)
  return (
    <div data-testid="processing-progress" data-state={state.state} data-progress={percent}>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium text-slate-700">
          {state.state === 'running' ? 'Analysing documents' : 'Documents analysed'}
        </span>
        <span className="tabular-nums text-slate-500">
          {finished} / {state.document_count}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cx(
            'h-full rounded-full transition-[width] duration-300',
            failed > 0 ? 'bg-amber-500' : 'bg-brand-500',
          )}
          style={{ width: `${Math.max(2, percent)}%` }}
        />
      </div>
      {failed > 0 && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-700">
          <TriangleAlert className="size-3.5" />
          {failed} document{failed === 1 ? '' : 's'} could not be processed
        </p>
      )}
    </div>
  )
}
