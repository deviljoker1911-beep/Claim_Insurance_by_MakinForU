/** Display helpers for canonical claim values. */

import { formatDate } from './format'
import type { CanonicalValue } from './types'

/** Indian digit grouping, as the documents print amounts. */
export function formatAmount(value: string | null | undefined): string {
  if (!value) return '—'
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : value
}

export function formatCanonicalValue(value: CanonicalValue): string {
  if (!value.value) return '—'
  if (value.kind === 'date') return formatDate(value.value)
  if (value.kind === 'gender') return value.value.charAt(0).toUpperCase() + value.value.slice(1)
  if (value.kind === 'amount') return formatAmount(value.value)
  return value.value
}
