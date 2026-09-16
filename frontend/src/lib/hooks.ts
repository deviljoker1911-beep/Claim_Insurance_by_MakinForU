import { useQuery } from '@tanstack/react-query'

import { api } from './api'
import type { HealthResponse } from './types'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api<HealthResponse>('/health'),
    // A status probe should report the real state immediately (React Query pauses retries in
    // background tabs); polling and window focus bring it back once the API is reachable.
    retry: false,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  })
}
