import { FileText } from 'lucide-react'

import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { PageHeader } from '../components/ui/PageHeader'

export function ReportsPage() {
  return (
    <>
      <PageHeader
        title="Reports"
        description="AI claim pre-submission validation reports, with evidence references and audit trail."
      />
      <Card>
        <EmptyState
          icon={FileText}
          title="No reports yet"
          description="Reports are generated from an analysed claim and can be exported as PDF or Excel. Final claim submission always requires authorised human review."
        />
      </Card>
    </>
  )
}
