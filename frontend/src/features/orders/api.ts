import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { cartKeys } from '@/features/cart/api'
import type { Paginated } from '@/features/catalog/types'
import { api } from '@/lib/api/client'

import type { OrderDetail, OrderSummary, PaymentMethod } from './types'

export const orderKeys = {
  all: ['orders'] as const,
  list: (page: number) => ['orders', 'list', page] as const,
  detail: (number: string) => ['orders', 'detail', number] as const,
}

export const ORDERS_PAGE_SIZE = 10

export function useOrders(page: number) {
  const { status } = useAuth()
  return useQuery({
    queryKey: orderKeys.list(page),
    queryFn: async () =>
      (await api.get<Paginated<OrderSummary>>('/orders/', { params: { page, page_size: ORDERS_PAGE_SIZE } })).data,
    enabled: status === 'authenticated',
    placeholderData: keepPreviousData,
  })
}

export function useOrder(number: string) {
  const { status } = useAuth()
  return useQuery({
    queryKey: orderKeys.detail(number),
    queryFn: async () => (await api.get<OrderDetail>(`/orders/${encodeURIComponent(number)}/`)).data,
    enabled: status === 'authenticated' && Boolean(number),
  })
}

/** Store the server's order in the cache and refresh anything that lists orders. */
function useOrderResult() {
  const queryClient = useQueryClient()
  return (order: OrderDetail) => {
    queryClient.setQueryData(orderKeys.detail(order.order_number), order)
    void queryClient.invalidateQueries({ queryKey: ['orders', 'list'] })
  }
}

export interface PlaceOrderInput {
  addressId: number
  paymentMethod: PaymentMethod
  couponCode: string
  customerNote: string
  /** The grand total the customer saw; the server compares it with its own calculation. */
  expectedTotal: string
  /** Same key for every retry of one "Place order" attempt, so a double submit can't create two orders. */
  idempotencyKey: string
}

export function usePlaceOrder() {
  const queryClient = useQueryClient()
  const store = useOrderResult()
  return useMutation({
    mutationFn: async (input: PlaceOrderInput) =>
      (
        await api.post<OrderDetail>(
          '/orders/',
          {
            address_id: input.addressId,
            payment_method: input.paymentMethod,
            coupon_code: input.couponCode,
            customer_note: input.customerNote,
            expected_total: input.expectedTotal,
          },
          { headers: { 'Idempotency-Key': input.idempotencyKey } },
        )
      ).data,
    onSuccess: (order) => {
      store(order)
      void queryClient.invalidateQueries({ queryKey: cartKeys.cart })
    },
  })
}

export function useCancelOrder(number: string) {
  const store = useOrderResult()
  return useMutation({
    mutationFn: async (reason: string) =>
      (await api.post<OrderDetail>(`/orders/${encodeURIComponent(number)}/cancel/`, { reason })).data,
    onSuccess: store,
  })
}

export function useRetryPayment(number: string) {
  const store = useOrderResult()
  return useMutation({
    mutationFn: async () => (await api.post<OrderDetail>(`/orders/${encodeURIComponent(number)}/retry-payment/`)).data,
    onSuccess: store,
  })
}

export type MockOutcome = 'success' | 'failed' | 'cancelled'

/** Sends the gateway's result to the backend, which verifies it and decides the order status. */
export function useVerifyPayment() {
  const store = useOrderResult()
  return useMutation({
    mutationFn: async ({ paymentId, payload }: { paymentId: string; payload: Record<string, string> }) =>
      (await api.post<OrderDetail>(`/payments/${encodeURIComponent(paymentId)}/verify/`, { payload })).data,
    onSuccess: store,
  })
}

/** crypto.randomUUID where available (all modern browsers); a random fallback otherwise. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`
}
