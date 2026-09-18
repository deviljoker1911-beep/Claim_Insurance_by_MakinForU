import { Check } from 'lucide-react'

import { cx } from '../../lib/cx'
import type { WorkflowStep } from '../../lib/types'

/** Where the claim stands. Each step reports its own work, not the one before it. */
export function WorkflowStepper({ steps }: { steps: WorkflowStep[] }) {
  return (
    <ol
      className="flex snap-x gap-2 overflow-x-auto px-5 py-4"
      aria-label="Claim workflow"
      data-testid="workflow-stepper"
    >
      {steps.map((step, index) => (
        <li
          key={step.key}
          data-testid="workflow-step"
          data-step={step.key}
          data-status={step.status}
          aria-current={step.status === 'current' ? 'step' : undefined}
          title={step.detail}
          className={cx(
            'min-w-[8.5rem] flex-1 snap-start rounded-lg border px-3 py-2',
            step.status === 'current' && 'border-brand-200 bg-brand-50/70',
            step.status === 'complete' && 'border-emerald-100 bg-emerald-50/50',
            step.status === 'pending' && 'border-slate-200 bg-white',
          )}
        >
          <p className="flex items-center gap-1.5">
            <span
              className={cx(
                'grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold',
                step.status === 'complete' && 'bg-emerald-600 text-white',
                step.status === 'current' && 'bg-brand-600 text-white',
                step.status === 'pending' && 'bg-slate-100 text-slate-500',
              )}
            >
              {step.status === 'complete' ? <Check className="size-3" strokeWidth={3} /> : index + 1}
            </span>
            <span
              className={cx(
                'truncate text-xs font-medium',
                step.status === 'pending' ? 'text-slate-500' : 'text-slate-900',
              )}
            >
              {step.label}
            </span>
          </p>
          <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-slate-500">{step.detail}</p>
        </li>
      ))}
    </ol>
  )
}
