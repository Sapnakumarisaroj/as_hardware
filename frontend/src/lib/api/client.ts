import axios from 'axios'

import { env } from '@/lib/env'

import { toApiError } from './errors'

/**
 * Single Axios instance for the whole app.
 * JWT attach + single-flight refresh interceptors are added in Phase 3 (auth).
 */
export const api = axios.create({
  baseURL: env.apiBaseUrl,
  timeout: 20_000,
  headers: { Accept: 'application/json' },
})

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(toApiError(error)),
)
