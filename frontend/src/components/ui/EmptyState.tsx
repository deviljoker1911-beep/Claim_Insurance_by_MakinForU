import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cx } from '../../lib/cx'

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cx('flex flex-col items-center justify-center px-6 py-14 text-center', className)}>
      <div className="relative mb-4">
        <div className="absolute inset-0 scale-150 rounded-full bg-brand-50 blur-md" aria-hidden />
        <div className="relative grid size-12 place-items-center rounded-xl border border-slate-200 bg-white text-brand-600 shadow-card">
          <Icon className="size-5.5" />
        </div>
      </div>
      <h3 className="text-[15px] font-semibold text-slate-900">{title}</h3>
      {description && <p className="mt-1 max-w-md text-sm leading-relaxed text-slate-500">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
