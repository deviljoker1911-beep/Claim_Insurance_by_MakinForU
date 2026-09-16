import {
  FileChartColumn,
  FilePlus2,
  FlaskConical,
  FolderKanban,
  LayoutDashboard,
  Settings,
  type LucideIcon,
} from 'lucide-react'
import { Link, useLocation } from 'react-router'

import { cx } from '../../lib/cx'
import { ApiStatus } from './ApiStatus'
import { Logo } from './Logo'

const NAV_ITEMS: Array<{ to: string; label: string; icon: LucideIcon; matches: (path: string) => boolean }> = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, matches: (path) => path === '/' },
  {
    to: '/claims',
    label: 'My Claims',
    icon: FolderKanban,
    // Claim pages live under /claims/<id>/...; /claims/new belongs to "New Claim".
    matches: (path) => path === '/claims' || (path.startsWith('/claims/') && !path.startsWith('/claims/new')),
  },
  { to: '/claims/new', label: 'New Claim', icon: FilePlus2, matches: (path) => path.startsWith('/claims/new') },
  { to: '/reports', label: 'Reports', icon: FileChartColumn, matches: (path) => path.startsWith('/reports') },
  { to: '/settings', label: 'Settings', icon: Settings, matches: (path) => path.startsWith('/settings') },
]

export function Sidebar() {
  const { pathname } = useLocation()

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-64 flex-col bg-navy-900 text-slate-300">
      <div className="flex h-16 items-center gap-3 border-b border-white/[0.06] px-5">
        <Logo size={34} />
        <div className="leading-tight">
          <p className="text-[15px] font-semibold tracking-tight text-white">ClaimAI</p>
          <p className="text-[11px] text-slate-400">Pre-submission validation</p>
        </div>
      </div>

      <nav aria-label="Primary" className="flex-1 space-y-1 px-3 py-6">
        <p className="px-3 pb-2 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Workspace</p>
        {NAV_ITEMS.map(({ to, label, icon: Icon, matches }) => {
          const active = matches(pathname)
          return (
            <Link
              key={to}
              to={to}
              aria-current={active ? 'page' : undefined}
              className={cx(
                'group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                active ? 'bg-white/[0.08] text-white' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-100',
              )}
            >
              {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-brand-400" aria-hidden />}
              <Icon
                className={cx(
                  'size-4.5 transition-colors',
                  active ? 'text-brand-300' : 'text-slate-500 group-hover:text-slate-300',
                )}
              />
              {label}
            </Link>
          )
        })}
      </nav>

      <div className="space-y-3 border-t border-white/[0.06] p-4">
        <div className="rounded-lg border border-white/[0.06] bg-white/[0.03] p-3">
          <p className="flex items-center gap-2 text-xs font-semibold text-amber-300">
            <FlaskConical className="size-3.5" />
            Demo environment
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
            Synthetic data only. No real patient records are used.
          </p>
        </div>
        <ApiStatus variant="sidebar" />
        <p className="px-1 text-[11px] text-slate-500">Prototype · by Makinforyou</p>
      </div>
    </aside>
  )
}
