import { ChevronRight, Plus } from 'lucide-react'
import { useLocation, useMatches } from 'react-router'

import type { RouteHandle } from '../../app/routeHandle'
import { ButtonLink } from '../ui/Button'
import { ApiStatus } from './ApiStatus'

export function Topbar() {
  const matches = useMatches()
  const { pathname } = useLocation()
  const title =
    [...matches]
      .reverse()
      .map((match) => (match.handle as RouteHandle | undefined)?.title)
      .find(Boolean) ?? 'ClaimAI'

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-slate-200/80 bg-white/85 px-8 backdrop-blur">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm">
        <span className="text-slate-500">ClaimAI</span>
        <ChevronRight className="size-3.5 text-slate-300" aria-hidden />
        <span className="font-medium text-slate-900">{title}</span>
      </nav>

      <div className="flex items-center gap-3">
        <ApiStatus />
        {pathname !== '/claims/new' && (
          <ButtonLink to="/claims/new" size="sm">
            <Plus className="size-4" />
            New Claim
          </ButtonLink>
        )}
        <div className="h-6 w-px bg-slate-200" aria-hidden />
        <div className="flex items-center gap-2.5">
          <div className="grid size-8 place-items-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800">
            DO
          </div>
          <div className="leading-tight">
            <p className="text-sm font-medium text-slate-900">Demo Operator</p>
            <p className="text-xs text-slate-500">Claims desk</p>
          </div>
        </div>
      </div>
    </header>
  )
}
