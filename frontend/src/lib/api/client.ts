import axios, { type InternalAxiosRequestConfig } from 'axios'

import { env } from '@/lib/env'

import { toApiError } from './errors'
import { tokenStore } from './tokens'

/** Single Axios instance for the whole app: attaches the JWT and refreshes it once on 401. */
export const api = axios.create({
  baseURL: env.apiBaseUrl,
  timeout: 20_000,
  headers: { Accept: 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = tokenStore.getAccess()
  if (token && !config.headers.Authorization) config.headers.Authorization = `Bearer ${token}`
  return config
})

// One refresh at a time: concurrent 401s wait for the same promise.
let refreshing: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refresh = tokenStore.getRefresh()
  if (!refresh) return null
  try {
    // Plain axios: the refresh call must not go through these interceptors.
    const { data } = await axios.post<{ access: string; refresh?: string }>(
      `${env.apiBaseUrl}/auth/token/refresh/`,
      { refresh },
      { timeout: 20_000 },
    )
    tokenStore.set({ access: data.access, refresh: data.refresh ?? refresh })
    return data.access
  } catch {
    tokenStore.clear() // refresh expired/revoked → signed out
    return null
  }
}

const NO_REFRESH_PATHS = ['/auth/login/', '/auth/register/', '/auth/token/refresh/', '/auth/logout/']

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

api.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401 && error.config) {
      const config = error.config as RetriableConfig
      const skip = NO_REFRESH_PATHS.some((path) => config.url?.endsWith(path))
      if (!config._retried && !skip && tokenStore.hasSession()) {
        config._retried = true
        refreshing ??= refreshAccessToken().finally(() => {
          refreshing = null
        })
        const token = await refreshing
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
          return api(config)
        }
      }
    }
    return Promise.reject(toApiError(error))
  },
)
