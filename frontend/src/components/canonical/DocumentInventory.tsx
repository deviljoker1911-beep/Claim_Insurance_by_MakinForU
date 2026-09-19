import { CircleHelp, Copy, EyeOff, FileImage, FileStack, FileText, ScanText, TriangleAlert } from 'lucide-react'
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

/** The files that were uploaded, and how many documents were read out of each. */
function sourceFiles(items: DocumentInventoryItem[]) {
  const files = new Map<string, { filename: string; pages: number | null; documents: DocumentInventoryItem[] }>()
  for (const item of items) {
    const key = item.source_file_id ?? item.document_id
    const entry = files.get(key) ?? {
      filename: item.filename,
      pages: item.source_page_count ?? item.page_count,
      documents: [],
    }
    entry.documents.push(item)
    files.set(key, entry)
  }
  return [...files.values()]
}

export function DocumentInventory({ items, claimId }: { items: DocumentInventoryItem[]; claimId: string }) {
  // A claim packet arrives as one file holding many documents. Where that happened, the file is
  // named above the documents that were found inside it, so the two are not confused.
  const bundles = sourceFiles(items).filter((file) => file.documents.length > 1)
  return (
    <div className="overflow-x-auto">
      {bundles.length > 0 && (
        <ul className="border-b border-slate-100 px-3 py-2.5 text-xs text-slate-600" data-testid="source-files">
          {bundles.map((file) => (
            <li key={file.filename + String(file.pages)} className="flex items-center gap-2 py-0.5">
              <FileStack className="size-3.5 shrink-0 text-slate-400" />
              <span className="font-medium text-slate-900">{file.filename}</span>
              <span className="text-slate-500">
                {file.pages} pages · read as {file.documents.length} documents
              </span>
            </li>
          ))}
        </ul>
      )}
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
            // Pages the reader could not place. Shown as its own badge because "uncertain" is a
            // different thing from a page that is hard to read.
            const uncertain = item.quality_signals.find((signal) => signal.code === 'classification_uncertain')
            return (
              <tr
                key={item.document_id}
                data-testid="inventory-row"
                data-doc-type={item.doc_type ?? ''}
                data-excluded={item.excluded}
                className={item.excluded ? 'bg-slate-50/60' : undefined}
              >
                <td className="max-w-[16rem] px-3 py-3">
                  <div className="flex items-center gap-3">
                    <Icon name={item.filename} />
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-900" title={item.display_name ?? item.filename}>
                        {item.display_name ?? item.filename}
                      </p>
                      <p className="text-xs text-slate-500">
                        {item.is_part_of_a_bundle ? (
                          <>
                            page{item.page_numbers.length === 1 ? '' : 's'} {item.page_span} of {item.filename}
                          </>
                        ) : (
                          formatBytes(item.size_bytes)
                        )}{' '}
                        · {item.extracted_field_count} values
                      </p>
                      {item.excluded && (
                        <p className="mt-0.5 inline-flex items-center gap-1 text-xs text-slate-500" title={item.exclusion_reason ?? undefined}>
                          <Copy className="size-3" />
                          Excluded as a duplicate — its values are not used
                        </p>
                      )}
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
                <td className="px-3 py-3 text-slate-600 tabular-nums" title={item.is_part_of_a_bundle ? `pages ${item.page_span} of ${item.filename}` : undefined}>
                  {item.page_count ?? '—'}
                </td>
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
                    {uncertain && (
                      <Badge tone="warning" title={uncertain.detail}>
                        <CircleHelp className="size-3.5" />
                        Uncertain
                      </Badge>
                    )}
                    {review + attention + item.concealed_text_count === 0 && (
                      <span className="text-xs text-slate-400">None</span>
                    )}
                  </span>
                </td>
                <td className="px-3 py-3 text-slate-600 tabular-nums">{item.extracted_field_count}</td>
                <td className="px-3 py-3">
                  {item.excluded ? (
                    <Badge tone="neutral">Excluded</Badge>
                  ) : item.processing_status === 'processed' ? (
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
        A copy excluded as a duplicate stays in this list; its values are not used.{' '}
        <Link to={`/claims/${claimId}/intake`} className="font-medium text-brand-700 hover:underline">
          Manage documents
        </Link>
      </p>
    </div>
  )
}
