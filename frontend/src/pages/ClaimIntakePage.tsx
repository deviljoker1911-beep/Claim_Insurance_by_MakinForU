import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FlaskConical, LoaderCircle, Lock, Play, SearchX } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useParams } from 'react-router'

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
import { useAttachDemoPack, useClaim } from '../lib/hooks'
import type { ClaimDetail, UploadResult } from '../lib/types'
import { precheckFile } from '../lib/uploads'

type NoticeState = { tone: 'success' | 'info' | 'danger'; text: string } | null

let uploadSequence = 0

export function ClaimIntakePage() {
  const { claimId = '' } = useParams()
  const claim = useClaim(claimId)
  const queryClient = useQueryClient()
  const attachDemoPack = useAttachDemoPack(claimId)
  const [pending, setPending] = useState<PendingUpload[]>([])
  const [notice, setNotice] = useState<NoticeState>(null)

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
      const reasons = fileErrors(error)
      setPending((current) =>
        current.map((p) => {
          if (!batch.has(p.key)) return p
          const reason = reasons.find((r) => r.filename === p.file.name)?.error
          return {
            ...p,
            state: 'failed',
            error: reason ?? (reasons.length ? 'Not stored: another file in this upload was rejected' : errorMessage(error)),
          }
        }),
      )
      setNotice({ tone: 'danger', text: errorMessage(error) })
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
      onError: (error) => setNotice({ tone: 'danger', text: errorMessage(error) }),
    })
  }

  if (claim.status === 'pending') return <IntakeSkeleton />
  if (claim.status === 'error') {
    const notFound = claim.error instanceof ApiError && claim.error.status === 404
    return (
      <Card>
        <EmptyState
          icon={SearchX}
          title={notFound ? 'Claim not found' : 'The claim could not be loaded'}
          description={notFound ? 'It may have been removed by a demo reset.' : claim.error.message}
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
          <ButtonLink to="/claims" variant="ghost" size="sm">
            <ArrowLeft className="size-4" />
            My Claims
          </ButtonLink>
        }
      />
      <ClaimSteps current={1} />

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
                disabled={uploading}
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
              onDismiss={(key) => setPending((current) => current.filter((p) => p.key !== key))}
            />
          </Card>
        </div>

        <aside className="space-y-6 xl:sticky xl:top-24">
          <ClaimInformation claim={data} />
          <Card className="p-5">
            <p className="text-[15px] font-semibold text-slate-900">Run analysis</p>
            <p className="mt-1 text-sm text-slate-500">
              OCR, document classification, data extraction and cross-document validation of the uploaded documents.
            </p>
            <Button
              className="mt-4 w-full"
              disabled
              title="The analysis pipeline is enabled in the next build phase"
              data-testid="start-analysis"
            >
              <Play className="size-4" />
              Start Analysis
            </Button>
            <p className="mt-2 flex items-center justify-center gap-1.5 text-xs text-slate-400">
              <Lock className="size-3" />
              {data.documents.length ? `${plural(data.documents.length, 'document')} ready · ` : ''}
              Available in the next build phase
            </p>
          </Card>
        </aside>
      </div>
    </>
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
