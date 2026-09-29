import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { cartKeys, type Cart } from '@/features/cart/api'
import type { Paginated } from '@/features/catalog/types'
import { trackingPollMs } from '@/features/delivery/format'
import { api } from '@/lib/api/client'

import type { OrderDetail, OrderSummary, PaymentMethod, ReorderLine, ReturnReason, ReturnRequest } from './types'

export const orderKeys = {
  all: ['orders'] as const,
  list: (page: number) => ['orders', 'list', page] as const,
  detail: (number: string) => ['orders', 'detail', number] as const,
  returns: (page: number) => ['returns', 'list', page] as const,
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

/**
 * `pollMs`: refetch periodically (e.g. while the gateway is still confirming a payment).
 * `'tracking'`: refetch while the order is on its way to the customer, and not otherwise.
 */
export function useOrder(number: string, pollMs: number | false | 'tracking' = false) {
  const { status } = useAuth()
  return useQuery({
    queryKey: orderKeys.detail(number),
    queryFn: async () => (await api.get<OrderDetail>(`/orders/${encodeURIComponent(number)}/`)).data,
    enabled: status === 'authenticated' && Boolean(number),
    refetchInterval: pollMs === 'tracking' ? (query) => trackingPollMs(query.state.data?.status) : pollMs,
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

/** The customer asks for a new delivery code (the old one stops working). */
export function useNewDeliveryCode(number: string) {
  const store = useOrderResult()
  return useMutation({
    mutationFn: async (sequence: number) =>
      (await api.post<OrderDetail>(`/orders/${encodeURIComponent(number)}/shipments/${sequence}/delivery-code/`)).data,
    onSuccess: store,
  })
}

/**
 * Proof-of-delivery photos have no public URL: they are fetched with the session's token and
 * shown from memory. The caller must release the returned object URL when done.
 */
export async function fetchPrivateImage(path: string): Promise<string> {
  const response = await api.get<Blob>(path, { responseType: 'blob' })
  return URL.createObjectURL(response.data)
}

export type MockOutcome = 'success' | 'failed' | 'cancelled' | 'pending'

/** Sends the gateway's result to the backend, which verifies it and decides the order status. */
export function useVerifyPayment() {
  const store = useOrderResult()
  return useMutation({
    mutationFn: async ({ paymentId, payload }: { paymentId: string; payload: Record<string, string | boolean> }) =>
      (await api.post<OrderDetail>(`/payments/${encodeURIComponent(paymentId)}/verify/`, { payload })).data,
    onSuccess: store,
  })
}

/** crypto.randomUUID where available (all modern browsers); a random fallback otherwise. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`
}

// --- Buy again ------------------------------------------------------------------------------

export interface ReorderResult {
  added: ReorderLine[]
  /** Lines added only partly or not at all, with the server's reason. */
  skipped: ReorderLine[]
  cart: Cart
}

/** Adds a past order's items to the cart at today's prices; the server caps by stock and limits. */
export function useReorder(number: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<ReorderResult>(`/orders/${encodeURIComponent(number)}/reorder/`)).data,
    onSuccess: (result) => {
      queryClient.setQueryData(cartKeys.cart, result.cart)
      void queryClient.invalidateQueries({ queryKey: ['checkout'] })
    },
  })
}

// --- Returns --------------------------------------------------------------------------------

export function useReturns(page: number) {
  const { status } = useAuth()
  return useQuery({
    queryKey: orderKeys.returns(page),
    queryFn: async () =>
      (await api.get<Paginated<ReturnRequest>>('/returns/', { params: { page, page_size: ORDERS_PAGE_SIZE } })).data,
    enabled: status === 'authenticated',
    placeholderData: keepPreviousData,
  })
}

export interface CreateReturnInput {
  reason: ReturnReason
  details: string
  items: { order_item_id: number; quantity: number }[]
}

/** The order changes too (status, returnable quantities), so it is refetched after every return action. */
function useReturnResult(orderNumber: string) {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: orderKeys.detail(orderNumber) })
    void queryClient.invalidateQueries({ queryKey: ['orders', 'list'] })
    void queryClient.invalidateQueries({ queryKey: ['returns'] })
  }
}

export function useCreateReturn(orderNumber: string) {
  const refresh = useReturnResult(orderNumber)
  return useMutation({
    mutationFn: async (input: CreateReturnInput) =>
      (await api.post<ReturnRequest>('/returns/', { order_number: orderNumber, ...input })).data,
    onSuccess: refresh,
  })
}

export function useCancelReturn(orderNumber: string) {
  const refresh = useReturnResult(orderNumber)
  return useMutation({
    mutationFn: async (returnNumber: string) =>
      (await api.post<ReturnRequest>(`/returns/${encodeURIComponent(returnNumber)}/cancel/`)).data,
    onSuccess: refresh,
  })
}
