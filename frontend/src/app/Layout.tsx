import { Outlet, ScrollRestoration, useLocation } from 'react-router'

import { AccessGate } from '../components/access/AccessGate'
import { Sidebar } from '../components/layout/Sidebar'
import { Topbar } from '../components/layout/Topbar'
import { Skeleton } from '../components/ui/Skeleton'
import { useAccessSession } from '../lib/hooks'

export function Layout() {
  const { pathname } = useLocation()
  const access = useAccessSession()

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
      <Sidebar />
      <div className="pl-64">
        <Topbar />
        <main className="mx-auto w-full max-w-[1440px] px-8 pt-8 pb-16">
          <div key={pathname} className="animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>
      <ScrollRestoration />
    </div>
  )
}
