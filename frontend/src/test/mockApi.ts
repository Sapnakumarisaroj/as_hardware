import { vi } from 'vitest'

import { api } from '@/lib/api/client'
import { ApiError } from '@/lib/api/errors'

type Method = 'get' | 'post' | 'patch' | 'delete'

export interface RequestInfo {
  url: string
  params: Record<string, string>
  body: unknown
}

/** A fixed response, an Error to reject with, or a function of the request (may return a Promise). */
type Reply = unknown | ((request: RequestInfo) => unknown)

export type Routes = Partial<Record<Method, Record<string, Reply>>>

export function httpError(status: number, message = 'Request failed.', code = 'http_error') {
  return new ApiError({ message, code, status })
}

/**
 * Replaces the shared Axios instance's methods with an in-memory route table keyed by URL
 * (e.g. '/products/'). Unknown routes reject with a 404 so a missing mock is obvious.
 * Returns the spies so tests can assert on the exact params/bodies sent to the backend.
 */
export function mockApi(routes: Routes) {
  function handler(method: Method) {
    return async (url: string, first?: unknown, second?: unknown) => {
      const hasBody = method === 'post' || method === 'patch'
      const config = (hasBody ? second : first) as { params?: Record<string, string> } | undefined
      const request: RequestInfo = { url, params: config?.params ?? {}, body: hasBody ? first : undefined }
      const table = routes[method] ?? {}
      if (!(url in table)) throw httpError(404, `No mock for ${method.toUpperCase()} ${url}`, 'not_found')
      const entry = table[url]
      const reply = await (typeof entry === 'function' ? (entry as (r: RequestInfo) => unknown)(request) : entry)
      if (reply instanceof Error) throw reply
      return { data: reply, status: 200 }
    }
  }
  return {
    get: vi.spyOn(api, 'get').mockImplementation(handler('get') as typeof api.get),
    post: vi.spyOn(api, 'post').mockImplementation(handler('post') as typeof api.post),
    patch: vi.spyOn(api, 'patch').mockImplementation(handler('patch') as typeof api.patch),
    delete: vi.spyOn(api, 'delete').mockImplementation(handler('delete') as typeof api.delete),
  }
}

/** Params of every GET made to `url`, in call order. */
export function paramsSent(spy: ReturnType<typeof mockApi>['get'], url: string): Record<string, string>[] {
  return spy.mock.calls
    .filter(([calledUrl]) => calledUrl === url)
    .map(([, config]) => ((config as { params?: Record<string, string> } | undefined)?.params ?? {}))
}
