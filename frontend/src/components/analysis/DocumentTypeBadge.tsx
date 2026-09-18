import { EyeOff, FileQuestion, TriangleAlert } from 'lucide-react'

import { Badge } from '../ui/Badge'
import type { DocumentProcessing } from '../../lib/types'

/** The document type the pipeline decided on, with how sure it was. */
export function DocumentTypeBadge({ processing }: { processing: DocumentProcessing }) {
  if (processing.processing_status !== 'processed') return <span className="text-slate-400">—</span>
  if (!processing.doc_type || processing.doc_type === 'other') {
    return (
      <Badge tone="warning">
        <FileQuestion className="size-3.5" />
        Unclassified
      </Badge>
    )
  }
  const confidence = processing.doc_type_confidence ?? 0
  return (
    <span className="inline-flex items-center gap-1.5">
      <Badge tone={confidence >= 0.8 ? 'brand' : 'warning'}>{processing.doc_type_label ?? processing.doc_type}</Badge>
      <span className="text-xs tabular-nums text-slate-400" title="Classification confidence">
        {Math.round(confidence * 100)}%
      </span>
    </span>
  )
}

/** Quality signals and covered text, as counts. The findings they feed are listed separately. */
export function DocumentSignals({ processing }: { processing: DocumentProcessing }) {
  const { review, attention } = processing.quality_flag_counts
  const concealed = processing.concealed_text_count
  if (!review && !attention && !concealed) {
    return processing.processing_status === 'processed' ? (
      <span className="text-xs text-slate-400">No signals</span>
    ) : (
      <span className="text-slate-400">—</span>
    )
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {review > 0 && (
        <Badge tone="danger" title="Signals that need a human look">
          <TriangleAlert className="size-3.5" />
          {review} review
        </Badge>
      )}
      {attention > 0 && <Badge tone="warning">{attention} attention</Badge>}
      {concealed > 0 && (
        <Badge tone="danger" title="Text in the file is covered by opaque paint; it is excluded from extracted values">
          <EyeOff className="size-3.5" />
          Covered text
        </Badge>
      )}
    </span>
  )
}
