/** Minimal client for the ClaimAI API (served under /api, proxied by Vite in development). */

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

  const isJson = response.headers.get('content-type')?.includes('application/json')
  const payload: unknown = isJson ? await response.json() : await response.text()

  if (!response.ok) {
    if (!isJson && [502, 503, 504].includes(response.status)) {
      // The dev proxy answers with a bare gateway error when the API process is down.
      throw new ApiError(response.status, 'Cannot reach the ClaimAI API', payload)
    }
    const detail = isJson && payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : payload
    const message = typeof detail === 'string' && detail ? detail : `Request failed (${response.status})`
    throw new ApiError(response.status, message, detail)
  }
  return payload as T
}
