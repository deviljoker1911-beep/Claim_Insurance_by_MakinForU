/** Minimal client for the ClaimAI API (served under /api, proxied by Vite in development). */

import type { FileError } from './types'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function describe(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{ loc: ['body', 'field'], msg, type }]
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== 'object' || !('msg' in item)) return ''
        const message = String(item.msg).replace(/^Value error, /, '')
        const location = 'loc' in item && Array.isArray(item.loc) ? item.loc : []
        const field = location.length > 1 ? location.at(-1) : null
        return typeof field === 'string' ? `${field.replaceAll('_', ' ')}: ${message}` : message
      })
      .filter(Boolean)
    if (messages.length) return messages.join('; ')
  }
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') {
    return detail.message
  }
  return `Request failed (${status})`
}

function toApiError(status: number, isJson: boolean, payload: unknown): ApiError {
  if (!isJson && [502, 503, 504].includes(status)) {
    // The dev proxy answers with a bare gateway error when the API process is down.
    return new ApiError(status, 'Cannot reach the ClaimAI API', payload)
  }
  const detail = isJson && payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : payload
  return new ApiError(status, describe(detail, status), detail)
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  // FastAPI only parses JSON bodies that declare their content type; multipart uploads set their own.
  if (init.body !== undefined && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(`/api${path}`, { ...init, headers })
  } catch (error) {
    throw new ApiError(0, 'Cannot reach the ClaimAI API', error)
  }

  const isJson = response.headers.get('content-type')?.includes('application/json') ?? false
  const payload: unknown = isJson ? await response.json() : await response.text()
  if (!response.ok) throw toApiError(response.status, isJson, payload)
  return payload as T
}

/** Multipart upload of several files in one request, with upload progress (0..1). */
export function uploadFiles<T>(path: string, files: File[], onProgress?: (fraction: number) => void): Promise<T> {
  const form = new FormData()
  for (const file of files) form.append('files', file, file.name)

  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', `/api${path}`)
    request.setRequestHeader('Accept', 'application/json')
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total)
    }
    request.onerror = () => reject(new ApiError(0, 'Cannot reach the ClaimAI API'))
    request.onload = () => {
      const isJson = (request.getResponseHeader('content-type') ?? '').includes('application/json')
      let payload: unknown = request.responseText
      if (isJson) {
        try {
          payload = JSON.parse(request.responseText)
        } catch {
          payload = request.responseText
        }
      }
      if (request.status >= 200 && request.status < 300) resolve(payload as T)
      else reject(toApiError(request.status, isJson, payload))
    }
    request.send(form)
  })
}

/** Per-file rejection reasons from a 422 upload response. */
export function fileErrors(error: unknown): FileError[] {
  if (!(error instanceof ApiError)) return []
  const detail = error.detail
  if (detail && typeof detail === 'object' && 'errors' in detail && Array.isArray(detail.errors)) {
    return detail.errors as FileError[]
  }
  return []
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong'
}
