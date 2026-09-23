import { ArrowRight, FlaskConical, LoaderCircle } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { ClaimSteps } from '../components/claims/ClaimSteps'
import { Button } from '../components/ui/Button'
import { Card, CardHeader } from '../components/ui/Card'
import { Notice } from '../components/ui/Notice'
import { PageHeader } from '../components/ui/PageHeader'
import { errorMessage } from '../lib/api'
import { cx } from '../lib/cx'
import { fetchDemoClaimProfile, useCreateClaim } from '../lib/hooks'
import type { DemoClaimProfile } from '../lib/types'

type FieldName = 'patient_name' | 'uhid' | 'hospital' | 'insurer' | 'tpa' | 'admission_date' | 'discharge_date'
type FormState = Record<FieldName, string>

const EMPTY: FormState = {
  patient_name: '',
  uhid: '',
  hospital: '',
  insurer: '',
  tpa: '',
  admission_date: '',
  discharge_date: '',
}

const FIELDS: Array<{
  name: FieldName
  label: string
  type: 'text' | 'date'
  placeholder?: string
  wide?: boolean
  optional?: boolean
  maxLength?: number
}> = [
  { name: 'patient_name', label: 'Patient name', type: 'text', placeholder: 'As on the hospital records', maxLength: 200 },
  { name: 'uhid', label: 'UHID / IPD number', type: 'text', placeholder: 'e.g. UHID-000000', maxLength: 64 },
  { name: 'hospital', label: 'Hospital', type: 'text', placeholder: 'Treating hospital', wide: true, maxLength: 200 },
  { name: 'insurer', label: 'Insurer', type: 'text', placeholder: 'Insurance company', maxLength: 200 },
  {
    name: 'tpa',
    label: 'TPA',
    type: 'text',
    placeholder: 'Third-party administrator',
    optional: true,
    maxLength: 200,
  },
  { name: 'admission_date', label: 'Admission date', type: 'date' },
  { name: 'discharge_date', label: 'Discharge date', type: 'date' },
]

function validate(form: FormState): Partial<Record<FieldName, string>> {
  const errors: Partial<Record<FieldName, string>> = {}
  for (const field of FIELDS) {
    if (field.optional) continue
    const value = form[field.name].trim()
    if (!value) errors[field.name] = 'Required'
    else if (field.type === 'text' && value.length < 2) errors[field.name] = 'Too short'
  }
  if (form.admission_date && form.discharge_date && form.discharge_date < form.admission_date) {
    errors.discharge_date = 'Discharge date cannot be before the admission date'
  }
  return errors
}

export function NewClaimPage() {
  const navigate = useNavigate()
  const createClaim = useCreateClaim()
  const [form, setForm] = useState<FormState>(EMPTY)
  const [demoProfile, setDemoProfile] = useState<DemoClaimProfile | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [filling, setFilling] = useState(false)
  const [fillError, setFillError] = useState<string | null>(null)

  const errors = validate(form)
  const hasErrors = Object.keys(errors).length > 0
  // Only a claim that still carries the synthetic patient's identity is flagged as a demo claim.
  const isDemo =
    demoProfile !== null &&
    form.patient_name.trim() === demoProfile.patient_name &&
    form.uhid.trim() === demoProfile.uhid

  async function fillDemoDetails() {
    setFilling(true)
    setFillError(null)
    try {
      const profile = await fetchDemoClaimProfile()
      setForm({ ...profile, tpa: profile.tpa ?? '' })
      setDemoProfile(profile)
    } catch (error) {
      setFillError(errorMessage(error))
    } finally {
      setFilling(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitted(true)
    if (hasErrors || createClaim.isPending) return
    createClaim.mutate(
      {
        patient_name: form.patient_name.trim(),
        uhid: form.uhid.trim(),
        hospital: form.hospital.trim(),
        insurer: form.insurer.trim(),
        tpa: form.tpa.trim() || null,
        admission_date: form.admission_date,
        discharge_date: form.discharge_date,
        is_demo: isDemo,
      },
      { onSuccess: (claim) => navigate(`/claims/${claim.id}/intake`) },
    )
  }

  return (
    <>
      <PageHeader
        title="New claim"
        description="Register the claim, add its hospital documents, then run pre-submission validation."
        actions={
          <Button variant="secondary" onClick={fillDemoDetails} disabled={filling} data-testid="fill-demo">
            {filling ? <LoaderCircle className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
            Fill demo claim details
          </Button>
        }
      />

      <ClaimSteps current={0} />

      <Card className="max-w-4xl">
        <CardHeader title="Claim details" description="As recorded on the hospital admission and insurer documents." />
        <form noValidate onSubmit={handleSubmit} className="p-5" data-testid="new-claim-form">
          <div className="space-y-3">
            {isDemo && (
              <Notice tone="warning">
                Synthetic demo claim details filled in. All patient and hospital information is fictional.
              </Notice>
            )}
            {fillError && <Notice tone="danger">Demo details could not be loaded: {fillError}</Notice>}
            {createClaim.error && <Notice tone="danger">{errorMessage(createClaim.error)}</Notice>}
          </div>

          <div className="mt-1 grid grid-cols-1 gap-x-5 gap-y-4 pt-3 sm:grid-cols-2">
            {FIELDS.map((field) => {
              const error = submitted ? errors[field.name] : undefined
              return (
                <label key={field.name} className={cx('block', field.wide && 'sm:col-span-2')}>
                  <span className="text-sm font-medium text-slate-700">
                    {field.label}
                    {field.optional && <span className="ml-1 font-normal text-slate-400">(optional)</span>}
                  </span>
                  <input
                    name={field.name}
                    type={field.type}
                    value={form[field.name]}
                    placeholder={field.placeholder}
                    maxLength={field.maxLength}
                    aria-invalid={Boolean(error)}
                    onChange={(event) => setForm((current) => ({ ...current, [field.name]: event.target.value }))}
                    className={cx(
                      'mt-1.5 block h-10 w-full rounded-lg border bg-white px-3 text-sm text-slate-900 shadow-sm transition outline-none placeholder:text-slate-400 focus:ring-3',
                      error
                        ? 'border-rose-300 focus:border-rose-400 focus:ring-rose-100'
                        : 'border-slate-200 focus:border-brand-400 focus:ring-brand-100',
                    )}
                  />
                  {error && <span className="mt-1 block text-xs text-rose-600">{error}</span>}
                </label>
              )
            })}
          </div>

          <div className="mt-6 flex flex-col gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <p className="text-xs text-slate-500">A claim number is assigned when the claim is created.</p>
            <Button
              type="submit"
              disabled={createClaim.isPending || (submitted && hasErrors)}
              data-testid="create-claim"
              className="w-full justify-center sm:w-auto"
            >
              {createClaim.isPending ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <ArrowRight className="size-4" />
              )}
              Create claim &amp; continue
            </Button>
          </div>
        </form>
      </Card>
    </>
  )
}
