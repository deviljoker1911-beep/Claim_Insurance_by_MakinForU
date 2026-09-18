import { CircleCheck, CircleHelp, CircleMinus, FileUp, Loader2, TriangleAlert } from 'lucide-react'
import { useRef, useState } from 'react'

import { errorMessage } from '../../lib/api'
import { useAnswerQuestion, useUploadForQuestion } from '../../lib/hooks'
import type { Question, QuestionAnswer, QuestionStatus } from '../../lib/types'
import { ACCEPT_ATTRIBUTE, precheckFile } from '../../lib/uploads'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Notice } from '../ui/Notice'
import type { Tone } from '../ui/styles'

const STATUS: Record<QuestionStatus, { label: string; tone: Tone }> = {
  open: { label: 'Open', tone: 'warning' },
  answered: { label: 'Waiting for the document', tone: 'info' },
  resolved: { label: 'Resolved', tone: 'success' },
  documented_unavailable: { label: 'Documented unavailable', tone: 'neutral' },
  not_applicable: { label: 'Not applicable', tone: 'neutral' },
}

const ANSWER_LABEL: Record<QuestionAnswer, string> = {
  yes_have_it: 'Yes, I have it',
  not_available: 'Not available',
  not_applicable: 'Not applicable',
}

/** What the claim is asking the operator for, and the ways to answer it. */
export function QuestionsPanel({ questions, claimId }: { questions: Question[]; claimId: string }) {
  const [showClosed, setShowClosed] = useState(false)
  const open = questions.filter((question) => question.status === 'open' || question.status === 'answered')
  const closed = questions.filter((question) => !open.includes(question))
  const visible = showClosed ? [...open, ...closed] : open

  if (questions.length === 0) {
    return (
      <p className="px-5 py-6 text-sm text-slate-500" data-testid="questions-empty">
        Nothing is being asked for: every required document of this procedure's checklist is in the claim.
      </p>
    )
  }

  return (
    <div data-testid="questions-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
        <Badge tone={open.length ? 'warning' : 'success'}>
          {open.length ? `${open.length} waiting for you` : 'Nothing outstanding'}
        </Badge>
        {closed.length > 0 && <Badge tone="neutral">{closed.length} closed</Badge>}
        {closed.length > 0 && (
          <button
            type="button"
            data-testid="questions-toggle"
            onClick={() => setShowClosed(!showClosed)}
            className="ml-auto text-xs font-medium text-brand-700 hover:underline"
          >
            {showClosed ? 'Show only what is open' : `Show all ${questions.length} questions`}
          </button>
        )}
      </div>
      <ul className="divide-y divide-slate-100">
        {visible.map((question) => (
          <QuestionRow key={question.id} question={question} claimId={claimId} />
        ))}
      </ul>
    </div>
  )
}

function QuestionRow({ question, claimId }: { question: Question; claimId: string }) {
  const status = STATUS[question.status]
  const answer = useAnswerQuestion(claimId)
  const upload = useUploadForQuestion(claimId)
  const fileInput = useRef<HTMLInputElement>(null)
  const [reasonFor, setReasonFor] = useState<QuestionAnswer | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const busy = answer.isPending || upload.isPending
  const canAnswer = question.actions_available.length > 0

  function send(choice: QuestionAnswer, withReason?: string) {
    setError(null)
    answer.mutate(
      { question, answer: choice, reason: withReason },
      {
        onSuccess: (result) => {
          setReasonFor(null)
          setReason('')
          if (choice === 'yes_have_it' && result.upload) fileInput.current?.click()
        },
        onError: (problem) => setError(errorMessage(problem)),
      },
    )
  }

  function chooseFiles(files: FileList | null) {
    const list = Array.from(files ?? [])
    if (list.length === 0) return
    const rejected = list.map((file) => precheckFile(file)).find(Boolean)
    if (rejected) {
      setError(rejected)
      return
    }
    setError(null)
    upload.mutate(
      { questionId: question.id, files: list },
      { onError: (problem) => setError(errorMessage(problem)) },
    )
  }

  return (
    <li className="px-5 py-4" data-testid="question" data-question={question.requirement_key} data-status={question.status}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-600">
          {question.status === 'resolved' ? (
            <CircleCheck className="size-3.5" />
          ) : question.status === 'open' || question.status === 'answered' ? (
            <CircleHelp className="size-3.5" />
          ) : (
            <CircleMinus className="size-3.5" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-slate-900">{question.question}</p>
            <Badge tone={status.tone}>{status.label}</Badge>
            {question.severity === 'critical' && question.status !== 'resolved' && (
              <Badge tone="danger">critical</Badge>
            )}
          </div>
          <p className="mt-0.5 text-sm text-slate-600">{question.reason}</p>
          <p className="mt-1 text-xs text-slate-500">
            Expected document type:{' '}
            <span className="font-medium text-slate-600">{question.expected_document_type.replaceAll('_', ' ')}</span>
          </p>

          {question.answer_reason && (
            <p className="mt-1.5 rounded-md bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">
              <span className="font-medium">{question.answered_by ?? 'Recorded'}:</span> {question.answer_reason}
            </p>
          )}

          {question.last_upload && !question.last_upload.satisfies && question.status !== 'resolved' && (
            <div className="mt-2" data-testid="question-mismatch">
              <Notice tone="warning">
                {question.last_upload.message} {question.last_upload.document_name} was read as{' '}
                <span className="font-medium">{question.last_upload.doc_type_label ?? 'not classified'}</span>. The
                request stays open.
              </Notice>
            </div>
          )}

          {question.last_upload?.satisfies && (
            <p className="mt-1.5 flex items-center gap-1.5 text-xs text-emerald-700">
              <CircleCheck className="size-3.5" />
              {question.last_upload.message}
            </p>
          )}

          {error && (
            <div className="mt-2">
              <Notice tone="danger" onDismiss={() => setError(null)}>
                {error}
              </Notice>
            </div>
          )}

          {canAnswer && reasonFor === null && (
            <div className="mt-2.5 flex flex-wrap gap-2">
              {question.actions_available.map((action) => (
                <Button
                  key={action}
                  size="sm"
                  variant={action === 'yes_have_it' ? 'primary' : 'secondary'}
                  disabled={busy}
                  data-testid={`question-${action}`}
                  onClick={() => (action === 'yes_have_it' ? send(action) : setReasonFor(action))}
                >
                  {busy && action === 'yes_have_it' ? <Loader2 className="size-4 animate-spin" /> : null}
                  {ANSWER_LABEL[action]}
                </Button>
              ))}
              {question.status === 'answered' && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy}
                  data-testid="question-upload-again"
                  onClick={() => fileInput.current?.click()}
                >
                  <FileUp className="size-4" />
                  Upload the document
                </Button>
              )}
            </div>
          )}

          {canAnswer && reasonFor !== null && (
            <form
              className="mt-2.5 space-y-2"
              data-testid="question-reason-form"
              onSubmit={(event) => {
                event.preventDefault()
                if (!reason.trim()) {
                  setError('A reason is required so the decision is on the record.')
                  return
                }
                send(reasonFor, reason.trim())
              }}
            >
              <label className="block text-xs font-medium text-slate-600" htmlFor={`reason-${question.id}`}>
                Why is it {reasonFor === 'not_available' ? 'not available' : 'not applicable'}? (required)
              </label>
              <textarea
                id={`reason-${question.id}`}
                data-testid="question-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={2}
                maxLength={500}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 focus-visible:outline-2 focus-visible:outline-brand-500"
                placeholder="Recorded in the audit trail"
              />
              <div className="flex gap-2">
                <Button size="sm" type="submit" disabled={busy} data-testid="question-reason-submit">
                  Record {ANSWER_LABEL[reasonFor].toLowerCase()}
                </Button>
                <Button
                  size="sm"
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setReasonFor(null)
                    setReason('')
                    setError(null)
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          )}

          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            accept={ACCEPT_ATTRIBUTE}
            data-testid="question-file-input"
            onChange={(event) => {
              chooseFiles(event.target.files)
              event.target.value = ''
            }}
          />
          {upload.isPending && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
              <Loader2 className="size-3.5 animate-spin" /> Uploading and processing…
            </p>
          )}
        </div>
      </div>
    </li>
  )
}

/** A short line for a claim with nothing outstanding. */
export function QuestionsSummaryBadge({ questions }: { questions: Question[] }) {
  const open = questions.filter((question) => question.status === 'open' || question.status === 'answered').length
  if (open === 0) return <Badge tone="success">Nothing outstanding</Badge>
  return (
    <Badge tone="warning">
      <TriangleAlert className="size-3.5" />
      {open} waiting for you
    </Badge>
  )
}
