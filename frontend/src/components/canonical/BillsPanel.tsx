import { ChevronDown, ChevronRight, Receipt } from 'lucide-react'
import { useState } from 'react'

import { formatAmount as amount } from '../../lib/canonical'
import { cx } from '../../lib/cx'
import { formatDate } from '../../lib/format'
import type { CanonicalBill, CanonicalBillLine, EvidenceSource } from '../../lib/types'
import { EmptyState } from '../ui/EmptyState'
import { SourceChip, type EvidenceOpener } from './CanonicalField'

/** A billed line as an evidence source, so its row on the page can be shown. */
function lineSource(bill: CanonicalBill, line: CanonicalBillLine): EvidenceSource {
  const evidence = line.evidence
  return {
    document_id: evidence.document_id,
    document_name: evidence.document_name,
    document_type: evidence.document_type,
    document_type_label: bill.bill_type_label,
    page: evidence.page,
    bounding_box: evidence.bounding_box,
    snippet: evidence.snippet,
    method: evidence.method,
    source_type: evidence.source_type,
    source_type_label: evidence.source_type === 'ocr' ? 'OCR' : 'Text layer',
    extraction_method: 'bill table row',
    confidence: evidence.confidence,
    weight: 1,
    eligible: true,
    excluded_reason: null,
    value: line.amount,
    raw_value: null,
    field_key: 'bills.line_item',
    derived_from: null,
    evidence_available: evidence.evidence_available,
  }
}

export function BillsPanel({ bills, onOpen }: { bills: CanonicalBill[]; onOpen: EvidenceOpener }) {
  const [open, setOpen] = useState<string | null>(null)

  if (bills.length === 0) {
    return (
      <EmptyState
        icon={Receipt}
        title="No bills read yet"
        description="Hospital, pharmacy, theatre and implant bills appear here once they are analysed."
      />
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm" data-testid="bills-table">
        <thead>
          <tr className="border-b border-slate-100 bg-slate-50/60">
            {['Bill', 'Number', 'Date', 'Lines', 'Subtotal', 'Tax', 'Total'].map((column) => (
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
          {bills.map((bill) => {
            const expanded = open === bill.document_id
            return [
              <tr key={bill.document_id} data-testid="bill-row" data-bill-type={bill.bill_type ?? ''}>
                <td className="px-3 py-3">
                  <button
                    type="button"
                    onClick={() => setOpen(expanded ? null : bill.document_id)}
                    className="flex items-center gap-2 text-left font-medium text-slate-900 hover:text-brand-700"
                    aria-expanded={expanded}
                    data-testid="bill-toggle"
                  >
                    {expanded ? (
                      <ChevronDown className="size-4 text-slate-400" />
                    ) : (
                      <ChevronRight className="size-4 text-slate-400" />
                    )}
                    <span>
                      {bill.bill_type_label ?? 'Bill'}
                      <span className="block truncate text-xs font-normal text-slate-500" title={bill.document_name}>
                        {bill.document_name}
                      </span>
                    </span>
                  </button>
                </td>
                <td className="px-3 py-3">
                  <div className="font-medium text-slate-900">{bill.fields.number?.value ?? '—'}</div>
                  {bill.fields.number && <SourceChip value={bill.fields.number} onOpen={onOpen} label="Bill number" />}
                </td>
                <td className="px-3 py-3 whitespace-nowrap">
                  <div className="text-slate-700">
                    {bill.fields.date?.value ? formatDate(bill.fields.date.value) : '—'}
                  </div>
                  {bill.fields.date && <SourceChip value={bill.fields.date} onOpen={onOpen} label="Bill date" />}
                </td>
                <td className="px-3 py-3 text-slate-600 tabular-nums">{bill.line_item_count}</td>
                <td className="px-3 py-3 text-slate-600 tabular-nums">{amount(bill.fields.subtotal?.value)}</td>
                <td className="px-3 py-3 text-slate-600 tabular-nums">
                  {bill.fields.tax?.present ? amount(bill.fields.tax.value) : '—'}
                </td>
                <td className="px-3 py-3">
                  <div className="font-semibold text-slate-900 tabular-nums">{amount(bill.fields.total?.value)}</div>
                  {bill.fields.total && <SourceChip value={bill.fields.total} onOpen={onOpen} label="Bill total" />}
                </td>
              </tr>,
              expanded ? (
                <tr key={`${bill.document_id}-lines`} className="bg-slate-50/50">
                  <td colSpan={7} className="px-3 py-3">
                    <table className="w-full text-left text-[13px]" data-testid="bill-lines">
                      <thead>
                        <tr className="text-[10.5px] tracking-wider text-slate-500 uppercase">
                          <th className="py-1.5 pr-3 font-semibold">#</th>
                          <th className="py-1.5 pr-3 font-semibold">Item</th>
                          {bill.columns.includes('batch') && <th className="py-1.5 pr-3 font-semibold">Batch</th>}
                          {bill.columns.includes('expiry') && <th className="py-1.5 pr-3 font-semibold">Expiry</th>}
                          <th className="py-1.5 pr-3 font-semibold">Qty</th>
                          <th className="py-1.5 pr-3 font-semibold">Rate</th>
                          <th className="py-1.5 pr-3 font-semibold">Amount</th>
                          <th className="py-1.5 font-semibold">Evidence</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-200/70">
                        {bill.line_items.map((line, index) => (
                          <tr key={`${line.line_no}-${index}`} data-testid="bill-line">
                            <td className="py-1.5 pr-3 text-slate-500 tabular-nums">{line.line_no ?? '—'}</td>
                            <td className="max-w-[22rem] py-1.5 pr-3">
                              <span className="block truncate text-slate-800" title={line.description ?? ''}>
                                {line.description}
                              </span>
                            </td>
                            {bill.columns.includes('batch') && (
                              <td className="py-1.5 pr-3 text-slate-600">{line.batch ?? '—'}</td>
                            )}
                            {bill.columns.includes('expiry') && (
                              <td className="py-1.5 pr-3 text-slate-600">{line.expiry ?? '—'}</td>
                            )}
                            <td className="py-1.5 pr-3 text-slate-600 tabular-nums">{line.quantity ?? '—'}</td>
                            <td className="py-1.5 pr-3 text-slate-600 tabular-nums">{amount(line.rate)}</td>
                            <td className="py-1.5 pr-3 font-medium text-slate-900 tabular-nums">
                              {amount(line.amount)}
                            </td>
                            <td className="py-1.5">
                              <button
                                type="button"
                                data-testid="bill-line-source"
                                onClick={() =>
                                  onOpen({
                                    title: `${bill.bill_type_label ?? 'Bill'} · line ${line.line_no ?? index + 1}`,
                                    value: line.description,
                                    sources: [lineSource(bill, line)],
                                  })
                                }
                                className={cx(
                                  'rounded-md px-1.5 py-0.5 text-[11px] font-medium tracking-wide uppercase transition',
                                  line.evidence.evidence_available
                                    ? 'text-slate-500 hover:bg-brand-50 hover:text-brand-700'
                                    : 'cursor-not-allowed text-slate-300',
                                )}
                                disabled={!line.evidence.evidence_available}
                              >
                                p{line.evidence.page ?? '—'}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {bill.notes.length > 0 && (
                      <p className="mt-2 text-xs text-slate-500">{bill.notes.join(' · ')}</p>
                    )}
                  </td>
                </tr>
              ) : null,
            ]
          })}
        </tbody>
      </table>
    </div>
  )
}
