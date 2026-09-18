import { EyeOff, FileImage, FileText, ScanText, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'

import { formatBytes } from '../../lib/format'
import type { DocumentInventoryItem } from '../../lib/types'
import { Badge } from '../ui/Badge'

const COLUMNS = ['Document', 'Type', 'Pages', 'Read by', 'Signals', 'Values', 'Status']

function Icon({ name }: { name: string }) {
  const Glyph = /\.(png|jpe?g)$/i.test(name) ? FileImage : FileText
  return (
    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500">
      <Glyph className="size-4" />
    </span>
  )
}

export function DocumentInventory({ items, claimId }: { items: DocumentInventoryItem[]; claimId: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-left text-sm" data-testid="document-inventory">
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
          {items.map((item) => {
            const review = item.quality_signals.filter((signal) => signal.severity === 'review').length
            const attention = item.quality_signals.length - review
            return (
              <tr key={item.document_id} data-testid="inventory-row" data-doc-type={item.doc_type ?? ''}>
                <td className="max-w-[16rem] px-3 py-3">
                  <div className="flex items-center gap-3">
                    <Icon name={item.filename} />
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-900" title={item.filename}>
                        {item.filename}
                      </p>
                      <p className="text-xs text-slate-500">
                        {formatBytes(item.size_bytes)} · {item.extracted_field_count} values
                      </p>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-3">
                  {item.doc_type_label ? (
                    <span className="inline-flex items-center gap-1.5">
                      <Badge tone={(item.classification_confidence ?? 0) >= 0.8 ? 'brand' : 'warning'}>
                        {item.doc_type_label}
                      </Badge>
                      <span className="text-xs text-slate-400 tabular-nums">
                        {Math.round((item.classification_confidence ?? 0) * 100)}%
                      </span>
                    </span>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
                <td className="px-3 py-3 text-slate-600 tabular-nums">{item.page_count ?? '—'}</td>
                <td className="px-3 py-3 whitespace-nowrap text-xs text-slate-600">
                  {item.ocr_engine ? (
                    <span className="inline-flex items-center gap-1">
                      <ScanText className="size-3.5 text-slate-400" />
                      {item.ocr_engine === 'demo_fixture' ? 'Demo fixture' : 'OCR'}
                    </span>
                  ) : (
                    'Text layer'
                  )}
                </td>
                <td className="px-3 py-3">
                  <span className="inline-flex flex-wrap items-center gap-1.5">
                    {review > 0 && (
                      <Badge tone="danger" title={item.quality_signals.map((signal) => signal.detail).join(' · ')}>
                        <TriangleAlert className="size-3.5" />
                        {review} review
                      </Badge>
                    )}
                    {attention > 0 && <Badge tone="warning">{attention} attention</Badge>}
                    {item.concealed_text_count > 0 && (
                      <Badge tone="danger" title="Text in the file is covered by opaque paint">
                        <EyeOff className="size-3.5" />
                        Covered text
                      </Badge>
                    )}
                    {review + attention + item.concealed_text_count === 0 && (
                      <span className="text-xs text-slate-400">None</span>
                    )}
                  </span>
                </td>
                <td className="px-3 py-3 text-slate-600 tabular-nums">{item.extracted_field_count}</td>
                <td className="px-3 py-3">
                  {item.processing_status === 'processed' ? (
                    <Badge tone="success" dot>
                      Processed
                    </Badge>
                  ) : item.processing_status === 'failed' ? (
                    <Badge tone="danger" dot title={item.processing_error ?? undefined}>
                      Failed
                    </Badge>
                  ) : (
                    <Badge tone="neutral">{item.processing_status}</Badge>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="px-3 py-3 text-xs text-slate-500">
        Duplicate and exclusion states are evaluated in a later phase.{' '}
        <Link to={`/claims/${claimId}/intake`} className="font-medium text-brand-700 hover:underline">
          Manage documents
        </Link>
      </p>
    </div>
  )
}
