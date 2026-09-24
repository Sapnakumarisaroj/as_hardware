import { isAxiosError } from 'axios'

/** Normalised error matching the backend envelope: {error: {code, message, details}, request_id}. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number | null
  readonly details: Record<string, unknown>
  readonly requestId: string | null

  constructor(opts: {
    message: string
    code: string
    status: number | null
    details?: Record<string, unknown>
    requestId?: string | null
  }) {
    super(opts.message)
    this.name = 'ApiError'
    this.code = opts.code
    this.status = opts.status
    this.details = opts.details ?? {}
    this.requestId = opts.requestId ?? null
  }

  /** Field-level validation messages, e.g. {email: ["Already registered."]} */
  fieldErrors(): Record<string, string[]> {
    if (this.code !== 'validation_error') return {}
    const out: Record<string, string[]> = {}
    for (const [key, value] of Object.entries(this.details)) {
      out[key] = Array.isArray(value) ? value.map(String) : [String(value)]
    }
    return out
  }
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

interface Envelope {
  error?: { code?: string; message?: string; details?: Record<string, unknown> }
  request_id?: string
}

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err
  if (isAxiosError(err)) {
    if (!err.response) {
      return new ApiError({
        message: 'Cannot reach the server. Check your connection and try again.',
        code: 'network_error',
        status: null,
      })
    }
    const body = err.response.data as Envelope | undefined
    return new ApiError({
      message: body?.error?.message ?? 'Something went wrong. Please try again.',
      code: body?.error?.code ?? 'http_error',
      status: err.response.status,
      details: body?.error?.details,
      requestId: body?.request_id ?? (err.response.headers['x-request-id'] as string | undefined) ?? null,
    })
  }
  return new ApiError({
    message: err instanceof Error ? err.message : 'Unexpected error.',
    code: 'unknown',
    status: null,
  })
}
