import { CircleAlert, FolderKanban, Plus } from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import { cx } from '../../lib/cx'
import { splitDateTime } from '../../lib/format'
import { useClaims, useDashboard } from '../../lib/hooks'
import type { ReadinessStatus } from '../../lib/types'
import { Badge } from '../ui/Badge'
import { Button, ButtonLink } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import type { Tone } from '../ui/styles'
import { ClaimStatusBadge } from './ClaimStatusBadge'

const STATUS_TONE: Record<ReadinessStatus, Tone> = {
  incomplete: 'danger',
  needs_attention: 'warning',
  ready_for_human_review: 'success',
}

const BAR: Record<ReadinessStatus, string> = {
  incomplete: 'bg-rose-500',
  needs_attention: 'bg-amber-500',
  ready_for_human_review: 'bg-emerald-500',
}

const COLUMNS = [
  'Claim ID',
  'Patient',
  'Hospital',
  'Procedure',
  'Documents',
  'Issues',
  'Readiness',
  'Status',
  'Last updated',
]

export function ClaimsTable({ limit }: { limit?: number }) {
  const claims = useClaims()
  // What a claim was read as, what is open on it and how ready it is are counted per claim by
  // the workspace summary. The columns for them stood empty while the numbers were a request
  // away, so every claim in this table read as one nobody had analysed.
  const dashboard = useDashboard()
  const navigate = useNavigate()
  const rows = claims.data ? claims.data.slice(0, limit) : []
  const summary = new Map((dashboard.data?.claims ?? []).map((claim) => [claim.claim_id, claim]))

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] text-left text-sm" data-testid="claims-table">
        <thead>
          <tr className="border-b border-slate-100 bg-slate-50/60">
            {COLUMNS.map((column) => (
              <th
                key={column}
                scope="col"
                className="px-3 py-2.5 text-[11px] font-semibold tracking-wider whitespace-nowrap text-slate-500 uppercase"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {claims.status === 'pending' &&
            [0, 1, 2].map((key) => (
              <tr key={key}>
                {COLUMNS.map((column) => (
                  <td key={column} className="px-3 py-4">
                    <Skeleton className="h-4 w-full max-w-28" />
                  </td>
                ))}
              </tr>
            ))}

          {claims.status === 'error' && !claims.data && (
            <tr>
              <td colSpan={COLUMNS.length}>
                <EmptyState
                  icon={CircleAlert}
                  title="Claims could not be loaded"
                  description={claims.error.message}
                  action={<Button onClick={() => claims.refetch()}>Retry</Button>}
                />
              </td>
            </tr>
          )}

          {claims.status === 'success' && rows.length === 0 && (
            <tr>
              <td colSpan={COLUMNS.length}>
                <EmptyState
                  icon={FolderKanban}
                  title="No claims yet"
                  description="Create a claim and upload its hospital documents to start pre-submission validation."
                  action={
                    <ButtonLink to="/claims/new">
                      <Plus className="size-4" />
                      Create claim
                    </ButtonLink>
                  }
                />
              </td>
            </tr>
          )}

          {rows.map((claim) => {
            const updated = splitDateTime(claim.updated_at)
            const detail = summary.get(claim.id)
            return (
              <tr
                key={claim.id}
                data-testid="claim-row"
                onClick={() => navigate(`/claims/${claim.id}`)}
                className="cursor-pointer transition-colors hover:bg-slate-50/80"
              >
                <td className="px-3 py-3.5 whitespace-nowrap">
                  <Link
                    to={`/claims/${claim.id}`}
                    onClick={(event) => event.stopPropagation()}
                    className="block font-semibold text-brand-700 tabular-nums hover:underline"
                  >
                    {claim.claim_number}
                  </Link>
                  {claim.is_demo && (
                    <Badge tone="warning" className="mt-1">
                      Demo
                    </Badge>
                  )}
                </td>
                <td className="px-3 py-3.5 whitespace-nowrap">
                  <p className="font-medium text-slate-900">{claim.patient_name}</p>
                  <p className="text-xs text-slate-500">{claim.uhid}</p>
                </td>
                <td className="min-w-[10rem] px-3 py-3.5 text-slate-700">{claim.hospital}</td>
                <td className="max-w-[12rem] truncate px-3 py-3.5 text-slate-700" title={detail?.procedure ?? undefined}>
                  {detail?.procedure ?? <span className="text-slate-400">—</span>}
                </td>
                <td className="px-3 py-3.5 text-slate-700 tabular-nums">{claim.document_count}</td>
                <td className="px-3 py-3.5 tabular-nums">
                  {detail === undefined ? (
                    <span className="text-slate-400">—</span>
                  ) : detail.open_findings > 0 ? (
                    <span className="font-medium text-amber-700">{detail.open_findings}</span>
                  ) : (
                    <span className="text-slate-400">0</span>
                  )}
                </td>
                <td className="px-3 py-3.5">
                  {detail === undefined ? (
                    <span className="text-slate-400">—</span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                        <span
                          className={cx('block h-full rounded-full', BAR[detail.readiness_status])}
                          style={{ width: `${Math.max(detail.readiness_score, 2)}%` }}
                        />
                      </span>
                      <span className="font-semibold text-slate-900 tabular-nums">{detail.readiness_score}%</span>
                      <Badge tone={STATUS_TONE[detail.readiness_status]}>{detail.readiness_status_label}</Badge>
                    </span>
                  )}
                </td>
                <td className="px-3 py-3.5 whitespace-nowrap">
                  <ClaimStatusBadge status={claim.status} />
                </td>
                <td className="px-3 py-3.5 whitespace-nowrap tabular-nums">
                  <p className="text-slate-700">{updated.date}</p>
                  <p className="text-xs text-slate-500">{updated.time}</p>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
