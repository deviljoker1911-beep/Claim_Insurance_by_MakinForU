import { BadgeCheck, CircleAlert, Files, Gauge, Plus, TriangleAlert, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router'

import { Badge } from '../components/ui/Badge'
import { ButtonLink } from '../components/ui/Button'
import { Card, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { PageHeader } from '../components/ui/PageHeader'
import { Skeleton } from '../components/ui/Skeleton'
import { iconTones, type Tone } from '../components/ui/styles'
import { cx } from '../lib/cx'
import { formatDateTime, plural } from '../lib/format'
import { useDashboard } from '../lib/hooks'
import type { DashboardClaim, DashboardResponse, ReadinessStatus } from '../lib/types'

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

export function DashboardPage() {
  const dashboard = useDashboard()

  return (
    <>
      <PageHeader
        title="Claims overview"
        description="Documentation readiness across claims being prepared for insurer submission."
        actions={
          <ButtonLink to="/claims/new">
            <Plus className="size-4" />
            New Claim
          </ButtonLink>
        }
      />

      {dashboard.isPending ? (
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
          {[0, 1, 2, 3, 4].map((key) => (
            <Skeleton key={key} className="h-28 rounded-xl" />
          ))}
        </div>
      ) : dashboard.data ? (
        <Kpis data={dashboard.data} />
      ) : (
        <Card className="p-5">
          <p className="text-sm text-slate-500">{dashboard.error?.message ?? 'The dashboard is unavailable.'}</p>
        </Card>
      )}

      <div className="mt-6 grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card data-testid="dashboard-claims">
          <CardHeader
            title="Claims"
            description={
              dashboard.data
                ? `${plural(dashboard.data.totals.claims, 'claim')} in this workspace`
                : 'Every claim in this workspace'
            }
          />
          {dashboard.isPending ? (
            <div className="space-y-2 p-5">
              <Skeleton className="h-10 rounded-lg" />
              <Skeleton className="h-10 rounded-lg" />
            </div>
          ) : dashboard.data && dashboard.data.claims.length > 0 ? (
            <ClaimsTable claims={dashboard.data.claims} />
          ) : (
            <EmptyState
              icon={Files}
              title="No claims yet"
              description="Create a claim and upload its documents to see readiness across the workspace."
              action={
                <ButtonLink to="/claims/new">
                  <Plus className="size-4" />
                  New Claim
                </ButtonLink>
              }
            />
          )}
        </Card>

        <Card data-testid="dashboard-activity">
          <CardHeader title="Recent activity" description="What happened across the workspace" />
          {dashboard.data && dashboard.data.recent_activity.length > 0 ? (
            <ul className="divide-y divide-slate-100">
              {dashboard.data.recent_activity.map((event) => (
                <li key={event.id} className="px-5 py-2.5">
                  <p className="text-sm text-slate-700">{event.message}</p>
                  <p className="text-xs text-slate-400">
                    {event.actor} · {formatDateTime(event.created_at)}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-5 py-6 text-sm text-slate-500">Nothing has happened in this workspace yet.</p>
          )}
        </Card>
      </div>
    </>
  )
}

function Kpis({ data }: { data: DashboardResponse }) {
  const cards: Array<{ label: string; value: string; hint: string; icon: LucideIcon; tone: Tone }> = [
    {
      label: 'Total claims',
      value: `${data.totals.claims}`,
      hint: `${plural(data.totals.documents, 'document')} uploaded`,
      icon: Files,
      tone: 'brand',
    },
    {
      label: 'Incomplete',
      value: `${data.totals.incomplete}`,
      hint: 'A required document is still missing',
      icon: CircleAlert,
      tone: 'danger',
    },
    {
      label: 'Needs attention',
      value: `${data.totals.needs_attention}`,
      hint: `${plural(data.totals.open_findings, 'finding')} open`,
      icon: TriangleAlert,
      tone: 'warning',
    },
    {
      label: 'Ready for human review',
      value: `${data.totals.ready_for_human_review}`,
      hint: `${data.totals.approved} approved by a person`,
      icon: BadgeCheck,
      tone: 'success',
    },
    {
      label: 'Average readiness',
      value: `${data.totals.average_readiness}%`,
      hint: 'Across the claims in this workspace',
      icon: Gauge,
      tone: 'info',
    },
  ]
  return (
    <section aria-label="Key metrics" className="grid grid-cols-2 gap-4 xl:grid-cols-5" data-testid="dashboard-kpis">
      {cards.map(({ label, value, hint, icon: Icon, tone }) => (
        <Card key={label} className="p-5" data-testid="dashboard-kpi" data-kpi={label}>
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium text-slate-600">{label}</p>
            <span className={cx('grid size-9 place-items-center rounded-lg', iconTones[tone])}>
              <Icon className="size-4.5" />
            </span>
          </div>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 tabular-nums">{value}</p>
          <p className="mt-1 text-xs text-slate-500">{hint}</p>
        </Card>
      ))}
    </section>
  )
}

function ClaimsTable({ claims }: { claims: DashboardClaim[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-left text-xs tracking-wide text-slate-500 uppercase">
            <th className="px-5 py-2.5 font-medium">Claim</th>
            <th className="px-3 py-2.5 font-medium">Patient</th>
            <th className="px-3 py-2.5 font-medium">Hospital</th>
            <th className="px-3 py-2.5 font-medium">Procedure</th>
            <th className="px-3 py-2.5 text-right font-medium">Docs</th>
            <th className="px-3 py-2.5 text-right font-medium">Issues</th>
            <th className="w-44 px-3 py-2.5 font-medium">Readiness</th>
            <th className="px-3 py-2.5 font-medium">Status</th>
            <th className="px-5 py-2.5 font-medium">Updated</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {claims.map((claim) => (
            <tr key={claim.claim_id} className="hover:bg-slate-50/60" data-testid="dashboard-claim-row">
              <td className="px-5 py-3">
                <Link to={`/claims/${claim.claim_id}`} className="font-medium text-brand-700 hover:underline">
                  {claim.claim_number}
                </Link>
              </td>
              <td className="px-3 py-3 text-slate-700">{claim.patient_name}</td>
              <td className="max-w-[12rem] truncate px-3 py-3 text-slate-600" title={claim.hospital}>
                {claim.hospital}
              </td>
              <td className="max-w-[12rem] truncate px-3 py-3 text-slate-600" title={claim.procedure ?? undefined}>
                {claim.procedure ?? '—'}
              </td>
              <td className="px-3 py-3 text-right text-slate-700 tabular-nums">{claim.document_count}</td>
              <td className="px-3 py-3 text-right tabular-nums">
                {claim.open_findings > 0 ? (
                  <span className="font-medium text-amber-700">{claim.open_findings}</span>
                ) : (
                  <span className="text-slate-400">0</span>
                )}
              </td>
              <td className="px-3 py-3">
                <div className="flex items-center gap-2">
                  <span className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
                    <span
                      className={cx('block h-full rounded-full', BAR[claim.readiness_status])}
                      style={{ width: `${Math.max(claim.readiness_score, 2)}%` }}
                    />
                  </span>
                  <span
                    className="text-sm font-semibold text-slate-900 tabular-nums"
                    data-testid="dashboard-readiness"
                  >
                    {claim.readiness_score}%
                  </span>
                </div>
              </td>
              <td className="px-3 py-3">
                <span className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={STATUS_TONE[claim.readiness_status]}>{claim.readiness_status_label}</Badge>
                  {claim.review_state === 'approved' && (
                    <Badge tone="success">
                      <BadgeCheck className="size-3.5" />
                      Approved
                    </Badge>
                  )}
                  {claim.review_state === 'superseded' && (
                    <Badge tone="warning" title="The claim changed after it was approved">
                      Approval superseded
                    </Badge>
                  )}
                </span>
              </td>
              <td className="px-5 py-3 text-xs whitespace-nowrap text-slate-500">
                {formatDateTime(claim.updated_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
