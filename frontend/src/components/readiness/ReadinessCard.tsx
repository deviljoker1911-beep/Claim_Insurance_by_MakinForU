import {
  BadgeCheck,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  History,
  Loader2,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { useState, type ComponentType } from 'react'

import { errorMessage } from '../../lib/api'
import { cx } from '../../lib/cx'
import { formatDateTime, plural } from '../../lib/format'
import { useApproveClaim } from '../../lib/hooks'
import type { ReadinessResponse, ReadinessStatus } from '../../lib/types'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Notice } from '../ui/Notice'
import type { Tone } from '../ui/styles'

const STATUS: Record<ReadinessStatus, { tone: Tone; bar: string; icon: ComponentType<{ className?: string }> }> = {
  incomplete: { tone: 'danger', bar: 'bg-rose-500', icon: CircleAlert },
  needs_attention: { tone: 'warning', bar: 'bg-amber-500', icon: TriangleAlert },
  ready_for_human_review: { tone: 'success', bar: 'bg-emerald-500', icon: CircleCheck },
}

/** How complete the documentation is, what each missing point is for, and the approval. */
export function ReadinessCard({ readiness, claimId }: { readiness: ReadinessResponse; claimId: string }) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const approve = useApproveClaim(claimId)
  const status = STATUS[readiness.status]
  const Icon = status.icon
  const { review, breakdown } = readiness

  return (
    <div data-testid="readiness-card" data-status={readiness.status} data-score={readiness.score}>
      <div className="flex flex-wrap items-end justify-between gap-4 px-5 pt-5">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-500">Documentation readiness</p>
          <p className="mt-1 flex items-baseline gap-3">
            <span className="text-4xl font-semibold tracking-tight text-slate-900 tabular-nums">
              {readiness.score}%
            </span>
            <Badge tone={status.tone}>
              <Icon className="size-3.5" />
              {readiness.status_label}
            </Badge>
          </p>
          <p className="mt-1 max-w-xl text-sm text-slate-500">{readiness.status_detail}</p>
        </div>

        <div className="flex flex-col items-end gap-2">
          {review.superseded ? (
            <div className="text-right" data-testid="superseded-stamp">
              <Badge tone="warning">
                <History className="size-3.5" />
                Approval superseded
              </Badge>
              <p className="mt-1 max-w-xs text-xs text-slate-500">
                {review.approved_by} approved this claim at {review.approved_readiness.score}% on{' '}
                {formatDateTime(review.approved_at)}. It has changed since, so that approval no longer stands for it.
              </p>
              <Button
                className="mt-2"
                size="sm"
                data-testid="approve-claim"
                disabled={!review.can_approve || approve.isPending}
                title={
                  review.can_approve
                    ? 'Record that you have reviewed the claim as it stands now'
                    : 'Available once the documentation is ready for review again'
                }
                onClick={() => {
                  setError(null)
                  approve.mutate(undefined, { onError: (problem) => setError(errorMessage(problem)) })
                }}
              >
                {approve.isPending ? <Loader2 className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />}
                Approve again
              </Button>
            </div>
          ) : review.approved ? (
            <div className="text-right" data-testid="approved-stamp">
              <Badge tone="success">
                <BadgeCheck className="size-3.5" />
                Approved by {review.approved_by}
              </Badge>
              <p className="mt-1 text-xs text-slate-500">{formatDateTime(review.approved_at)}</p>
            </div>
          ) : (
            <>
              <Button
                size="sm"
                data-testid="approve-claim"
                disabled={!review.can_approve || approve.isPending}
                title={
                  review.can_approve
                    ? 'Record that you have reviewed this claim'
                    : 'Available once the documentation is ready for review'
                }
                onClick={() => {
                  setError(null)
                  approve.mutate(undefined, { onError: (problem) => setError(errorMessage(problem)) })
                }}
              >
                {approve.isPending ? <Loader2 className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />}
                Approve claim
              </Button>
              <p className="text-xs text-slate-400">A person approves; nothing here does it for them.</p>
            </>
          )}
        </div>
      </div>

      <div className="px-5 pt-4">
        <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            data-testid="readiness-bar"
            className={cx('h-full rounded-full transition-[width] duration-500', status.bar)}
            style={{ width: `${Math.max(readiness.score, 2)}%` }}
            role="progressbar"
            aria-valuenow={readiness.score}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Documentation readiness"
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
          <span>
            {breakdown.base_score} start
            {breakdown.deducted > 0 && <> − {breakdown.deducted} outstanding</>}
          </span>
          {readiness.summary.required_missing > 0 && (
            <span>{plural(readiness.summary.required_missing, 'required document')} missing</span>
          )}
          {readiness.summary.documented_unavailable > 0 && (
            <span>{readiness.summary.documented_unavailable} documented unavailable</span>
          )}
          {readiness.summary.counted_findings > 0 && (
            <span>{plural(readiness.summary.counted_findings, 'finding')} counted</span>
          )}
          {breakdown.deductions.length > 0 && (
            <button
              type="button"
              data-testid="readiness-breakdown-toggle"
              onClick={() => setOpen(!open)}
              className="ml-auto inline-flex items-center gap-1 font-medium text-brand-700 hover:underline"
            >
              {open ? 'Hide the breakdown' : `Why ${readiness.score}%?`}
              <ChevronDown className={cx('size-3.5 transition-transform', open && 'rotate-180')} />
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="px-5 pt-3">
          <Notice tone="danger" onDismiss={() => setError(null)}>
            {error}
          </Notice>
        </div>
      )}

      {open && breakdown.deductions.length > 0 && (
        <ul className="mt-3 divide-y divide-slate-100 border-t border-slate-100" data-testid="readiness-breakdown">
          {breakdown.deductions.map((deduction, index) => (
            <li
              key={`${deduction.source.kind}:${deduction.source.key}:${index}`}
              className="flex items-start gap-3 px-5 py-2.5"
              data-testid="readiness-deduction"
              data-kind={deduction.source.kind}
            >
              <span className="mt-0.5 w-10 shrink-0 text-right text-sm font-semibold text-rose-600 tabular-nums">
                −{deduction.amount}
              </span>
              <span className="min-w-0">
                <span className="text-sm text-slate-700">{deduction.reason}</span>
                {deduction.source.detail && (
                  <span className="block text-xs text-slate-500">{deduction.source.detail}</span>
                )}
              </span>
            </li>
          ))}
          <li className="flex items-center gap-3 px-5 py-2.5">
            <span className="w-10 shrink-0 text-right text-sm font-semibold text-slate-900 tabular-nums">
              {breakdown.final_score}
            </span>
            <span className="text-sm text-slate-500">
              out of {breakdown.base_score}. Every point is one of the items above.
            </span>
          </li>
        </ul>
      )}

      {!review.approved && readiness.blocking_items.length > 0 && (
        <div className="mt-3 border-t border-slate-100 px-5 py-3">
          <p className="text-xs font-medium text-slate-500">Outstanding before a person can review it</p>
          <ul className="mt-1.5 space-y-1">
            {readiness.blocking_items.slice(0, 5).map((item) => (
              <li key={`${item.kind}:${item.key}`} className="flex items-start gap-2 text-sm text-slate-600">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-slate-300" />
                <span className="min-w-0">
                  {item.label}
                  {item.action && <span className="text-slate-400"> — {item.action}</span>}
                </span>
              </li>
            ))}
            {readiness.blocking_items.length > 5 && (
              <li className="text-xs text-slate-400">and {readiness.blocking_items.length - 5} more.</li>
            )}
          </ul>
        </div>
      )}

      {review.approved && review.approval_note && (
        <p className="border-t border-slate-100 px-5 py-3 text-sm text-slate-600">{review.approval_note}</p>
      )}
    </div>
  )
}
