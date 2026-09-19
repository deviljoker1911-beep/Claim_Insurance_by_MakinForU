import '@fontsource-variable/inter'
import './index.css'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router/dom'

import { router } from './app/router'

const queryClient = new QueryClient({
  defaultOptions: {
    // Coming back to a tab that was left open asks the claim what it says now. A claim changes
    // through the other tab, or through anyone else at the same claim, and a tab left showing
    // what it said ten minutes ago is worse than a moment's fetch. Nothing under five seconds
    // old is asked for again.
    queries: { staleTime: 5_000, refetchOnWindowFocus: true },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
