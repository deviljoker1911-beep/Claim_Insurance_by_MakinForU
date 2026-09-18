import { ArrowRight, CircleCheck, CircleHelp, FilePlus2, ListChecks, TriangleAlert, Waypoints } from 'lucide-react'
import { useState, type ComponentType } from 'react'

import type { Change, ChangeKind, ReanalysisRun } from '../../lib/types'
import { formatDateTime } from '../../lib/format'
import { Badge } from '../ui/Badge'
import type { Tone } from '../ui/styles'

const KIND: Record<ChangeKind, { icon: ComponentType<{ className?: string }>; tone: Tone; label: string }> = {
  document: { icon: FilePlus2, tone: 'brand', label: 'Document' },
  finding: { icon: TriangleAlert, tone: 'warning', label: 'Finding' },
  checklist: { icon: ListChecks, tone: 'info', label: 'Checklist' },
  canonical: { icon: Waypoints, tone: 'neutral', label: 'Value' },
  question: { icon: CircleHelp, tone: 'info', label: 'Question' },
  procedure: { icon: Waypoints, tone: 'brand', label: 'Procedure' },
}

/** What the last pass of analysis changed, taken from the states it compared. */
export function ChangeSummary({ run, history }: { run: ReanalysisRun; history: ReanalysisRun[] }) {
  const [showAll, setShowAll] = useState(false)
  const runs = showAll ? history : [run]

  if (run.changes.length === 0 && history.length <= 1) {
    return (
      <p className="px-5 py-6 text-sm text-slate-500" data-testid="changes-empty">
        Nothing has changed since this claim was first analysed.
      </p>
    )
  }

  return (
    <div data-testid="change-summary">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
        <Counts run={run} />
        {history.length > 1 && (
          <button
            type="button"
            data-testid="changes-toggle"
            onClick={() => setShowAll(!showAll)}
            className="ml-auto text-xs font-medium text-brand-700 hover:underline"
          >
            {showAll ? 'Show only the last pass' : `Show all ${history.length} passes`}
          </button>
        )}
      </div>
      <ul className="divide-y divide-slate-100">
        {runs.map((item) => (
          <li key={item.id} className="px-5 py-3" data-testid="change-run" data-sequence={item.sequence}>
            <p className="text-xs text-slate-400">
              Pass {item.sequence} · {formatDateTime(item.completed_at ?? item.started_at)}
              {item.duration_ms !== null && ` · ${item.duration_ms} ms`}
            </p>
            {item.changes.length === 0 ? (
              <p className="mt-1 text-sm text-slate-500">Nothing changed in this pass.</p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {item.changes.map((change) => (
                  <ChangeRow key={`${change.kind}:${change.key}`} change={change} />
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Counts({ run }: { run: ReanalysisRun }) {
  const counts: Array<[string, number, Tone]> = [
    ['document added', run.summary.documents_added, 'brand'],
    ['question resolved', run.summary.questions_resolved, 'success'],
    ['finding closed', run.summary.findings_auto_closed, 'success'],
    ['finding opened', run.summary.findings_opened, 'warning'],
    ['checklist change', run.summary.checklist_changed, 'info'],
    ['value changed', run.summary.canonical_changed, 'neutral'],
  ]
  const shown = counts.filter(([, total]) => total > 0)
  if (shown.length === 0) return <Badge tone="neutral">No change in the last pass</Badge>
  return (
    <>
      {shown.map(([label, total, tone]) => (
        <Badge key={label} tone={tone}>
          {total} {label}
          {total === 1 ? '' : 's'}
        </Badge>
      ))}
    </>
  )
}

function ChangeRow({ change }: { change: Change }) {
  const kind = KIND[change.kind]
  const Icon = kind.icon
  return (
    <li className="flex items-start gap-2 text-sm" data-testid="change" data-kind={change.kind} data-key={change.key}>
      <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-slate-100 text-slate-500">
        <Icon className="size-3" />
      </span>
      <span className="min-w-0">
        <span className="text-slate-700">{change.headline}</span>
        {change.before !== null && change.after !== null && (
          <span className="ml-1.5 inline-flex items-center gap-1 text-xs text-slate-400">
            <span>{String(change.before).replaceAll('_', ' ')}</span>
            <ArrowRight className="size-3" />
            <span>{String(change.after).replaceAll('_', ' ')}</span>
          </span>
        )}
        {change.after === 'found' && <CircleCheck className="ml-1 inline size-3.5 text-emerald-600" />}
      </span>
    </li>
  )
}
