import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { describe, expect, it } from 'vitest'

import { ApiError, toApiError } from './errors'

function axiosErrorWith(status: number, data: unknown, headers: Record<string, string> = {}) {
  const response = {
    status,
    data,
    statusText: '',
    headers,
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse
  return new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, response)
}

describe('toApiError', () => {
  it('maps the backend error envelope', () => {
    const err = toApiError(
      axiosErrorWith(400, {
        error: { code: 'validation_error', message: 'Invalid input.', details: { email: ['Required.'] } },
        request_id: 'abc123',
      }),
    )
    expect(err).toBeInstanceOf(ApiError)
    expect(err.code).toBe('validation_error')
    expect(err.status).toBe(400)
    expect(err.requestId).toBe('abc123')
    expect(err.fieldErrors()).toEqual({ email: ['Required.'] })
  })

  it('handles network failures without a response', () => {
    const err = toApiError(new AxiosError('Network Error', 'ERR_NETWORK'))
    expect(err.code).toBe('network_error')
    expect(err.status).toBeNull()
  })

  it('falls back gracefully for non-envelope responses', () => {
    const err = toApiError(axiosErrorWith(502, '<html>Bad gateway</html>', { 'x-request-id': 'rid-1' }))
    expect(err.code).toBe('http_error')
    expect(err.status).toBe(502)
    expect(err.requestId).toBe('rid-1')
  })

  it('wraps plain errors', () => {
    expect(toApiError(new Error('boom')).message).toBe('boom')
  })
})
