import { FolderKanban, Plus } from 'lucide-react'

import { ButtonLink } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'

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

/** Claims table. Rows are wired to the claims API in a later phase; until then it shows the empty state. */
export function ClaimsTable() {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[960px] text-left text-sm">
        <thead>
          <tr className="border-b border-slate-100 bg-slate-50/60">
            {COLUMNS.map((column) => (
              <th
                key={column}
                scope="col"
                className="px-5 py-2.5 text-[11px] font-semibold tracking-wider text-slate-500 uppercase"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
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
        </tbody>
      </table>
    </div>
  )
}
