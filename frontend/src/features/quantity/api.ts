import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { cartKeys } from '@/features/cart/api'
import { projectKeys } from '@/features/projects/api'
import { api } from '@/lib/api/client'

import type { QuantityRequest, QuantityResult, QuantityStatus } from './types'

export function useQuantityStatus() {
  return useQuery({
    queryKey: ['quantity', 'status'],
    queryFn: async () => (await api.get<QuantityStatus>('/ai/quantity/')).data,
    staleTime: 60 * 60_000,
  })
}

/** Works out a requirement: questions, assumptions, breakdown and a priced, delivery-checked kit. */
export function useEstimate() {
  return useMutation({
    mutationFn: async (input: QuantityRequest) => (await api.post<QuantityResult>('/ai/quantity/', input)).data,
  })
}

/** The result's lines into the cart, all or nothing (the server checks every line). */
export function useAddQuantityToCart() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (lines: { variant_id: number; quantity: number }[]) =>
      (await api.post<{ added_lines: number; added_units: number }>('/ai/quantity/add-to-cart/', { lines })).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cartKeys.cart })
      void queryClient.invalidateQueries({ queryKey: ['checkout'] })
    },
  })
}

/** Saves the calculation as a project (edited, priced and added to the cart from the project page). */
export function useSaveQuantity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: QuantityRequest) =>
      (await api.post<{ project_id: number; path: string }>('/ai/quantity/save/', input)).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: projectKeys.list }),
  })
}
