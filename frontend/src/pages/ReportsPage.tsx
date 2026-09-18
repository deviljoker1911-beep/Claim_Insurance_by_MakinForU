import { FileText, Plus } from 'lucide-react'
import { Link } from 'react-router'

import { ReportActions } from '../components/reports/ReportActions'
import { Badge } from '../components/ui/Badge'
import { ButtonLink } from '../components/ui/Button'
import { Card, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { PageHeader } from '../components/ui/PageHeader'
import { Skeleton } from '../components/ui/Skeleton'
import type { Tone } from '../components/ui/styles'
import { formatDateTime, plural } from '../lib/format'
import { useDashboard } from '../lib/hooks'
import type { ReadinessStatus } from '../lib/types'

const STATUS_TONE: Record<ReadinessStatus, Tone> = {
  incomplete: 'danger',
  needs_attention: 'warning',
  ready_for_human_review: 'success',
}

export function ReportsPage() {
  const dashboard = useDashboard()

  return (
    <>
      <PageHeader
        title="Reports"
        description="One report per claim: what its documents say, what the rules found, what is outstanding and what a person decided."
        actions={
          <ButtonLink to="/claims/new">
            <Plus className="size-4" />
            New Claim
          </ButtonLink>
        }
      />

      <Card>
        <CardHeader
          title="Claim reports"
          description="The page, the PDF and the workbook are the same report, generated from the claim as it stands."
        />
        {dashboard.isPending ? (
          <div className="space-y-2 p-5">
            <Skeleton className="h-12 rounded-lg" />
            <Skeleton className="h-12 rounded-lg" />
          </div>
        ) : dashboard.data && dashboard.data.claims.length > 0 ? (
          <ul className="divide-y divide-slate-100" data-testid="report-list">
            {dashboard.data.claims.map((claim) => (
              <li
                key={claim.claim_id}
                className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"
                data-testid="report-row"
                data-claim={claim.claim_id}
              >
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
                    <Link to={`/claims/${claim.claim_id}`} className="text-brand-700 hover:underline">
                      {claim.claim_number}
                    </Link>
                    <span className="text-slate-500">{claim.patient_name}</span>
                    <Badge tone={STATUS_TONE[claim.readiness_status]}>
                      {claim.readiness_score}% · {claim.readiness_status_label}
                    </Badge>
                    {claim.review_state === 'approved' && <Badge tone="success">Approved</Badge>}
                    {claim.review_state === 'superseded' && <Badge tone="warning">Approval superseded</Badge>}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {claim.procedure ?? 'No procedure named'} · {plural(claim.document_count, 'document')} ·{' '}
                    {plural(claim.open_findings, 'open finding')} · updated {formatDateTime(claim.updated_at)}
                  </p>
                </div>
                <ReportActions claimId={claim.claim_id} size="sm" />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={FileText}
            title="No reports yet"
            description="A report is generated from an analysed claim. Create a claim and upload its documents to produce one."
            action={
              <ButtonLink to="/claims/new">
                <Plus className="size-4" />
                New Claim
              </ButtonLink>
            }
          />
        )}
        <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">
          AI-generated validation assistance. Final claim submission requires authorized human review.
        </p>
      </Card>
    </>
  )
}
