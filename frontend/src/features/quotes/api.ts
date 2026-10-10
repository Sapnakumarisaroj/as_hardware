import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useIsStaff } from '@/features/admin/api'
import { useAuth } from '@/features/auth/context'
import type { Paginated } from '@/features/catalog/types'
import { api } from '@/lib/api/client'
import { ApiError } from '@/lib/api/errors'

/**
 * Bulk quote requests (RFQ). The customer asks, the shop prices every line (never above MRP) and
 * sets a validity date, the customer accepts and checks out through the normal checkout. The
 * browser never calculates a price: line totals here are the server's, and checkout re-prices.
 */
export type QuoteStatus = 'requested' | 'quoted' | 'accepted' | 'ordered' | 'cancelled' | 'declined' | 'rejected' | 'expired'

export interface QuoteItem {
  id: number
  variant_id: number
  sku: string
  product_name: string
  product_slug: string
  variant_name: string
  unit: string
  quantity: number
  customer_note: string
  unit_mrp: string
  /** Catalogue price for this quantity (bulk tier applied) when the request was made. */
  list_unit_price: string
  list_line_total: string
  quoted_unit_price: string | null
  quoted_line_total: string | null
}

export interface Quote {
  id: number
  number: string
  status: QuoteStatus
  status_label: string
  customer_note: string
  address: number | null
  buyer_type: string
  business_name: string
  gstin: string
  shop_note: string
  valid_until: string | null
  quoted_at: string | null
  accepted_at: string | null
  closed_reason: string
  order_number: string | null
  items: QuoteItem[]
  list_goods_total: string
  quoted_goods_total: string | null
  can_accept: boolean
  can_checkout: boolean
  can_close: boolean
  created_at: string
  updated_at: string
}

export interface AdminQuote extends Quote {
  customer_name: string
  customer_email: string
  customer_phone: string
}

export interface RequestQuoteInput {
  items?: { variant_id: number; quantity: number; note?: string }[]
  from_cart?: boolean
  note?: string
  address_id?: number | null
}

export const QUOTES_PAGE_SIZE = 10

export const quoteKeys = {
  all: ['quotes'] as const,
  list: (page: number) => ['quotes', 'list', page] as const,
  detail: (id: number | string) => ['quotes', 'detail', String(id)] as const,
}

export function useQuotes(page: number) {
  const { status } = useAuth()
  return useQuery({
    queryKey: quoteKeys.list(page),
    queryFn: async () =>
      (await api.get<Paginated<Quote>>('/quotes/', { params: { page, page_size: QUOTES_PAGE_SIZE } })).data,
    enabled: status === 'authenticated',
    placeholderData: keepPreviousData,
  })
}

export function useQuote(id: string | number | undefined) {
  const { status } = useAuth()
  return useQuery({
    queryKey: quoteKeys.detail(id ?? ''),
    queryFn: async () => (await api.get<Quote>(`/quotes/${id}/`)).data,
    enabled: status === 'authenticated' && Boolean(id),
  })
}

function useQuoteResult() {
  const queryClient = useQueryClient()
  return (quote: Quote) => {
    queryClient.setQueryData(quoteKeys.detail(quote.id), quote)
    void queryClient.invalidateQueries({ queryKey: ['quotes', 'list'] })
  }
}

export function useRequestQuote() {
  const store = useQuoteResult()
  return useMutation({
    mutationFn: async (input: RequestQuoteInput) => (await api.post<Quote>('/quotes/', input)).data,
    onSuccess: store,
  })
}

export function useAcceptQuote(id: number) {
  const store = useQuoteResult()
  return useMutation({
    mutationFn: async () => (await api.post<Quote>(`/quotes/${id}/accept/`)).data,
    onSuccess: store,
  })
}

export function useCloseQuote(id: number) {
  const store = useQuoteResult()
  return useMutation({
    mutationFn: async (reason: string) => (await api.post<Quote>(`/quotes/${id}/close/`, { reason })).data,
    onSuccess: store,
  })
}

// --- Staff -----------------------------------------------------------------------------------

export const ADMIN_QUOTES_PAGE_SIZE = 20

export function useAdminQuotes(filters: { page: number; status?: string; q?: string }) {
  const staff = useIsStaff()
  const params: Record<string, string | number> = { page: filters.page, page_size: ADMIN_QUOTES_PAGE_SIZE }
  if (filters.status) params.status = filters.status
  if (filters.q) params.q = filters.q
  return useQuery({
    queryKey: ['admin', 'quotes', 'list', params],
    queryFn: async () => (await api.get<Paginated<AdminQuote>>('/admin/quotes/', { params })).data,
    enabled: staff,
    placeholderData: keepPreviousData,
  })
}

export function useAdminQuote(id: string | undefined) {
  const staff = useIsStaff()
  return useQuery({
    queryKey: ['admin', 'quotes', 'one', String(id)],
    queryFn: async () => (await api.get<AdminQuote>(`/admin/quotes/${id}/`)).data,
    enabled: staff && Boolean(id),
  })
}

function useAdminQuoteChange<TInput>(run: (input: TInput) => Promise<AdminQuote>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'quotes'] }),
  })
}

export interface QuotationInput {
  lines: { item_id: number; unit_price: string }[]
  valid_days: number
  shop_note: string
}

export function useSendQuotation(id: number) {
  return useAdminQuoteChange(
    async (input: QuotationInput) => (await api.post<AdminQuote>(`/admin/quotes/${id}/quotation/`, input)).data,
  )
}

export function useRejectQuote(id: number) {
  return useAdminQuoteChange(
    async (reason: string) => (await api.post<AdminQuote>(`/admin/quotes/${id}/reject/`, { reason })).data,
  )
}

export function quoteErrorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}
