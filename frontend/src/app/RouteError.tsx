import { TriangleAlert } from 'lucide-react'
import { isRouteErrorResponse, useRouteError } from 'react-router'

import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'

export function RouteError() {
  const error = useRouteError()
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : 'An unexpected error occurred.'

  return (
    <div className="grid min-h-screen place-items-center bg-slate-50 p-8">
      <Card className="w-full max-w-lg">
        <EmptyState
          icon={TriangleAlert}
          title="Something went wrong"
          description={message}
          action={<Button onClick={() => window.location.assign('/')}>Back to dashboard</Button>}
        />
      </Card>
    </div>
  )
}
