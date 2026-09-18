import { CircleAlert, FolderKanban, Plus } from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import { splitDateTime } from '../../lib/format'
import { useClaims } from '../../lib/hooks'
import { Badge } from '../ui/Badge'
import { Button, ButtonLink } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import { ClaimStatusBadge } from './ClaimStatusBadge'

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
  const navigate = useNavigate()
  const rows = claims.data ? claims.data.slice(0, limit) : []

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
                <td className="px-3 py-3.5 whitespace-nowrap text-slate-400">Not analysed</td>
                <td className="px-3 py-3.5 text-slate-700 tabular-nums">{claim.document_count}</td>
                <td className="px-3 py-3.5 text-slate-400">—</td>
                <td className="px-3 py-3.5 text-slate-400">—</td>
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
