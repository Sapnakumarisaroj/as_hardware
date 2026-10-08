import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { api } from '@/lib/api/client'

import { isValidPincode } from './location'
import type { DeliveryQuote, Serviceability } from './types'

/** Where to deliver: a saved address (signed-in customers) or a PIN code. */
export type DeliveryTarget = { addressId: number } | { pincode: string } | null

function targetParams(target: DeliveryTarget): Record<string, string | number> | null {
  if (!target) return null
  if ('addressId' in target) return { address_id: target.addressId }
  return isValidPincode(target.pincode) ? { postal_code: target.pincode } : null
}

// Estimates depend on riders and workload right now: keep them fresh, never retry in a loop.
const LIVE = { staleTime: 60_000, retry: false } as const

/** The shop-wide fast-delivery limit for the header badge; whether an order is fast is decided per PIN and cart. */
export function useDeliveryPromise() {
  return useQuery({
    queryKey: ['delivery', 'promise'],
    queryFn: async () => (await api.get<{ fast_delivery_max_minutes: number }>('/delivery/promise/')).data,
    staleTime: 60 * 60 * 1000,
    retry: false,
  })
}

export function useServiceability(pincode: string) {
  return useQuery({
    queryKey: ['delivery', 'check', pincode],
    queryFn: async () => (await api.get<Serviceability>('/delivery/check/', { params: { postal_code: pincode } })).data,
    enabled: isValidPincode(pincode),
    ...LIVE,
  })
}

export function useProductEstimate(variantId: number, quantity: number, pincode: string, enabled = true) {
  return useQuery({
    queryKey: ['delivery', 'estimate', variantId, quantity, pincode],
    queryFn: async () =>
      (
        await api.get<DeliveryQuote>('/delivery/estimate/', {
          params: { variant_id: variantId, quantity, postal_code: pincode },
        })
      ).data,
    enabled: enabled && isValidPincode(pincode),
    placeholderData: keepPreviousData,
    ...LIVE,
  })
}

/** `cartVersion` changes whenever the cart does, so the estimate is recalculated. */
export function useCartEstimate(target: DeliveryTarget, cartVersion: string) {
  const { status } = useAuth()
  const params = targetParams(target)
  return useQuery({
    queryKey: ['delivery', 'cart-estimate', params, cartVersion],
    queryFn: async () => (await api.get<DeliveryQuote>('/delivery/cart-estimate/', { params: params ?? {} })).data,
    enabled: status === 'authenticated' && params !== null,
    placeholderData: keepPreviousData,
    ...LIVE,
  })
}
