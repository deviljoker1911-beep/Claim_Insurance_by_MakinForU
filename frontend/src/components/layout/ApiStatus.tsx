import { useHealth } from '../../lib/hooks'
import { cx } from '../../lib/cx'
import { badgeTones, dotTones, type Tone } from '../ui/styles'

type State = 'checking' | 'online' | 'degraded' | 'offline'

const STATES: Record<State, { tone: Tone; label: string }> = {
  checking: { tone: 'neutral', label: 'Checking API…' },
  online: { tone: 'success', label: 'API connected' },
  degraded: { tone: 'warning', label: 'Database unavailable' },
  offline: { tone: 'danger', label: 'API offline' },
}

export function ApiStatus({ variant = 'pill' }: { variant?: 'pill' | 'sidebar' }) {
  const health = useHealth()
  const state: State =
    health.status === 'pending'
      ? 'checking'
      : health.status === 'error'
        ? 'offline'
        : health.data.status === 'ok'
          ? 'online'
          : 'degraded'
  const { tone, label } = STATES[state]
  const version = health.status === 'success' ? `v${health.data.version}` : null

  const dot = (
    <span className="relative flex size-2">
      {state === 'online' && (
        <span className={cx('absolute inline-flex size-full animate-ping rounded-full opacity-50', dotTones[tone])} />
      )}
      <span className={cx('relative inline-flex size-2 rounded-full', dotTones[tone])} />
    </span>
  )

  if (variant === 'sidebar') {
    return (
      <div
        data-testid="api-status-sidebar"
        data-state={state}
        className="flex items-center justify-between rounded-lg px-1 text-xs text-slate-400"
      >
        <span className="flex items-center gap-2">
          {dot}
          {label}
        </span>
        {version && <span className="text-slate-500 tabular-nums">{version}</span>}
      </div>
    )
  }

  return (
    <span
      data-testid="api-status"
      data-state={state}
      title={health.status === 'error' ? health.error.message : undefined}
      className={cx(
        'inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset',
        badgeTones[tone],
      )}
    >
      {dot}
      {label}
    </span>
  )
}
