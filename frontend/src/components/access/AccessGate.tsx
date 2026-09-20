import { ArrowLeft, Mail, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { ApiError } from '../../lib/api'
import { useRequestAccessCode, useVerifyAccessCode } from '../../lib/hooks'
import { Button } from '../ui/Button'

function message(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  return fallback
}

/**
 * The first screen of a public deployment: an address, then the code sent to it.
 *
 * Nobody is turned away — the point is that a demo anyone can upload documents to has a name
 * attached to every session, and that the people who came to look can be counted.
 */
export function AccessGate({ delivery }: { delivery: 'mailed' | 'logged' }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(false)
  const [note, setNote] = useState('')
  const requestCode = useRequestAccessCode()
  const verify = useVerifyAccessCode()

  const busy = requestCode.isPending || verify.isPending
  const error = requestCode.error ?? verify.error

  function send(event: FormEvent) {
    event.preventDefault()
    verify.reset()
    requestCode.mutate(email.trim(), {
      onSuccess: (result) => {
        setSent(true)
        setNote(result.message)
      },
    })
  }

  function submitCode(event: FormEvent) {
    event.preventDefault()
    verify.mutate({ email: email.trim(), code: code.trim() })
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-brand-700 text-white">
            <ShieldCheck className="size-5" />
          </span>
          <div>
            <p className="font-semibold text-slate-900">ClaimAI</p>
            <p className="text-xs text-slate-500">Claim pre-submission validation · by MakinForU</p>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          {!sent ? (
            <form onSubmit={send} data-testid="access-email-form">
              <h1 className="text-lg font-semibold text-slate-900">See the demo</h1>
              <p className="mt-1.5 text-sm text-slate-600">
                Confirm an email address and the full demo opens. We send a six-digit code — no
                password, no account.
              </p>

              <label className="mt-5 block text-sm font-medium text-slate-700" htmlFor="access-email">
                Email address
              </label>
              <input
                id="access-email"
                name="email"
                type="email"
                required
                autoFocus
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@company.com"
                className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-600 focus:ring-2 focus:ring-brand-100"
              />

              {error && (
                <p className="mt-3 flex items-start gap-1.5 text-sm text-rose-700" role="alert">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                  {message(error, 'The code could not be sent.')}
                </p>
              )}

              <Button type="submit" disabled={busy || !email.trim()} className="mt-5 w-full justify-center">
                <Mail className="size-4" />
                {requestCode.isPending ? 'Sending…' : 'Send me a code'}
              </Button>

              <p className="mt-4 text-xs leading-relaxed text-slate-500">
                Your address is kept so MakinForU knows who has seen the demo, and may be used to
                contact you about it. The demo itself holds synthetic data only — please do not
                upload real patient records.
              </p>
            </form>
          ) : (
            <form onSubmit={submitCode} data-testid="access-code-form">
              <h1 className="text-lg font-semibold text-slate-900">Enter the code</h1>
              <p className="mt-1.5 text-sm text-slate-600">
                Sent to <span className="font-medium text-slate-900">{email.trim()}</span>.
              </p>
              {delivery === 'logged' && (
                <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  No mail server is configured on this deployment, so the code was written to the
                  server log instead of being sent.
                </p>
              )}

              <label className="mt-5 block text-sm font-medium text-slate-700" htmlFor="access-code">
                Six-digit code
              </label>
              <input
                id="access-code"
                name="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                autoFocus
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="000000"
                className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-center text-lg tracking-[0.4em] tabular-nums text-slate-900 outline-none focus:border-brand-600 focus:ring-2 focus:ring-brand-100"
              />

              {error ? (
                <p className="mt-3 flex items-start gap-1.5 text-sm text-rose-700" role="alert">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                  {message(error, 'That code was not accepted.')}
                </p>
              ) : (
                // The banner above already says this when the code was only logged; repeating
                // the same sentence underneath reads as two different problems.
                delivery === 'mailed' && note && <p className="mt-3 text-sm text-slate-500">{note}</p>
              )}

              <Button type="submit" disabled={busy || !code.trim()} className="mt-5 w-full justify-center">
                {verify.isPending ? 'Checking…' : 'Open the demo'}
              </Button>

              <button
                type="button"
                onClick={() => {
                  setSent(false)
                  setCode('')
                  verify.reset()
                  requestCode.reset()
                }}
                className="mt-4 inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline"
              >
                <ArrowLeft className="size-3.5" />
                Use a different address
              </button>
            </form>
          )}
        </div>

        <p className="mt-5 text-center text-xs text-slate-400">
          Prototype. AI-generated validation assistance; final claim submission requires
          authorised human review.
        </p>
      </div>
    </div>
  )
}
