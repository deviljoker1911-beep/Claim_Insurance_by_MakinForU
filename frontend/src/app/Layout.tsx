import { Outlet, ScrollRestoration, useLocation } from 'react-router'

import { Sidebar } from '../components/layout/Sidebar'
import { Topbar } from '../components/layout/Topbar'

export function Layout() {
  const { pathname } = useLocation()

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
