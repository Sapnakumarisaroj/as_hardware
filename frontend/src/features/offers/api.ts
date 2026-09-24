import { useQuery } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { api } from '@/lib/api/client'

export interface LiveOffer {
  id: number
  name: string
  description: string
  badge: string
  min_order_value: string
  ends_at: string | null
  applies_to_everything: boolean
  categories: { name: string; slug: string }[]
  products: { name: string; slug: string }[]
}

export interface AvailableCoupon {
  code: string
  description: string
  badge: string
  min_order_value: string
  ends_at: string | null
  /** Would apply to the current cart right now (checked by the server). */
  applicable: boolean
  discount: string | null
  /** Why it doesn't apply yet, e.g. "Add ₹120.00 more…". */
  message: string
}

export const offerKeys = {
  live: ['offers', 'live'] as const,
  availableCoupons: ['checkout', 'available-coupons'] as const,
}

export function useLiveOffers() {
  return useQuery({
    queryKey: offerKeys.live,
    queryFn: async () => (await api.get<LiveOffer[]>('/offers/')).data,
    staleTime: 5 * 60_000,
  })
}

/** Advertised coupons for the signed-in customer, evaluated against their cart (refetched with checkout). */
export function useAvailableCoupons() {
  const { status } = useAuth()
  return useQuery({
    queryKey: offerKeys.availableCoupons,
    queryFn: async () => (await api.get<AvailableCoupon[]>('/coupons/available/')).data,
    enabled: status === 'authenticated',
  })
}
