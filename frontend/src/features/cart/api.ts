import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { api } from '@/lib/api/client'

/** Server cart. Prices, totals and stock checks all come from the backend. */
export interface CartLine {
  id: number
  variant_id: number
  sku: string
  product_id: number
  product_name: string
  product_slug: string
  variant_name: string
  quantity: number
  /** Per unit at this quantity (bulk tier applied by the server). */
  unit_price: string
  /** The normal price for one unit. */
  base_unit_price?: string
  /** Bulk pricing for this line; null when the item has no bulk prices. */
  bulk?: CartLineBulk | null
  unit_mrp: string
  price_at_add: string
  price_changed: boolean
  line_total: string | null
  line_mrp_total: string | null
  discount_percent: string | null
  available_quantity: number
  in_stock: boolean
  purchasable: boolean
  brand_name: string
  attributes: Record<string, string | number>
  max_order_quantity: number
  image: string | null
}

export interface CartLineBulk {
  applied_min_quantity: number | null
  saving: string
  next_tier: { min_quantity: number; unit_price: string; units_more: number; reachable: boolean } | null
}

export interface CartTotals {
  subtotal: string
  mrp_total: string
  discount_total: string
  delivery_fee: string
  tax_total: string
  grand_total: string
  savings_vs_mrp: string
  /** Automatic offers (no code). discount_total = offer_discount + coupon_discount. */
  offer_discount: string
  coupon_discount: string
  bulk_savings?: string
  /** Delivery is free, and why (`free_delivery_reason`), or how much more would make it free. */
  free_delivery?: boolean
  free_delivery_reason?: string
  amount_to_free_delivery?: string
  free_delivery_threshold?: string | null
  /** Items that count towards that threshold, e.g. "Cement" (empty = everything). */
  free_delivery_hint?: string
  /** Phase 17: shop credit used (already taken off grand_total). */
  credit_discount?: string
}

export interface AppliedOffer {
  id: number
  name: string
  description: string
  badge: string
  discount: string
  variant_ids: number[]
}

export interface MissedOffer {
  id: number
  name: string
  badge: string
  min_order_value: string
  /** How much more to spend on the offer's items to unlock it. */
  shortfall: string
  /** Quantity offers: units still needed on an item ("add 2 more"). */
  units_short?: number
  min_quantity?: number
  benefit?: 'discount' | 'free_delivery'
}

export interface CartOffers {
  applied: AppliedOffer[]
  missed: MissedOffer[]
  /** A free-delivery offer that applies to this cart. */
  free_delivery?: AppliedOffer | null
}

export interface Cart {
  id: number
  items: CartLine[]
  totals: CartTotals
  offers: CartOffers
  issues: string[]
  can_checkout: boolean
}

export const cartKeys = { cart: ['cart'] as const }

export function useCart() {
  const { status } = useAuth()
  return useQuery({
    queryKey: cartKeys.cart,
    queryFn: async () => (await api.get<Cart>('/cart/')).data,
    enabled: status === 'authenticated',
  })
}

/** Number of units in the cart (0 when signed out or not loaded yet). */
export function useCartCount(): number {
  const { data } = useCart()
  return data?.items.reduce((sum, line) => sum + line.quantity, 0) ?? 0
}

function useCartMutation<TVars>(request: (vars: TVars) => Promise<Cart>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: (cart) => {
      queryClient.setQueryData(cartKeys.cart, cart)
      // Any checkout preview is now out of date.
      void queryClient.invalidateQueries({ queryKey: ['checkout'] })
    },
  })
}

export function useAddToCart() {
  return useCartMutation(async (vars: { variantId: number; quantity: number }) => {
    const { data } = await api.post<Cart>('/cart/items/', { variant_id: vars.variantId, quantity: vars.quantity })
    return data
  })
}

export function useUpdateCartItem() {
  return useCartMutation(async (vars: { itemId: number; quantity: number }) => {
    const { data } = await api.patch<Cart>(`/cart/items/${vars.itemId}/`, { quantity: vars.quantity })
    return data
  })
}

export function useRemoveCartItem() {
  return useCartMutation(async (itemId: number) => (await api.delete<Cart>(`/cart/items/${itemId}/`)).data)
}
