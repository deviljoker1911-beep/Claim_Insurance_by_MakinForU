import { CircleCheck, CircleMinus, Clock, TriangleAlert } from 'lucide-react'
import { useState, type ComponentType } from 'react'

import { cx } from '../../lib/cx'
import type { CheckStatus, ValidationCheck } from '../../lib/types'
import { Badge } from '../ui/Badge'
import type { Tone } from '../ui/styles'

const STATUS: Record<CheckStatus, { label: string; tone: Tone; icon: ComponentType<{ className?: string }> }> = {
  pass: { label: 'Passed', tone: 'success', icon: CircleCheck },
  fail: { label: 'Finding raised', tone: 'warning', icon: TriangleAlert },
  pending: { label: 'Waiting', tone: 'info', icon: Clock },
  not_applicable: { label: 'Not applicable', tone: 'neutral', icon: CircleMinus },
}

/** The engine's own record: every check it ran, and what it concluded. */
export function ChecksPanel({ checks }: { checks: ValidationCheck[] }) {
  const [open, setOpen] = useState(false)
  const counts = (["fail", "pending", "pass", "not_applicable"] as CheckStatus[]).map((status) => ({
    status,
    total: checks.filter((check) => check.status === status).length,
  }))
  const visible = open ? checks : checks.filter((check) => check.status !== 'pass' && check.status !== 'not_applicable')

  return (
    <div data-testid="checks-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
        {counts
          .filter((item) => item.total > 0)
          .map((item) => (
            <Badge key={item.status} tone={STATUS[item.status].tone}>
              {item.total} {STATUS[item.status].label.toLowerCase()}
            </Badge>
          ))}
        <button
          type="button"
          data-testid="checks-toggle"
          onClick={() => setOpen(!open)}
          className="ml-auto text-xs font-medium text-brand-700 hover:underline"
        >
          {open ? 'Show only what needs attention' : `Show all ${checks.length} checks`}
        </button>
      </div>
      <ul className="divide-y divide-slate-100">
        {visible.map((check) => {
          const status = STATUS[check.status]
          const Icon = status.icon
          return (
            <li
              key={check.check_id}
              className="flex items-start gap-3 px-5 py-3"
              data-testid="check"
              data-check={check.check_id}
              data-status={check.status}
            >
              <span
                className={cx(
                  'mt-0.5 grid size-6 shrink-0 place-items-center rounded-full',
                  check.status === 'pass' && 'bg-emerald-50 text-emerald-600',
                  check.status === 'fail' && 'bg-amber-50 text-amber-700',
                  check.status === 'pending' && 'bg-sky-50 text-sky-700',
                  check.status === 'not_applicable' && 'bg-slate-100 text-slate-400',
                )}
              >
                <Icon className="size-3.5" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-900">{check.title}</p>
                <p className="text-xs text-slate-500">{check.detail}</p>
              </div>
              <span className="ml-auto shrink-0 font-mono text-[11px] text-slate-400">
                {check.rule_ids.join(' ') || '—'}
              </span>
            </li>
          )
        })}
      </ul>
      {visible.length === 0 && (
        <p className="px-5 py-6 text-center text-sm text-slate-500">Every check passed.</p>
      )}
    </div>
  )
}
