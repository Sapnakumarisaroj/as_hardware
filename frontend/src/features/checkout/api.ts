import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import type { Cart, CartOffers, CartTotals } from '@/features/cart/api'
import type { DeliveryQuote } from '@/features/delivery/types'
import type { PaymentMethod } from '@/features/orders/types'
import { api } from '@/lib/api/client'

/** Server-validated checkout state (POST /checkout/preview/). Nothing here is computed in the browser. */
export interface CheckoutPreview {
  cart: Cart
  totals: CartTotals
  address_id: number | null
  coupon: { code: string; description: string; discount: string } | null
  coupon_error: { code: string; message: string; details: Record<string, unknown> } | null
  /** Fulfilment plan for the chosen address: store(s), fast or standard, estimate and fee rule. */
  delivery: DeliveryQuote
  /** Automatic offers applied to (or nearly unlocked by) this checkout. */
  offers: CartOffers
  blocking_issues: { code: string; message: string }[]
  can_place_order: boolean
  payment_methods: PaymentOption[]
  /** Phase 17: shop credit (the server decides how much may be used: its share of the goods). */
  credits?: CheckoutCredits
  /** Cashback this order would earn (pending until delivery and the return window). */
  cashback?: { amount: string; rule: string; summary: string } | null
}

export interface CheckoutCredits {
  enabled: boolean
  available: string
  max_share_percent: string
  /** The most credit this order may use (its share of the goods after offers and coupon). */
  max_usable: string
  usable: string
  use_credits: boolean
  applied: string
  remaining_to_pay: string
}

/** A payment choice and whether this order can use it (cash on delivery has rules, e.g. a maximum). */
export interface PaymentOption {
  value: PaymentMethod
  label: string
  test_mode: boolean
  available?: boolean
  reason_code?: string
  /** Why it can't be used, e.g. "Cash on Delivery isn't available for orders above ₹10,000." */
  message?: string
  max_order_value?: string | null
}

export const checkoutKeys = {
  all: ['checkout'] as const,
  preview: (addressId: number | null, couponCode: string, useCredits = false, quoteId: number | null = null) =>
    ['checkout', 'preview', addressId, couponCode, useCredits, quoteId] as const,
}

/** `quoteId`: check out an accepted B2B quotation (its lines at the quoted prices) instead of the cart. */
export function useCheckoutPreview(addressId: number | null, couponCode: string, useCredits = false, quoteId: number | null = null) {
  const { status } = useAuth()
  return useQuery({
    queryKey: checkoutKeys.preview(addressId, couponCode, useCredits, quoteId),
    queryFn: async () =>
      (
        await api.post<CheckoutPreview>('/checkout/preview/', {
          address_id: addressId,
          coupon_code: couponCode,
          use_credits: useCredits,
          ...(quoteId ? { quote_id: quoteId } : {}),
        })
      ).data,
    enabled: status === 'authenticated',
    placeholderData: keepPreviousData,
    // Prices and stock can change: always re-check when the page is revisited.
    staleTime: 0,
  })
}
