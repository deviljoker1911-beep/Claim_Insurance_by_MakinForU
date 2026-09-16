import { CircleAlert, CircleCheck, Info, TriangleAlert, X, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cx } from '../../lib/cx'
import type { Tone } from './styles'

const TONES: Partial<Record<Tone, { icon: LucideIcon; className: string }>> = {
  success: { icon: CircleCheck, className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  info: { icon: Info, className: 'border-sky-200 bg-sky-50 text-sky-800' },
  warning: { icon: TriangleAlert, className: 'border-amber-200 bg-amber-50 text-amber-900' },
  danger: { icon: CircleAlert, className: 'border-rose-200 bg-rose-50 text-rose-800' },
}

interface NoticeProps {
  tone: 'success' | 'info' | 'warning' | 'danger'
  children: ReactNode
  onDismiss?: () => void
  className?: string
}

export function Notice({ tone, children, onDismiss, className }: NoticeProps) {
  const { icon: Icon, className: toneClass } = TONES[tone]!
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={cx('flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm animate-fade-in', toneClass, className)}
    >
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">{children}</div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="rounded p-0.5 opacity-60 transition hover:opacity-100"
          aria-label="Dismiss"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  )
}
