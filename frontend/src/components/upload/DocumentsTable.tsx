import { Check, Copy, FileImage, FileText, Inbox, X } from 'lucide-react'
import { useState } from 'react'

import { cx } from '../../lib/cx'
import { formatBytes } from '../../lib/format'
import type { ClaimDocument } from '../../lib/types'
import { Badge } from '../ui/Badge'
import { EmptyState } from '../ui/EmptyState'

export interface PendingUpload {
  key: string
  file: File
  state: 'uploading' | 'failed'
  progress: number
  error?: string
}

const COLUMNS = ['File', 'Size', 'Pages', 'Upload', 'Processing', 'Document ID']

function FileIcon({ name }: { name: string }) {
  const Icon = /\.(png|jpe?g)$/i.test(name) ? FileImage : FileText
  return (
    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500">
      <Icon className="size-4" />
    </span>
  )
}

function CopyableId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <span className="inline-flex items-center gap-1">
      <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700" title={id}>
        {id.slice(0, 8)}
      </code>
      <button
        type="button"
        aria-label="Copy document ID"
        className="rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
        onClick={() => {
          void navigator.clipboard
            ?.writeText(id)
            .then(() => {
              setCopied(true)
              window.setTimeout(() => setCopied(false), 1200)
            })
            .catch(() => undefined) // clipboard access can be denied; copying is a convenience only
        }}
      >
        {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5" />}
      </button>
    </span>
  )
}

interface DocumentsTableProps {
  documents: ClaimDocument[]
  pending: PendingUpload[]
  onDismiss: (key: string) => void
}

export function DocumentsTable({ documents, pending, onDismiss }: DocumentsTableProps) {
  if (documents.length === 0 && pending.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No documents uploaded yet"
        description="Drag files into the upload area, browse for them, or add the synthetic demo document pack."
      />
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-left text-sm" data-testid="documents-table">
        <thead>
          <tr className="border-b border-slate-100 bg-slate-50/60">
            {COLUMNS.map((column) => (
              <th
                key={column}
                scope="col"
                className="px-3 py-2.5 text-[11px] font-semibold tracking-wider whitespace-nowrap text-slate-500 uppercase"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {pending.map((item) => (
            <tr
              key={item.key}
              data-testid="document-row"
              data-filename={item.file.name}
              data-upload-state={item.state}
              className={cx('animate-fade-in', item.state === 'failed' && 'bg-rose-50/40')}
            >
              <td className="max-w-[15rem] px-3 py-3 2xl:max-w-[22rem]">
                <div className="flex items-center gap-3">
                  <FileIcon name={item.file.name} />
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-900" title={item.file.name}>
                      {item.file.name}
                    </p>
                    {item.error && <p className="text-xs text-rose-700">{item.error}</p>}
                  </div>
                </div>
              </td>
              <td className="px-3 py-3 whitespace-nowrap text-slate-600 tabular-nums">{formatBytes(item.file.size)}</td>
              <td className="px-3 py-3 text-slate-400">—</td>
              <td className="px-3 py-3">
                {item.state === 'uploading' ? (
                  <div className="w-32">
                    <div className="flex justify-between text-xs text-slate-600">
                      <span>Uploading</span>
                      <span className="tabular-nums">{Math.round(item.progress * 100)}%</span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-brand-500 transition-[width] duration-200"
                        style={{ width: `${Math.max(4, item.progress * 100)}%` }}
                      />
                    </div>
                  </div>
                ) : (
                  <Badge tone="danger" dot>
                    Failed
                  </Badge>
                )}
              </td>
              <td className="px-3 py-3 text-slate-400">—</td>
              <td className="px-3 py-3 text-right">
                {item.state === 'failed' ? (
                  <button
                    type="button"
                    onClick={() => onDismiss(item.key)}
                    className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                    aria-label={`Dismiss ${item.file.name}`}
                  >
                    <X className="size-4" />
                  </button>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
            </tr>
          ))}

          {documents.map((document) => (
            <tr
              key={document.id}
              data-testid="document-row"
              data-filename={document.filename}
              data-upload-state={document.upload_status}
              data-processing-state={document.processing_status}
              data-document-id={document.id}
            >
              <td className="max-w-[15rem] px-3 py-3 2xl:max-w-[22rem]">
                <div className="flex items-center gap-3">
                  <FileIcon name={document.filename} />
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-900" title={document.filename}>
                      {document.filename}
                    </p>
                    <p className="truncate text-xs text-slate-500" title={`SHA-256 ${document.sha256}`}>
                      {document.source === 'demo_pack' ? 'Demo pack · ' : ''}SHA-256 {document.sha256.slice(0, 12)}…
                    </p>
                  </div>
                </div>
              </td>
              <td className="px-3 py-3 whitespace-nowrap text-slate-600 tabular-nums">
                {formatBytes(document.size_bytes)}
              </td>
              <td className="px-3 py-3 text-slate-600 tabular-nums">{document.page_count ?? '—'}</td>
              <td className="px-3 py-3">
                <Badge tone="success" dot>
                  Uploaded
                </Badge>
              </td>
              <td className="px-3 py-3">
                <Badge tone="neutral">{document.processing_status === 'pending' ? 'Awaiting analysis' : document.processing_status}</Badge>
              </td>
              <td className="px-3 py-3">
                <CopyableId id={document.id} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
