import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError, uploadFiles } from './api'
import type {
  ApprovalResult,
  AssistantAnswer,
  ChecklistResponse,
  ChecksResponse,
  Claim,
  ClaimDetail,
  ClaimInput,
  ClaimProcessing,
  ClaimState,
  DashboardResponse,
  FindingAction,
  FindingActionResult,
  FindingsResponse,
  DemoAttachResult,
  DemoClaimProfile,
  DemoResetResult,
  DemoSet,
  HealthResponse,
  Question,
  QuestionAnswer,
  QuestionAnswerResult,
  QuestionsResponse,
  ReadinessResponse,
  ReanalysisResponse,
  UploadResult,
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

/** Live processing state of a claim. Polls only while the worker is busy. */
export function useClaimProcessing(claimId: string, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['claims', claimId, 'processing'],
    queryFn: () => api<ClaimProcessing>(`/claims/${encodeURIComponent(claimId)}/processing`),
    enabled: Boolean(claimId) && options.enabled !== false,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
    refetchInterval: (query) => (query.state.data?.state === 'running' ? 700 : false),
    // Keep following a run even when the operator switches to another tab, so the timeline is
    // up to date the moment they come back.
    refetchIntervalInBackground: true,
  })
}

/** The canonical claim: one structured claim assembled from the processed documents. */
export function useClaimState(claimId: string) {
  return useQuery({
    queryKey: ['claims', claimId, 'state'],
    queryFn: () => api<ClaimState>(`/claims/${encodeURIComponent(claimId)}/state`),
    enabled: Boolean(claimId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}

/** Findings of a claim. Validation runs again first if the documents changed. */
export function useFindings(claimId: string) {
  return useQuery({
    queryKey: ['claims', claimId, 'findings'],
    queryFn: () => api<FindingsResponse>(`/claims/${encodeURIComponent(claimId)}/findings`),
    enabled: Boolean(claimId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}

/** Every check the validation engine ran, and whether it passed, failed or is waiting. */
export function useChecklist(claimId: string) {
  return useQuery({
    queryKey: ['claims', claimId, 'checklist'],
    queryFn: () => api<ChecklistResponse>(`/claims/${encodeURIComponent(claimId)}/checklist`),
    enabled: Boolean(claimId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}

export function useReadiness(claimId: string) {
  return useQuery({
    queryKey: ['claims', claimId, 'readiness'],
    queryFn: () => api<ReadinessResponse>(`/claims/${encodeURIComponent(claimId)}/readiness`),
    enabled: Boolean(claimId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}

/** The workspace at a glance: every number counted from the claims themselves. */
export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api<DashboardResponse>('/dashboard'),
  })
}

/** Approval is a person's action; the button that calls this is the only way it happens. */
export function useApproveClaim(claimId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (note?: string) =>
      api<ApprovalResult>(`/claims/${encodeURIComponent(claimId)}/review/approve`, {
        method: 'POST',
        body: JSON.stringify({ note: note ?? null }),
      }),
    onSuccess: () =>
      Promise.all([claimViews(queryClient, claimId), queryClient.invalidateQueries({ queryKey: ['dashboard'] })]),
  })
}

export function useQuestions(claimId: string) {
  return useQuery({
    queryKey: ['claims', claimId, 'questions'],
    queryFn: () => api<QuestionsResponse>(`/claims/${encodeURIComponent(claimId)}/questions`),
    enabled: Boolean(claimId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}

export function useChanges(claimId: string) {
  return useQuery({
    queryKey: ['claims', claimId, 'changes'],
    queryFn: () => api<ReanalysisResponse>(`/claims/${encodeURIComponent(claimId)}/changes`),
    enabled: Boolean(claimId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}

/** Everything a claim derives from its documents moves together, so refresh it together. */
export function claimViews(queryClient: ReturnType<typeof useQueryClient>, claimId: string) {
  return Promise.all(
    ['questions', 'findings', 'checks', 'checklist', 'changes', 'readiness', 'state', 'processing'].map((view) =>
      queryClient.invalidateQueries({ queryKey: ['claims', claimId, view] }),
    ),
  )
}

export function useAnswerQuestion(claimId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ question, answer, reason }: { question: Question; answer: QuestionAnswer; reason?: string }) =>
      api<QuestionAnswerResult>(`/questions/${encodeURIComponent(question.id)}/answer`, {
        method: 'POST',
        body: JSON.stringify({ answer, reason: reason ?? null }),
      }),
    onSuccess: () => claimViews(queryClient, claimId),
  })
}

export function useUploadForQuestion(claimId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ questionId, files }: { questionId: string; files: File[] }) =>
      uploadFiles<UploadResult>(`/questions/${encodeURIComponent(questionId)}/documents`, files),
    onSuccess: () => claimViews(queryClient, claimId),
  })
}

export function useAskAssistant(claimId: string) {
  return useMutation({
    mutationFn: (question: string) =>
      api<AssistantAnswer>(`/claims/${encodeURIComponent(claimId)}/assistant`, {
        method: 'POST',
        body: JSON.stringify({ question }),
      }),
  })
}

export function useChecks(claimId: string) {
  return useQuery({
    queryKey: ['claims', claimId, 'checks'],
    queryFn: () => api<ChecksResponse>(`/claims/${encodeURIComponent(claimId)}/checks`),
    enabled: Boolean(claimId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}

export function useFindingAction(claimId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ findingId, action, note }: { findingId: string; action: FindingAction; note?: string }) =>
      api<FindingActionResult>(`/findings/${encodeURIComponent(findingId)}/action`, {
        method: 'POST',
        body: JSON.stringify({ action, note: note ?? null }),
      }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ['claims', claimId, 'findings'] }),
        queryClient.invalidateQueries({ queryKey: ['claims', claimId, 'checks'] }),
        queryClient.invalidateQueries({ queryKey: ['claims', claimId, 'checklist'] }),
        queryClient.invalidateQueries({ queryKey: ['claims', claimId, 'state'] }),
      ]),
  })
}

export function useStartAnalysis(claimId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api<ClaimProcessing>(`/claims/${encodeURIComponent(claimId)}/analyze`, { method: 'POST' }),
    onSuccess: (state) => {
      queryClient.setQueryData(['claims', claimId, 'processing'], state)
      void queryClient.invalidateQueries({ queryKey: ['claims', claimId, 'processing'] })
      void queryClient.invalidateQueries({ queryKey: ['claims', claimId, 'state'] })
      void queryClient.invalidateQueries({ queryKey: ['claims', claimId, 'findings'] })
      void queryClient.invalidateQueries({ queryKey: ['claims', claimId, 'checks'] })
    },
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
