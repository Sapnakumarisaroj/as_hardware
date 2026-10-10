import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { cartKeys, type Cart } from '@/features/cart/api'
import { api } from '@/lib/api/client'

import type { BudgetPlan, BundleDetail, BundleOverride, BundleSummary, Recommendations, SmartCart } from './types'

export const shoppingKeys = {
  product: (id: number, variant: number | null) => ['shopping', 'product', id, variant] as const,
  home: (signedIn: boolean) => ['shopping', 'home', signedIn] as const,
  cart: ['shopping', 'cart'] as const,
  bundles: (product: number | null) => ['shopping', 'bundles', product] as const,
}

/** Product-page groups (needed with this, works with this, frequently bought together, alternatives…). */
export function useProductRecommendations(productId: number, variantId: number | null) {
  return useQuery({
    queryKey: shoppingKeys.product(productId, variantId),
    queryFn: async () =>
      (await api.get<Recommendations>('/shopping/recommendations/', { params: { product: productId, ...(variantId ? { variant: variantId } : {}) } })).data,
    staleTime: 5 * 60_000,
  })
}

/** Home-page groups: personal ones only from the customer's own orders and saved items. */
export function useHomeRecommendations() {
  const { status } = useAuth()
  return useQuery({
    queryKey: shoppingKeys.home(status === 'authenticated'),
    queryFn: async () => (await api.get<Recommendations>('/shopping/recommendations/')).data,
    staleTime: 5 * 60_000,
    enabled: status !== 'loading',
  })
}

/** What's worth knowing about the cart, highest value first. Read-only: actions go through the cart API. */
export function useSmartCart(lines: string, params: { postal_code?: string; budget?: string }) {
  const { status } = useAuth()
  return useQuery({
    queryKey: [...shoppingKeys.cart, lines, params],
    queryFn: async () => (await api.get<SmartCart>('/shopping/cart/', { params })).data,
    enabled: status === 'authenticated' && lines.length > 0,
  })
}

export function useBudgetPlan() {
  return useMutation({
    mutationFn: async (input: { text: string; budget?: string; answers?: Record<string, string | number>; postal_code?: string }) =>
      (await api.post<BudgetPlan>('/shopping/budget/', input)).data,
  })
}

export function useBundles(product: number | null = null) {
  return useQuery({
    queryKey: shoppingKeys.bundles(product),
    queryFn: async () => (await api.get<{ results: BundleSummary[] }>('/shopping/bundles/', { params: product ? { product } : {} })).data.results,
    staleTime: 5 * 60_000,
  })
}

/** A bundle with the customer's edits, priced by the server (tiers, offers, stock, delivery). */
export function useBundlePrice(slug: string, overrides: Record<string, BundleOverride>, postalCode: string) {
  return useQuery({
    queryKey: ['shopping', 'bundle', slug, overrides, postalCode],
    queryFn: async () => (await api.post<BundleDetail>(`/shopping/bundles/${slug}/price/`, { overrides, ...(postalCode ? { postal_code: postalCode } : {}) })).data,
    placeholderData: (previous) => previous,
  })
}

export function useAddBundleToCart() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { slug: string; overrides?: Record<string, BundleOverride>; onlyMissing?: boolean }) =>
      (
        await api.post<{ added_lines: number; added_units: number }>(`/shopping/bundles/${input.slug}/add-to-cart/`, {
          overrides: input.overrides ?? {},
          only_missing: input.onlyMissing ?? false,
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cartKeys.cart })
      void queryClient.invalidateQueries({ queryKey: shoppingKeys.cart })
      void queryClient.invalidateQueries({ queryKey: ['checkout'] })
    },
  })
}

function refreshCart(queryClient: ReturnType<typeof useQueryClient>, cart?: Cart) {
  if (cart) queryClient.setQueryData(cartKeys.cart, cart)
  else void queryClient.invalidateQueries({ queryKey: cartKeys.cart })
  void queryClient.invalidateQueries({ queryKey: shoppingKeys.cart })
  void queryClient.invalidateQueries({ queryKey: ['checkout'] })
}

/** Swap a cart line for another variant at a quantity (a cheaper pack size: 40 singles → 1 box of 50). */
export function useReplaceWithQuantity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { itemId: number; variantId: number; quantity: number }) =>
      (await api.post<Cart>(`/cart/items/${input.itemId}/replace/`, { variant_id: input.variantId, quantity: input.quantity })).data,
    onSuccess: (cart) => refreshCart(queryClient, cart),
  })
}

/** "Complete the set": the missing lines one by one through the cart API (each checked again there). */
export function useAddLines() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (lines: { variant_id: number; quantity: number }[]) => {
      let cart: Cart | undefined
      for (const line of lines) cart = (await api.post<Cart>('/cart/items/', { variant_id: line.variant_id, quantity: line.quantity })).data
      return cart
    },
    onSuccess: (cart) => refreshCart(queryClient, cart),
    onError: () => refreshCart(queryClient),
  })
}

/** Set a cart line's quantity (bulk-tier and quantity suggestions); the cart checks it again. */
export function useSetCartQuantity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { itemId: number; quantity: number }) => (await api.patch<Cart>(`/cart/items/${input.itemId}/`, { quantity: input.quantity })).data,
    onSuccess: (cart) => {
      queryClient.setQueryData(cartKeys.cart, cart)
      void queryClient.invalidateQueries({ queryKey: shoppingKeys.cart })
    },
  })
}
