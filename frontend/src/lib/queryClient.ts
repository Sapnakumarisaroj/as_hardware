import { QueryClient } from '@tanstack/react-query'

import { ApiError } from './api/errors'

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Don't retry client errors (4xx); retry transient failures twice.
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status !== null && error.status < 500) return false
          return failureCount < 2
        },
      },
      mutations: { retry: false },
    },
  })
}
