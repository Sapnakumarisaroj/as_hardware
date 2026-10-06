import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { cartKeys, type Cart } from '@/features/cart/api'
import { api } from '@/lib/api/client'

import type { CompatibilityOption, CompatibilityProblem, CompatibilityResult, ProductCompatibility } from './types'

export const compatibilityKeys = {
  product: (id: number, variant: number | null) => ['compatibility', 'product', id, variant] as const,
  cart: ['compatibility', 'cart'] as const,
}

/** Will product A work with product B? Decided on the server from the listings and the shop's links. */
export function useCompatibilityCheck() {
  return useMutation({
    mutationFn: async (input: { product_a: number; variant_a?: number | null; product_b: number; variant_b?: number | null }) =>
      (await api.post<CompatibilityResult>('/compatibility/check/', input)).data,
  })
}

/** Required, compatible, commonly used and alternative products for the product page. */
export function useProductCompatibility(productId: number, variantId: number | null) {
  return useQuery({
    queryKey: compatibilityKeys.product(productId, variantId),
    queryFn: async () =>
      (await api.get<ProductCompatibility>(`/products/${productId}/compatibility/`, { params: variantId ? { variant: variantId } : {} })).data,
    staleTime: 5 * 60_000,
  })
}

/** Lines in the signed-in customer's cart that may not work together (Phase 22 builds the smart cart on this). */
export function useCartCompatibility(lines: string, enabled: boolean) {
  const { status } = useAuth()
  return useQuery({
    queryKey: [...compatibilityKeys.cart, lines], // checked again whenever the cart's lines change
    queryFn: async () => (await api.get<{ problems: CompatibilityProblem[] }>('/cart/compatibility/')).data.problems,
    enabled: status === 'authenticated' && enabled,
  })
}

/** Swap a cart line for a compatible product in one step (checked like any cart line). */
export function useReplaceCartItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { itemId: number; variantId: number }) =>
      (await api.post<Cart>(`/cart/items/${input.itemId}/replace/`, { variant_id: input.variantId })).data,
    onSuccess: (cart) => {
      queryClient.setQueryData(cartKeys.cart, cart)
      void queryClient.invalidateQueries({ queryKey: compatibilityKeys.cart })
      void queryClient.invalidateQueries({ queryKey: ['checkout'] })
    },
  })
}

/** The variant to use for an option: the matching one when the server named it, else the product's default. */
export function optionVariant(option: CompatibilityOption): number | null {
  return option.variant_id ?? option.product?.default_variant_id ?? null
}
