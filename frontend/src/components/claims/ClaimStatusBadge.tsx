import { Badge } from '../ui/Badge'
import type { Tone } from '../ui/styles'

const STATUSES: Record<string, { label: string; tone: Tone }> = {
  draft: { label: 'Draft', tone: 'neutral' },
  documents_uploaded: { label: 'Documents uploaded', tone: 'info' },
}

export function ClaimStatusBadge({ status }: { status: string }) {
  const { label, tone } = STATUSES[status] ?? { label: status.replaceAll('_', ' '), tone: 'neutral' }
  return (
    <Badge tone={tone} dot>
      {label}
    </Badge>
  )
}
