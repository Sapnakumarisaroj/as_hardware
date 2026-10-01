import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { useAuth } from '@/features/auth/context'
import type { ProductSummary } from '@/features/catalog/types'
import { api } from '@/lib/api/client'

/**
 * Search service. Results come from GET /products/?q= (the backend picks the search engine:
 * keyword today, semantic/hybrid in Phase 13), so the UI never changes when search improves.
 */
export interface Suggestions {
  query: string
  /** Each product may carry `match_reason` (why it matches when its name does not say so). */
  products: ProductSummary[]
  categories: { name: string; slug: string; parent_name: string | null }[]
  brands: { name: string; slug: string }[]
}

export interface RecentSearch {
  query: string
  searched_at: string
}

export const searchKeys = {
  suggest: (q: string) => ['search', 'suggest', q] as const,
  recent: ['recent-searches'] as const,
}

export function useDebouncedValue<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

export function useSuggestions(query: string) {
  const q = query.trim()
  return useQuery({
    queryKey: searchKeys.suggest(q.toLowerCase()),
    queryFn: async ({ signal }) => (await api.get<Suggestions>('/search/suggest/', { params: { q }, signal })).data,
    enabled: q.length >= 2,
    staleTime: 60_000,
  })
}

export function useRecentSearches() {
  const { status } = useAuth()
  return useQuery({
    queryKey: searchKeys.recent,
    queryFn: async () => (await api.get<RecentSearch[]>('/search/recent/')).data,
    enabled: status === 'authenticated',
    staleTime: 60_000,
  })
}

export function useRecordSearch() {
  const queryClient = useQueryClient()
  const { status } = useAuth()
  return useMutation({
    mutationFn: async (query: string) => {
      if (status === 'authenticated') await api.post('/search/recent/', { query })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: searchKeys.recent }),
  })
}

export function useClearRecentSearches() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await api.delete('/search/recent/')
    },
    onSuccess: () => queryClient.setQueryData(searchKeys.recent, []),
  })
}
