import { FileDown, FileSpreadsheet, FileText } from 'lucide-react'

import { reportUrls } from '../../lib/api'
import { cx } from '../../lib/cx'

const LINK =
  'inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm ' +
  'font-medium text-slate-700 shadow-sm hover:bg-slate-50 hover:text-slate-900'

/** The same report, in the format the reader needs it in. */
export function ReportActions({
  claimId,
  size = 'md',
  className,
}: {
  claimId: string
  size?: 'sm' | 'md'
  className?: string
}) {
  const urls = reportUrls(claimId)
  const style = cx(LINK, size === 'sm' && 'px-2.5 py-1 text-xs', 'whitespace-nowrap')
  const icon = size === 'sm' ? 'size-3.5' : 'size-4'
  return (
    <span className={cx('flex flex-wrap items-center gap-2', className)} data-testid="report-actions">
      <a className={style} href={urls.html} target="_blank" rel="noreferrer" data-testid="report-html">
        <FileText className={icon} />
        View report
      </a>
      <a className={style} href={urls.pdf} data-testid="report-pdf">
        <FileDown className={icon} />
        PDF
      </a>
      <a className={style} href={urls.xlsx} data-testid="report-xlsx">
        <FileSpreadsheet className={icon} />
        Excel
      </a>
    </span>
  )
}
