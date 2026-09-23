import { ChevronRight, LogOut, Menu, Plus } from 'lucide-react'
import { useLocation, useMatches } from 'react-router'

import type { RouteHandle } from '../../app/routeHandle'
import { useAccessSession, useSignOut } from '../../lib/hooks'
import { ButtonLink } from '../ui/Button'
import { ApiStatus } from './ApiStatus'

export function Topbar({ navOpen, onOpenNav }: { navOpen: boolean; onOpenNav: () => void }) {
  const matches = useMatches()
  const { pathname } = useLocation()
  const access = useAccessSession()
  const signOut = useSignOut()
  // On a deployment that asks for an address, say which one is in — the operator on the audit
  // trail is a configured name, not the visitor, and confusing the two would misread the record.
  const visitor = access.data?.gate_enabled ? access.data.email : null
  const title =
    [...matches]
      .reverse()
      .map((match) => (match.handle as RouteHandle | undefined)?.title)
      .find(Boolean) ?? 'ClaimAI'

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b border-slate-200/80 bg-white/85 px-4 backdrop-blur sm:px-6 lg:px-8">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={onOpenNav}
          aria-label="Open navigation"
          aria-expanded={navOpen}
          aria-controls="primary-navigation"
          className="-ml-1.5 grid size-9 shrink-0 place-items-center rounded-lg text-slate-600 hover:bg-slate-100 lg:hidden"
        >
          <Menu className="size-5" />
        </button>
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
          {/* The product name is on the drawer; on a phone the page title is what fits. */}
          <span className="hidden text-slate-500 sm:inline">ClaimAI</span>
          <ChevronRight className="hidden size-3.5 text-slate-300 sm:block" aria-hidden />
          <span className="truncate font-medium text-slate-900">{title}</span>
        </nav>
      </div>

      <div className="flex shrink-0 items-center gap-2 sm:gap-3">
        {/* The same status is at the foot of the drawer, where there is room for it. */}
        <div className="hidden md:block">
          <ApiStatus />
        </div>
        {pathname !== '/claims/new' && (
          <ButtonLink to="/claims/new" size="sm" aria-label="New Claim">
            <Plus className="size-4" />
            <span className="hidden sm:inline">New Claim</span>
          </ButtonLink>
        )}
        <div className="hidden h-6 w-px bg-slate-200 md:block" aria-hidden />
        <div className="flex items-center gap-2.5">
          <div className="grid size-8 place-items-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800">
            DO
          </div>
          <div className="hidden min-w-0 leading-tight md:block">
            <p className="text-sm font-medium text-slate-900">Demo Operator</p>
            <p className="max-w-[14rem] truncate text-xs text-slate-500" title={visitor ?? undefined}>
              {visitor ?? 'Claims desk'}
            </p>
          </div>
          {visitor && (
            <button
              type="button"
              onClick={() => signOut.mutate()}
              disabled={signOut.isPending}
              title="Sign out"
              aria-label="Sign out"
              className="grid size-8 place-items-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            >
              <LogOut className="size-4" />
            </button>
          )}
        </div>
      </div>
    </header>
  )
}
