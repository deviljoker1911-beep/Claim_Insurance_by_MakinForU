import { useEffect, useState } from 'react'
import { Outlet, ScrollRestoration, useLocation } from 'react-router'

import { AccessGate } from '../components/access/AccessGate'
import { Sidebar } from '../components/layout/Sidebar'
import { Topbar } from '../components/layout/Topbar'
import { Skeleton } from '../components/ui/Skeleton'
import { useAccessSession } from '../lib/hooks'

export function Layout() {
  const { pathname } = useLocation()
  const access = useAccessSession()
  const [navOpen, setNavOpen] = useState(false)

  // An open drawer is dismissed with Escape, and the page behind it does not scroll under it.
  useEffect(() => {
    if (!navOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setNavOpen(false)
    }
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [navOpen])

  // Until the deployment has said whether it asks for an address, show neither the app nor the
  // gate: flashing one and replacing it with the other reads as a bug on every page load.
  if (access.isPending) {
    return (
      <div className="grid min-h-dvh place-items-center bg-slate-50">
        <Skeleton className="h-8 w-40" />
      </div>
    )
  }

  // A deployment with no gate, or an unreachable one, falls through to the app — which is then
  // refused by the API itself if a gate really is in force. The gate is enforced there, not here.
  if (access.data?.gate_enabled && !access.data.verified) {
    return <AccessGate delivery={access.data.delivery} />
  }

  return (
    <div className="min-h-screen">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="lg:pl-64">
        <Topbar navOpen={navOpen} onOpenNav={() => setNavOpen(true)} />
        <main className="mx-auto w-full max-w-[1440px] px-4 pt-5 pb-16 sm:px-6 sm:pt-6 lg:px-8 lg:pt-8">
          <div key={pathname} className="animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>
      <ScrollRestoration />
    </div>
  )
}
