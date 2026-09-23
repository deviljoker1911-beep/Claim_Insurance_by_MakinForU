import type { HTMLAttributes, ReactNode } from 'react'

import { cx } from '../../lib/cx'

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx('rounded-xl border border-slate-200/80 bg-white shadow-card', className)}
      {...props}
    />
  )
}

interface CardHeaderProps {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}

export function CardHeader({ title, description, actions, className }: CardHeaderProps) {
  return (
    // Side by side from sm up. Below it the actions — badges, a toggle — go under the title, since
    // beside it they squeezed a one-line description into a column a word or two wide.
    <div
      className={cx(
        'flex flex-col gap-2.5 border-b border-slate-100 px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-4 sm:px-5',
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 sm:shrink-0">{actions}</div>}
    </div>
  )
}
