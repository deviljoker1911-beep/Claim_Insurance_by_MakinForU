import { SearchX } from 'lucide-react'

import { ButtonLink } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'

export function NotFoundPage() {
  return (
    <Card>
      <EmptyState
        icon={SearchX}
        title="Page not found"
        description="The page you are looking for does not exist or has moved."
        action={<ButtonLink to="/">Back to dashboard</ButtonLink>}
      />
    </Card>
  )
}
