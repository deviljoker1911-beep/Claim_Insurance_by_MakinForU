import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CircleCheck, FlaskConical, LayoutList, LoaderCircle, Play, ScanText, SearchX } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'react-router'

import { ProcessingProgress, ProcessingTimeline } from '../components/analysis/ProcessingTimeline'
import { ClaimStatusBadge } from '../components/claims/ClaimStatusBadge'
import { ClaimSteps } from '../components/claims/ClaimSteps'
import { Badge } from '../components/ui/Badge'
import { Button, ButtonLink } from '../components/ui/Button'
import { Card, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { Notice } from '../components/ui/Notice'
import { PageHeader } from '../components/ui/PageHeader'
import { Skeleton } from '../components/ui/Skeleton'
import { DocumentDropzone } from '../components/upload/DocumentDropzone'
import { DocumentsTable, type PendingUpload } from '../components/upload/DocumentsTable'
import { ApiError, errorMessage, fileErrors, uploadFiles } from '../lib/api'
import { daysBetween, formatBytes, formatDate, formatDateTime, plural } from '../lib/format'
import { useAttachDemoPack, useClaim, useClaimProcessing, useHealth, useStartAnalysis } from '../lib/hooks'
import type { ClaimDetail, ClaimProcessing, DocumentProcessing, UploadResult } from '../lib/types'
import { precheckFile } from '../lib/uploads'

type NoticeState = { tone: 'success' | 'info' | 'danger'; text: string } | null

let uploadSequence = 0

export function ClaimIntakePage() {
  const { claimId = '' } = useParams()
  const claim = useClaim(claimId)
  const queryClient = useQueryClient()
  const attachDemoPack = useAttachDemoPack(claimId)
  const processing = useClaimProcessing(claimId)
  const startAnalysis = useStartAnalysis(claimId)
  const [pending, setPending] = useState<PendingUpload[]>([])
  const [notice, setNotice] = useState<NoticeState>(null)

  const state = processing.data
  const running = state?.state === 'running'
  const documentStates = useMemo(() => {
    const map = new Map<string, DocumentProcessing>()
    for (const document of state?.documents ?? []) map.set(document.document_id, document)
    return map
  }, [state])

  // When a run finishes, refresh the claim so the stored classification and signals are shown.
  const previousState = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (previousState.current === 'running' && state && state.state !== 'running') {
      void queryClient.invalidateQueries({ queryKey: ['claims', claimId] })
      const processed = state.counts.processed ?? 0
      const failed = state.counts.failed ?? 0
      setNotice(
        failed > 0
          ? { tone: 'info', text: `Analysis finished: ${plural(processed, 'document')} processed, ${failed} could not be read.` }
          : {
              tone: 'success',
              text: `Analysis finished: ${plural(processed, 'document')} processed. Open the claim overview to see the structured claim and its evidence.`,
            },
      )
    }
    previousState.current = state?.state
  }, [state, claimId, queryClient])

  function runAnalysis() {
    setNotice(null)
    startAnalysis.mutate(undefined, {
      onError: (error) => {
        setNotice({ tone: 'danger', text: errorMessage(error) })
        refreshIfClaimMissing(error)
      },
    })
  }

  async function handleFiles(files: File[]) {
    setNotice(null)
    const checked = files.map((file) => ({ file, key: `upload-${++uploadSequence}`, problem: precheckFile(file) }))
    const accepted = checked.filter((item) => !item.problem)
    setPending((current) => [
      ...checked.map<PendingUpload>((item) => ({
        key: item.key,
        file: item.file,
        state: item.problem ? 'failed' : 'uploading',
        progress: 0,
        error: item.problem ?? undefined,
      })),
      ...current,
    ])
    if (accepted.length === 0) return

    const batch = new Set(accepted.map((item) => item.key))
    try {
      const result = await uploadFiles<UploadResult>(
        `/claims/${encodeURIComponent(claimId)}/documents`,
        accepted.map((item) => item.file),
        (fraction) =>
          setPending((current) => current.map((p) => (batch.has(p.key) ? { ...p, progress: fraction } : p))),
      )
      await queryClient.invalidateQueries({ queryKey: ['claims'] })
      setPending((current) => current.filter((p) => !batch.has(p.key)))
      setNotice({ tone: 'success', text: `${plural(result.documents.length, 'document')} uploaded and stored.` })
    } catch (error) {
      // The server reports rejected files by their position in the request.
      const reasons = new Map(fileErrors(error).map((reason) => [accepted[reason.index]?.key, reason.error]))
      setPending((current) =>
        current.map((p) => {
          if (!batch.has(p.key)) return p
          return {
            ...p,
            state: 'failed',
            error:
              reasons.get(p.key) ??
              (reasons.size ? 'Not stored: another file in this upload was rejected' : errorMessage(error)),
          }
        }),
      )
      setNotice({ tone: 'danger', text: errorMessage(error) })
      refreshIfClaimMissing(error)
    }
  }

  function refreshIfClaimMissing(error: unknown) {
    // The claim may have been removed (e.g. by a demo reset in another tab): reload it so the
    // page shows "Claim not found" instead of a stale claim.
    if (error instanceof ApiError && error.status === 404) {
      void queryClient.invalidateQueries({ queryKey: ['claims'] })
    }
  }

  function addDemoPack() {
    setNotice(null)
    attachDemoPack.mutate('initial', {
      onSuccess: (result) =>
        setNotice(
          result.attached_count > 0
            ? { tone: 'success', text: `Demo document pack added: ${plural(result.attached_count, 'synthetic document')}.` }
            : { tone: 'info', text: 'The demo document pack is already attached to this claim.' },
        ),
      onError: (error) => {
        setNotice({ tone: 'danger', text: errorMessage(error) })
        refreshIfClaimMissing(error)
      },
    })
  }

  if (claim.status === 'pending') return <IntakeSkeleton />
  // A failed background refetch keeps showing the loaded claim, unless the claim no longer exists.
  const notFound = claim.error instanceof ApiError && claim.error.status === 404
  if (!claim.data || notFound) {
    return (
      <Card>
        <EmptyState
          icon={SearchX}
          title={notFound ? 'Claim not found' : 'The claim could not be loaded'}
          description={notFound ? 'It may have been removed by a demo reset.' : claim.error?.message}
          action={<ButtonLink to="/claims">Back to My Claims</ButtonLink>}
        />
      </Card>
    )
  }

  const data = claim.data
  const uploading = pending.some((p) => p.state === 'uploading')
  const totalBytes = data.documents.reduce((sum, d) => sum + d.size_bytes, 0)
  const totalPages = data.documents.reduce((sum, d) => sum + (d.page_count ?? 0), 0)

  return (
    <>
      <PageHeader
        title={`Claim ${data.claim_number}`}
        description="Upload the hospital documents for this claim. Originals are stored unchanged, each with a SHA-256 fingerprint."
        actions={
          <>
            <ButtonLink to={`/claims/${claimId}`} variant="secondary" size="sm">
              <LayoutList className="size-4" />
              Claim overview
            </ButtonLink>
            <ButtonLink to="/claims" variant="ghost" size="sm">
              <ArrowLeft className="size-4" />
              My Claims
            </ButtonLink>
          </>
        }
      />
      <ClaimSteps current={state && state.state !== 'idle' ? 2 : 1} />

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Upload documents"
              description="Admission, clinical, investigation and billing documents. Several files can be uploaded together."
            />
            <div className="space-y-4 p-5">
              <DocumentDropzone
                onFiles={handleFiles}
                disabled={uploading || attachDemoPack.isPending}
                actions={
                  <Button
                    variant="secondary"
                    onClick={addDemoPack}
                    disabled={attachDemoPack.isPending || uploading}
                    data-testid="add-demo-pack"
                  >
                    {attachDemoPack.isPending ? (
                      <LoaderCircle className="size-4 animate-spin" />
                    ) : (
                      <FlaskConical className="size-4 text-amber-600" />
                    )}
                    Add demo document pack
                  </Button>
                }
              />
              {notice && (
                <Notice tone={notice.tone} onDismiss={() => setNotice(null)}>
                  {notice.text}
                </Notice>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Uploaded documents"
              description={
                data.documents.length
                  ? `${plural(data.documents.length, 'document')} · ${plural(totalPages, 'page')} · ${formatBytes(totalBytes)}`
                  : 'Nothing uploaded yet'
              }
            />
            <DocumentsTable
              documents={data.documents}
              pending={pending}
              processing={documentStates}
              onDismiss={(key) => setPending((current) => current.filter((p) => p.key !== key))}
            />
          </Card>
        </div>

        <aside className="space-y-6 xl:sticky xl:top-24">
          <ClaimInformation claim={data} />
          <AnalysisPanel
            documentCount={data.documents.length}
            state={state}
            running={running}
            pendingUploads={uploading}
            starting={startAnalysis.isPending}
            onStart={runAnalysis}
          />
        </aside>
      </div>
    </>
  )
}

interface AnalysisPanelProps {
  documentCount: number
  state: ClaimProcessing | undefined
  running: boolean
  pendingUploads: boolean
  starting: boolean
  onStart: () => void
}

function AnalysisPanel({ documentCount, state, running, pendingUploads, starting, onStart }: AnalysisPanelProps) {
  const health = useHealth()
  const waiting = (state?.counts.pending ?? 0) + (state?.counts.failed ?? 0)
  const analysed = state?.counts.processed ?? 0
  const finished = state ? state.state === 'completed' || state.state === 'completed_with_failures' : false
  const canStart = documentCount > 0 && !running && !starting && !pendingUploads && waiting > 0
  const label = running
    ? 'Analysing…'
    : finished
      ? 'Analysis complete'
      : analysed > 0 && waiting > 0
        ? `Analyse ${plural(waiting, 'new document')}`
        : 'Start Analysis'
  const ocr = health.data?.ocr

  return (
    <Card className="p-5" data-testid="analysis-panel" data-analysis-state={state?.state ?? 'idle'}>
      <p className="text-[15px] font-semibold text-slate-900">Run analysis</p>
      <p className="mt-1 text-sm text-slate-500">
        Text extraction, OCR for scans, quality checks, document classification and field extraction. Every value keeps
        the page it came from.
      </p>
      <Button className="mt-4 w-full" onClick={onStart} disabled={!canStart} data-testid="start-analysis">
        {running || starting ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : finished ? (
          <CircleCheck className="size-4" />
        ) : (
          <Play className="size-4" />
        )}
        {label}
      </Button>

      {state && state.state !== 'idle' ? (
        <div className="mt-4 space-y-4">
          <ProcessingProgress state={state} />
          <ProcessingTimeline state={state} />
        </div>
      ) : (
        <p className="mt-2 text-center text-xs text-slate-400">
          {documentCount ? `${plural(documentCount, 'document')} ready for analysis` : 'Upload documents to analyse'}
        </p>
      )}

      {ocr && (
        <p className="mt-4 flex items-start gap-1.5 border-t border-slate-100 pt-3 text-xs text-slate-400">
          <ScanText className="mt-0.5 size-3.5 shrink-0" />
          <span>
            {ocr.active === 'rapidocr'
              ? 'OCR: RapidOCR, running locally with no API key'
              : ocr.active === 'demo_fixture'
                ? 'OCR: deterministic demo fixture (no OCR engine installed)'
                : 'OCR is disabled'}
          </span>
        </p>
      )}
    </Card>
  )
}

function ClaimInformation({ claim }: { claim: ClaimDetail }) {
  const stay = daysBetween(claim.admission_date, claim.discharge_date)
  const rows: Array<[string, ReactNode]> = [
    [
      'Claim number',
      <span key="claim-number" className="font-semibold tabular-nums">
        {claim.claim_number}
      </span>,
    ],
    ['Status', <ClaimStatusBadge key="status" status={claim.status} />],
    ['Patient', claim.patient_name],
    ['UHID / IPD', claim.uhid],
    ['Hospital', claim.hospital],
    ['Insurer', claim.insurer],
    ['TPA', claim.tpa ?? '—'],
    ['Admission', formatDate(claim.admission_date)],
    ['Discharge', formatDate(claim.discharge_date)],
    ['Length of stay', plural(stay, 'day')],
    ['Created', `${formatDateTime(claim.created_at)} · ${claim.created_by}`],
  ]
  return (
    <Card data-testid="claim-information">
      <CardHeader
        title="Claim information"
        actions={claim.is_demo ? <Badge tone="warning">Synthetic demo claim</Badge> : undefined}
      />
      <dl className="divide-y divide-slate-100 px-5 py-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-start justify-between gap-4 py-2.5">
            <dt className="shrink-0 text-slate-500">{label}</dt>
            <dd className="text-right font-medium text-slate-900" data-field={label}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

function IntakeSkeleton() {
  return (
    <div aria-busy className="space-y-6">
      <Skeleton className="h-8 w-64" />
      <div className="grid grid-cols-3 gap-3">
        {[0, 1, 2].map((key) => (
          <Skeleton key={key} className="h-14 rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Skeleton className="h-72 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    </div>
  )
}
