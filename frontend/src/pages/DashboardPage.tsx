import {
  ArrowRight,
  BadgeCheck,
  Copy,
  FileX2,
  Files,
  Plus,
  Receipt,
  Scale,
  Stethoscope,
  UserRoundCheck,
  type LucideIcon,
} from 'lucide-react'

import { ClaimsTable } from '../components/claims/ClaimsTable'
import { ButtonLink } from '../components/ui/Button'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { iconTones, type Tone } from '../components/ui/styles'
import { cx } from '../lib/cx'

const KPIS: Array<{ label: string; hint: string; icon: LucideIcon; tone: Tone }> = [
  { label: 'Total Claims', hint: 'All claims in this workspace', icon: Files, tone: 'brand' },
  { label: 'Ready for Review', hint: 'Documentation complete', icon: BadgeCheck, tone: 'success' },
  { label: 'Missing Documents', hint: 'Required documents not found', icon: FileX2, tone: 'danger' },
  { label: 'Data Mismatches', hint: 'Cross-document inconsistencies', icon: Scale, tone: 'warning' },
  { label: 'Billing Issues', hint: 'Arithmetic or duplicate bills', icon: Receipt, tone: 'warning' },
  { label: 'Duplicate Documents', hint: 'Repeated files or pages', icon: Copy, tone: 'info' },
  { label: 'Clinical Review', hint: 'Diagnosis and procedure checks', icon: Stethoscope, tone: 'info' },
  { label: 'Human Verification', hint: 'Items awaiting a reviewer', icon: UserRoundCheck, tone: 'neutral' },
]

export function DashboardPage() {
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

      <section aria-label="Key metrics" className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {KPIS.map(({ label, hint, icon: Icon, tone }) => (
          <Card key={label} className="p-5">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium text-slate-600">{label}</p>
              <span className={cx('grid size-9 place-items-center rounded-lg', iconTones[tone])}>
                <Icon className="size-4.5" />
              </span>
            </div>
            <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-300 tabular-nums">—</p>
            <p className="mt-1 text-xs text-slate-500">{hint}</p>
          </Card>
        ))}
      </section>
      <p className="mt-3 text-xs text-slate-400">Metrics populate once claims have been analysed.</p>

      <Card className="mt-8">
        <CardHeader
          title="Recent claims"
          description="Claims ordered by latest activity."
          actions={
            <ButtonLink to="/claims" variant="ghost" size="sm">
              View all
              <ArrowRight className="size-4" />
            </ButtonLink>
          }
        />
        <ClaimsTable />
      </Card>
    </>
  )
}
