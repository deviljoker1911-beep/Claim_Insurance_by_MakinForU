import { Plus } from 'lucide-react'

import { ClaimsTable } from '../components/claims/ClaimsTable'
import { ButtonLink } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'

export function ClaimsPage() {
  return (
    <>
      <PageHeader
        title="My Claims"
        description="Every claim you are preparing, with its documentation readiness and open issues."
        actions={
          <ButtonLink to="/claims/new">
            <Plus className="size-4" />
            New Claim
          </ButtonLink>
        }
      />
      <Card>
        <ClaimsTable />
      </Card>
    </>
  )
}
