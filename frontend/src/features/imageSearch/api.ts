import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import type { Paginated } from '@/features/catalog/types'
import { api } from '@/lib/api/client'

import type { ImageSearchHistoryRow, ImageSearchResult, ImageSearchStatus } from './types'

export const imageSearchKeys = {
  status: ['image-search', 'status'] as const,
  history: ['image-search', 'history'] as const,
  one: (id: number) => ['image-search', 'one', id] as const,
}

export function useImageSearchStatus() {
  return useQuery({
    queryKey: imageSearchKeys.status,
    queryFn: async () => (await api.get<ImageSearchStatus>('/ai/image-search/')).data,
    staleTime: 10 * 60_000,
  })
}

/** Sends the photo; the answer names the item and lists real catalogue products. */
export function useImageSearch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('image', file)
      return (await api.post<ImageSearchResult>('/ai/image-search/', form)).data
    },
    onSuccess: (result) => {
      if (result.id !== null) {
        queryClient.setQueryData(imageSearchKeys.one(result.id), result)
        void queryClient.invalidateQueries({ queryKey: imageSearchKeys.history })
      }
    },
  })
}

export function useImageSearchHistory() {
  const { status } = useAuth()
  return useQuery({
    queryKey: imageSearchKeys.history,
    queryFn: async () =>
      (await api.get<Paginated<ImageSearchHistoryRow>>('/ai/image-searches/', { params: { page_size: 10 } })).data,
    enabled: status === 'authenticated',
  })
}

export function useSavedImageSearch(id: number | null) {
  const { status } = useAuth()
  return useQuery({
    queryKey: imageSearchKeys.one(id ?? 0),
    queryFn: async () => (await api.get<ImageSearchResult>(`/ai/image-searches/${id}/`)).data,
    enabled: status === 'authenticated' && id !== null,
  })
}

export function useDeleteImageSearch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number | 'all') =>
      id === 'all' ? api.post('/ai/image-searches/clear/', {}) : api.delete(`/ai/image-searches/${id}/`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: imageSearchKeys.history }),
  })
}
