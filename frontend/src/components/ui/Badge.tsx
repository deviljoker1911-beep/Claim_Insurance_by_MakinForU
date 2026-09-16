import type { ReactNode } from 'react'

import { cx } from '../../lib/cx'
import { badgeTones, dotTones, type Tone } from './styles'

interface BadgeProps {
  tone?: Tone
  dot?: boolean
  className?: string
  children: ReactNode
}

export function Badge({ tone = 'neutral', dot = false, className, children }: BadgeProps) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset',
        badgeTones[tone],
        className,
      )}
    >
      {dot && <span className={cx('size-1.5 rounded-full', dotTones[tone])} aria-hidden />}
      {children}
    </span>
  )
}
