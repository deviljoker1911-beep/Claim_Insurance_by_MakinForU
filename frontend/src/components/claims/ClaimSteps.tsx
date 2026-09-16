import { Check } from 'lucide-react'

import { cx } from '../../lib/cx'

const STEPS = [
  { label: 'Claim details', description: 'Patient, hospital and insurer' },
  { label: 'Upload documents', description: 'PDF, JPG or PNG files' },
  { label: 'Run analysis', description: 'OCR, validation and checklist' },
]

export function ClaimSteps({ current }: { current: number }) {
  return (
    <ol className="mb-6 grid grid-cols-3 gap-3" aria-label="Claim intake steps">
      {STEPS.map((step, index) => {
        const done = index < current
        const active = index === current
        return (
          <li
            key={step.label}
            aria-current={active ? 'step' : undefined}
            className={cx(
              'flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors',
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
              <p className={cx('text-sm font-medium', active ? 'text-brand-900' : 'text-slate-700')}>{step.label}</p>
              <p className="truncate text-xs text-slate-500">{done ? 'Completed' : step.description}</p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
