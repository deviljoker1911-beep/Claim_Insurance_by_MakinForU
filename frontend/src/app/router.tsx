import { createBrowserRouter } from 'react-router'

import { ClaimIntakePage } from '../pages/ClaimIntakePage'
import { ClaimsPage } from '../pages/ClaimsPage'
import { DashboardPage } from '../pages/DashboardPage'
import { NewClaimPage } from '../pages/NewClaimPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { ReportsPage } from '../pages/ReportsPage'
import { SettingsPage } from '../pages/SettingsPage'
import { Layout } from './Layout'
import { RouteError } from './RouteError'
import type { RouteHandle } from './routeHandle'

const handle = (title: string): RouteHandle => ({ title })

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <DashboardPage />, handle: handle('Dashboard') },
      { path: 'claims', element: <ClaimsPage />, handle: handle('My Claims') },
      { path: 'claims/new', element: <NewClaimPage />, handle: handle('New Claim') },
      { path: 'claims/:claimId/intake', element: <ClaimIntakePage />, handle: handle('Claim documents') },
      { path: 'reports', element: <ReportsPage />, handle: handle('Reports') },
      { path: 'settings', element: <SettingsPage />, handle: handle('Settings') },
      { path: '*', element: <NotFoundPage />, handle: handle('Page not found') },
    ],
  },
])
