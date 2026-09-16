import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from './api'
import type {
  Claim,
  ClaimDetail,
  ClaimInput,
  DemoAttachResult,
  DemoClaimProfile,
  DemoResetResult,
  DemoSet,
  HealthResponse,
} from './types'

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

export function useClaims() {
  return useQuery({ queryKey: ['claims'], queryFn: () => api<Claim[]>('/claims') })
}

export function useClaim(claimId: string) {
  return useQuery({
    queryKey: ['claims', claimId],
    queryFn: () => api<ClaimDetail>(`/claims/${encodeURIComponent(claimId)}`),
    enabled: Boolean(claimId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}

export function useCreateClaim() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: ClaimInput) => api<Claim>('/claims', { method: 'POST', body: JSON.stringify(input) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['claims'] }),
  })
}

export function useAttachDemoPack(claimId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (set: DemoSet) =>
      api<DemoAttachResult>(`/claims/${encodeURIComponent(claimId)}/demo-documents?set=${set}`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['claims'] }),
  })
}

export function useResetDemo() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api<DemoResetResult>('/demo/reset', { method: 'POST', body: JSON.stringify({ confirm: true }) }),
    // Drop cached claims entirely (not just refetch the visible ones) so Back never shows a deleted claim.
    onSuccess: () => Promise.all([queryClient.resetQueries({ queryKey: ['claims'] }), queryClient.invalidateQueries()]),
  })
}

export function fetchDemoClaimProfile() {
  return api<DemoClaimProfile>('/demo/profile')
}
