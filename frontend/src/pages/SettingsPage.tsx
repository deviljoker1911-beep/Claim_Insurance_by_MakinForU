import { Bot, CircleX, Cpu, Database, FlaskConical, RefreshCw, Server, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { PageHeader } from '../components/ui/PageHeader'
import { Skeleton } from '../components/ui/Skeleton'
import { iconTones, type Tone } from '../components/ui/styles'
import { cx } from '../lib/cx'
import { useHealth } from '../lib/hooks'
import type { HealthResponse } from '../lib/types'

const DIALECTS: Record<string, string> = { postgresql: 'PostgreSQL', sqlite: 'SQLite' }
const PROVIDERS: Record<string, string> = {
  demo: 'Demo reasoning engine',
  anthropic: 'Anthropic Claude',
  openai: 'OpenAI-compatible',
}

export function SettingsPage() {
  const health = useHealth()

  return (
    <>
      <PageHeader
        title="Settings"
        description="Environment, document-processing engines and AI provider configuration."
        actions={
          <Button variant="secondary" size="sm" onClick={() => health.refetch()} disabled={health.isFetching}>
            <RefreshCw className={cx('size-4', health.isFetching && 'animate-spin')} />
            Refresh
          </Button>
        }
      />
      {health.status === 'pending' && <SettingsSkeleton />}
      {health.status === 'error' && (
        <Card>
          <EmptyState
            icon={CircleX}
            title="The ClaimAI API is unreachable"
            description={`${health.error.message}. Start the backend with "make backend" and try again.`}
            action={<Button onClick={() => health.refetch()}>Retry</Button>}
          />
        </Card>
      )}
      {health.status === 'success' && <SettingsContent data={health.data} />}
    </>
  )
}

function SettingsContent({ data }: { data: HealthResponse }) {
  const { database, engines, llm } = data
  return (
    <div className="space-y-6">
      <section aria-label="System status" className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <StatusTile
          icon={Server}
          tone="success"
          label="API"
          value="Online"
          detail={`v${data.version} · ${data.environment}`}
        />
        <StatusTile
          icon={Database}
          tone={database.ok ? 'success' : 'danger'}
          label="Database"
          value={`${DIALECTS[database.dialect] ?? database.dialect} ${database.ok ? 'connected' : 'unavailable'}`}
          detail={
            database.ok
              ? [database.database, database.host && `${database.host}:${database.port}`, database.server_version && `v${database.server_version}`]
                  .filter(Boolean)
                  .join(' · ')
              : (database.error ?? 'Connection failed')
          }
        />
        <StatusTile
          icon={FlaskConical}
          tone={data.demo_mode ? 'warning' : 'brand'}
          label="Processing mode"
          value={data.demo_mode ? 'Demo mode' : 'Live mode'}
          detail={
            data.demo_mode
              ? 'Deterministic results for synthetic demo documents'
              : 'Real OCR and configured AI provider'
          }
        />
      </section>

      <Card>
        <CardHeader
          title="Document processing engines"
          description="OCR and document-understanding components available to the processing pipeline."
        />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60">
                {['Engine', 'Role', 'Status'].map((column) => (
                  <th
                    key={column}
                    scope="col"
                    className="px-5 py-2.5 text-[11px] font-semibold tracking-wider text-slate-500 uppercase"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {engines.map((engine) => (
                <tr key={engine.key}>
                  <td className="px-5 py-3">
                    <span className="flex items-center gap-2 font-medium text-slate-900">
                      <Cpu className="size-4 text-slate-400" />
                      {engine.name}
                      {engine.optional && <Badge>Optional</Badge>}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-600">{engine.role}</td>
                  <td className="px-5 py-3">
                    {engine.available ? (
                      <Badge tone="success" dot>
                        Available{engine.version ? ` · v${engine.version}` : ''}
                      </Badge>
                    ) : (
                      <Badge tone="neutral" dot>
                        Not installed
                      </Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="AI provider"
          description="Used only for semantic tasks. Deterministic rules handle all deterministic validation."
        />
        <dl className="grid grid-cols-1 gap-x-8 gap-y-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Provider">
            <span className="flex items-center gap-2">
              <Bot className="size-4 text-brand-600" />
              {PROVIDERS[llm.provider] ?? llm.provider}
            </span>
          </Field>
          <Field label="Model">
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">{llm.model || 'not set'}</code>
          </Field>
          <Field label="Mode">
            <Badge tone={llm.mode === 'remote' ? 'brand' : 'info'}>
              {llm.mode === 'remote' ? 'Remote API' : 'Offline, deterministic'}
            </Badge>
          </Field>
          <Field label="API key">
            {llm.provider === 'demo' ? (
              <span className="text-slate-500">Not required</span>
            ) : llm.api_key_configured ? (
              <Badge tone="success" dot>
                Configured
              </Badge>
            ) : (
              <Badge tone="warning" dot>
                Missing
              </Badge>
            )}
          </Field>
        </dl>
      </Card>
    </div>
  )
}

function StatusTile({
  icon: Icon,
  tone,
  label,
  value,
  detail,
}: {
  icon: LucideIcon
  tone: Tone
  label: string
  value: string
  detail: string
}) {
  return (
    <Card className="flex items-start gap-4 p-5">
      <span className={cx('grid size-10 shrink-0 place-items-center rounded-lg', iconTones[tone])}>
        <Icon className="size-5" />
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</p>
        <p className="mt-0.5 font-semibold text-slate-900">{value}</p>
        <p className="mt-0.5 truncate text-xs text-slate-500" title={detail}>
          {detail}
        </p>
      </div>
    </Card>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1.5 text-sm font-medium text-slate-900">{children}</dd>
    </div>
  )
}

function SettingsSkeleton() {
  return (
    <div className="space-y-6" aria-busy>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {[0, 1, 2].map((key) => (
          <Card key={key} className="flex items-center gap-4 p-5">
            <Skeleton className="size-10 rounded-lg" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-4 w-32" />
            </div>
          </Card>
        ))}
      </div>
      <Card className="space-y-3 p-5">
        {[0, 1, 2, 3].map((key) => (
          <Skeleton key={key} className="h-5 w-full" />
        ))}
      </Card>
    </div>
  )
}
