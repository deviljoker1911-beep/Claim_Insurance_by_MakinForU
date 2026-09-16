import { Info } from 'lucide-react'

import { Button } from '../components/ui/Button'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { cx } from '../lib/cx'

const STEPS = [
  { label: 'Claim details', description: 'Patient, hospital and insurer' },
  { label: 'Upload documents', description: 'PDF, JPG or PNG files' },
  { label: 'Run analysis', description: 'OCR, validation and checklist' },
]

const FIELDS: Array<{ id: string; label: string; type: 'text' | 'date'; placeholder?: string; wide?: boolean }> = [
  { id: 'patient_name', label: 'Patient name', type: 'text', placeholder: 'e.g. Rajesh Sharma' },
  { id: 'uhid', label: 'UHID / IPD number', type: 'text', placeholder: 'e.g. UHID-123456' },
  { id: 'hospital', label: 'Hospital', type: 'text', placeholder: 'e.g. CityCare Multispeciality Hospital', wide: true },
  { id: 'insurer', label: 'Insurer', type: 'text', placeholder: 'e.g. Demo Health Insurance' },
  { id: 'tpa', label: 'TPA', type: 'text', placeholder: 'e.g. Demo TPA' },
  { id: 'admission_date', label: 'Admission date', type: 'date' },
  { id: 'discharge_date', label: 'Discharge date', type: 'date' },
]

export function NewClaimPage() {
  return (
    <>
      <PageHeader
        title="New claim"
        description="Register the claim, add its hospital documents, then run pre-submission validation."
      />

      <ol className="mb-6 grid grid-cols-3 gap-3" aria-label="Claim creation steps">
        {STEPS.map((step, index) => {
          const current = index === 0
          return (
            <li
              key={step.label}
              aria-current={current ? 'step' : undefined}
              className={cx(
                'flex items-center gap-3 rounded-xl border px-4 py-3',
                current ? 'border-brand-200 bg-brand-50/60' : 'border-slate-200 bg-white',
              )}
            >
              <span
                className={cx(
                  'grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold',
                  current ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-500',
                )}
              >
                {index + 1}
              </span>
              <div className="min-w-0">
                <p className={cx('text-sm font-medium', current ? 'text-brand-900' : 'text-slate-700')}>{step.label}</p>
                <p className="truncate text-xs text-slate-500">{step.description}</p>
              </div>
            </li>
          )
        })}
      </ol>

      <Card className="max-w-4xl">
        <CardHeader title="Claim details" description="As recorded on the hospital admission and insurer documents." />
        <form className="grid grid-cols-2 gap-x-5 gap-y-4 p-5" onSubmit={(event) => event.preventDefault()}>
          {FIELDS.map((field) => (
            <label key={field.id} className={cx('block', field.wide && 'col-span-2')}>
              <span className="text-sm font-medium text-slate-700">{field.label}</span>
              <input
                name={field.id}
                type={field.type}
                placeholder={field.placeholder}
                className="mt-1.5 block h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 shadow-sm transition outline-none placeholder:text-slate-400 focus:border-brand-400 focus:ring-3 focus:ring-brand-100"
              />
            </label>
          ))}
          <div className="col-span-2 mt-2 flex items-center justify-between gap-4 border-t border-slate-100 pt-4">
            <p className="flex items-center gap-2 text-xs text-slate-500">
              <Info className="size-3.5 text-sky-600" />
              Claim creation and document upload are enabled in the next build phase.
            </p>
            <Button type="submit" disabled>
              Create claim &amp; continue
            </Button>
          </div>
        </form>
      </Card>
    </>
  )
}
