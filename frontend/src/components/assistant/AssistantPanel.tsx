import { CircleHelp, FileText, ListChecks, Loader2, Send, Sparkles, TriangleAlert } from 'lucide-react'
import { useState, type ComponentType } from 'react'

import { errorMessage } from '../../lib/api'
import { useAskAssistant } from '../../lib/hooks'
import type { AssistantAnswer, AssistantCitation } from '../../lib/types'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Notice } from '../ui/Notice'

const SUGGESTIONS = [
  'What documents are missing?',
  'What issues need my attention?',
  'What changed after my last upload?',
  'Summarise this claim.',
  'Explain the billing concerns.',
  'What should I do next?',
]

const CITATION_ICON: Record<AssistantCitation['kind'], ComponentType<{ className?: string }>> = {
  document: FileText,
  finding: TriangleAlert,
  requirement: ListChecks,
  question: CircleHelp,
  claim: Sparkles,
}

/** Asks about this claim only, and answers from what the claim holds. */
export function AssistantPanel({
  claimId,
  onOpenCitation,
}: {
  claimId: string
  onOpenCitation?: (citation: AssistantCitation) => void
}) {
  const ask = useAskAssistant(claimId)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null)
  const [error, setError] = useState<string | null>(null)

  function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || ask.isPending) return
    setError(null)
    ask.mutate(trimmed, {
      onSuccess: (result) => {
        setAnswer(result)
        setQuestion('')
      },
      onError: (problem) => setError(errorMessage(problem)),
    })
  }

  return (
    <div className="flex flex-col" data-testid="assistant-panel">
      <form
        className="flex gap-2 px-5 pt-4"
        onSubmit={(event) => {
          event.preventDefault()
          send(question)
        }}
      >
        <input
          type="text"
          value={question}
          maxLength={500}
          data-testid="assistant-input"
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about this claim"
          className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 focus-visible:outline-2 focus-visible:outline-brand-500"
        />
        <Button type="submit" size="sm" disabled={ask.isPending || !question.trim()} data-testid="assistant-send">
          {ask.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
          Ask
        </Button>
      </form>

      <div className="flex flex-wrap gap-1.5 px-5 pt-3">
        {(answer?.suggested_questions ?? SUGGESTIONS).map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            data-testid="assistant-suggestion"
            disabled={ask.isPending}
            onClick={() => send(suggestion)}
            className="rounded-full bg-slate-50 px-2.5 py-1 text-xs text-slate-600 ring-1 ring-slate-200 ring-inset hover:bg-slate-100 hover:text-slate-900 disabled:opacity-50"
          >
            {suggestion}
          </button>
        ))}
      </div>

      {error && (
        <div className="px-5 pt-3">
          <Notice tone="danger" onDismiss={() => setError(null)}>
            {error}
          </Notice>
        </div>
      )}

      {ask.isPending && (
        <p className="flex items-center gap-2 px-5 py-4 text-sm text-slate-500" data-testid="assistant-loading">
          <Loader2 className="size-4 animate-spin" /> Reading the claim…
        </p>
      )}

      {answer && !ask.isPending && (
        <div className="px-5 py-4" data-testid="assistant-answer" data-intent={answer.intent}>
          <p className="text-xs text-slate-400">You asked: {answer.question}</p>
          <div className="mt-2 space-y-2 text-sm whitespace-pre-line text-slate-700">{answer.answer}</div>

          {answer.citations.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-medium text-slate-500">Sources</p>
              <ul className="mt-1.5 flex flex-wrap gap-1.5">
                {answer.citations.map((citation) => {
                  const Icon = CITATION_ICON[citation.kind]
                  const chip = (
                    <span className="inline-flex max-w-full items-center gap-1.5">
                      <Icon className="size-3.5 shrink-0 text-slate-400" />
                      <span className="truncate">{citation.label}</span>
                      {citation.page && <span className="text-slate-400">· p{citation.page}</span>}
                    </span>
                  )
                  return (
                    <li key={`${citation.kind}:${citation.id}:${citation.page ?? ''}`}>
                      {onOpenCitation && citation.kind === 'document' ? (
                        <button
                          type="button"
                          data-testid="assistant-citation"
                          data-kind={citation.kind}
                          onClick={() => onOpenCitation(citation)}
                          title={citation.detail ?? undefined}
                          className="rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-600 ring-1 ring-slate-200 ring-inset hover:bg-slate-100 hover:text-slate-900"
                        >
                          {chip}
                        </button>
                      ) : (
                        <span
                          data-testid="assistant-citation"
                          data-kind={citation.kind}
                          title={citation.detail ?? undefined}
                          className="inline-block rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-600 ring-1 ring-slate-200 ring-inset"
                        >
                          {chip}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-400">{answer.notice}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge tone="neutral">
              {answer.provider.name === 'demo' ? 'Deterministic demo provider' : answer.provider.name}
            </Badge>
            <span className="text-xs text-slate-400">{answer.provider.model}</span>
            {answer.provider.fell_back_to && <Badge tone="warning">fell back to the demo provider</Badge>}
          </div>
        </div>
      )}

      {!answer && !ask.isPending && !error && (
        <p className="px-5 py-4 text-sm text-slate-500">
          Ask about the documents, the findings, the checklist or what changed. Answers come from this claim only,
          and every source is listed.
        </p>
      )}
    </div>
  )
}
