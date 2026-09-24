import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import type { Cart, CartOffers, CartTotals } from '@/features/cart/api'
import type { PaymentMethod } from '@/features/orders/types'
import { api } from '@/lib/api/client'

/** Server-validated checkout state (POST /checkout/preview/). Nothing here is computed in the browser. */
export interface CheckoutPreview {
  cart: Cart
  totals: CartTotals
  address_id: number | null
  coupon: { code: string; description: string; discount: string } | null
  coupon_error: { code: string; message: string; details: Record<string, unknown> } | null
  delivery: {
    available: boolean
    fee: string
    free_delivery_min_order: string
    amount_to_free_delivery: string
    fast_delivery_possible: boolean
    eta_minutes: number | null
    message: string
  }
  /** Automatic offers applied to (or nearly unlocked by) this checkout. */
  offers: CartOffers
  blocking_issues: { code: string; message: string }[]
  can_place_order: boolean
  payment_methods: { value: PaymentMethod; label: string; test_mode: boolean }[]
}

export const checkoutKeys = {
  all: ['checkout'] as const,
  preview: (addressId: number | null, couponCode: string) => ['checkout', 'preview', addressId, couponCode] as const,
}

export function useCheckoutPreview(addressId: number | null, couponCode: string) {
  const { status } = useAuth()
  return useQuery({
    queryKey: checkoutKeys.preview(addressId, couponCode),
    queryFn: async () =>
      (await api.post<CheckoutPreview>('/checkout/preview/', { address_id: addressId, coupon_code: couponCode })).data,
    enabled: status === 'authenticated',
    placeholderData: keepPreviousData,
    // Prices and stock can change: always re-check when the page is revisited.
    staleTime: 0,
  })
}
