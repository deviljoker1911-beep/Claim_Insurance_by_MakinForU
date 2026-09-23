import { Check } from 'lucide-react'

import { cx } from '../../lib/cx'

const STEPS = [
  { label: 'Claim details', description: 'Patient, hospital and insurer' },
  { label: 'Upload documents', description: 'PDF, JPG or PNG files' },
  { label: 'Run analysis', description: 'OCR, validation and checklist' },
]

export function ClaimSteps({ current }: { current: number }) {
  return (
    <ol className="mb-5 grid grid-cols-3 gap-2 sm:mb-6 sm:gap-3" aria-label="Claim intake steps">
      {STEPS.map((step, index) => {
        const done = index < current
        const active = index === current
        return (
          <li
            key={step.label}
            aria-current={active ? 'step' : undefined}
            className={cx(
              // A third of a phone is too narrow for a number, a title and a subtitle side by side,
              // so there the number sits above the title and the subtitle goes.
              'flex flex-col items-start gap-1.5 rounded-xl border px-3 py-2.5 transition-colors sm:flex-row sm:items-center sm:gap-3 sm:px-4 sm:py-3',
              active ? 'border-brand-200 bg-brand-50/70' : 'border-slate-200 bg-white',
            )}
          >
            <span
              className={cx(
                'grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold',
                done && 'bg-emerald-600 text-white',
                active && 'bg-brand-600 text-white',
                !done && !active && 'bg-slate-100 text-slate-500',
              )}
            >
              {done ? <Check className="size-3.5" strokeWidth={3} /> : index + 1}
            </span>
            <div className="min-w-0">
              <p className={cx('text-xs font-medium sm:text-sm', active ? 'text-brand-900' : 'text-slate-700')}>
                {step.label}
              </p>
              <p className="hidden truncate text-xs text-slate-500 sm:block">
                {done ? 'Completed' : step.description}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
