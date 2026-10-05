import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { isValidPincode, usePincode } from '@/features/delivery/location'
import { api } from '@/lib/api/client'

import type {
  Brand,
  Category,
  Collection,
  Paginated,
  PriceQuote,
  ProductDetail,
  ProductFacets,
  ProductPage,
  Review,
} from './types'

/** Query parameters understood by GET /products/ and /products/facets/ (see docs/API.md). */
export type ListingParams = Record<string, string>

export const catalogKeys = {
  categories: ['catalog', 'categories'] as const,
  category: (slug: string) => ['catalog', 'category', slug] as const,
  brands: ['catalog', 'brands'] as const,
  brand: (slug: string) => ['catalog', 'brand', slug] as const,
  products: (params: ListingParams) => ['catalog', 'products', params] as const,
  facets: (params: ListingParams) => ['catalog', 'facets', params] as const,
  product: (slug: string, pin = '') => ['catalog', 'product', slug, pin] as const,
  reviews: (slug: string) => ['catalog', 'reviews', slug] as const,
  quote: (slug: string, variantId: number, quantity: number, pin = '') =>
    ['catalog', 'quote', slug, variantId, quantity, pin] as const,
  collections: ['catalog', 'collections'] as const,
}

const TEN_MINUTES = 10 * 60_000

/**
 * The shopper's delivery PIN as a query parameter (Phase 16): listings and product pages then say
 * whether a store serving that PIN has the item and whether it can come fast. Without a valid PIN
 * nothing is added and no fast-delivery badge is shown.
 */
export function usePinParams(): ListingParams {
  const pincode = usePincode()
  return isValidPincode(pincode) ? { postal_code: pincode } : {}
}

export function useCategories() {
  return useQuery({
    queryKey: catalogKeys.categories,
    queryFn: async () => (await api.get<Category[]>('/categories/')).data,
    staleTime: TEN_MINUTES,
  })
}

export function useCategory(slug: string) {
  return useQuery({
    queryKey: catalogKeys.category(slug),
    queryFn: async () => (await api.get<Category>(`/categories/${encodeURIComponent(slug)}/`)).data,
    staleTime: TEN_MINUTES,
  })
}

export function useBrand(slug: string) {
  return useQuery({
    queryKey: catalogKeys.brand(slug),
    queryFn: async () => (await api.get<Brand>(`/brands/${encodeURIComponent(slug)}/`)).data,
    staleTime: TEN_MINUTES,
  })
}

export function useBrands() {
  return useQuery({
    queryKey: catalogKeys.brands,
    queryFn: async () => (await api.get<Brand[]>('/brands/')).data,
    staleTime: TEN_MINUTES,
  })
}

export function useProducts(params: ListingParams, options: { enabled?: boolean } = {}) {
  const withPin = { ...usePinParams(), ...params }
  return useQuery({
    queryKey: catalogKeys.products(withPin),
    queryFn: async () => (await api.get<ProductPage>('/products/', { params: withPin })).data,
    placeholderData: keepPreviousData, // keep the grid visible while the next page/filter loads
    enabled: options.enabled ?? true,
  })
}

export function useProductFacets(params: ListingParams) {
  const withPin = { ...usePinParams(), ...params }
  return useQuery({
    queryKey: catalogKeys.facets(withPin),
    queryFn: async () => (await api.get<ProductFacets>('/products/facets/', { params: withPin })).data,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}

export function useProduct(slug: string) {
  const pin = usePinParams()
  return useQuery({
    queryKey: catalogKeys.product(slug, pin.postal_code ?? ''),
    queryFn: async () => (await api.get<ProductDetail>(`/products/${encodeURIComponent(slug)}/`, { params: pin })).data,
    placeholderData: keepPreviousData, // a PIN change keeps the page while the delivery flags reload
  })
}

export function useProductReviews(slug: string) {
  return useQuery({
    queryKey: catalogKeys.reviews(slug),
    queryFn: async () =>
      (await api.get<Paginated<Review>>(`/products/${encodeURIComponent(slug)}/reviews/`, { params: { page_size: 5 } }))
        .data,
    staleTime: 5 * 60_000,
  })
}

/** Server price for a variant and quantity (bulk tier + live offers). A preview: the cart prices again. */
export function useProductQuote(slug: string, variantId: number, quantity: number, enabled = true) {
  const pin = usePinParams()
  return useQuery({
    queryKey: catalogKeys.quote(slug, variantId, quantity, pin.postal_code ?? ''),
    queryFn: async () =>
      (
        await api.get<PriceQuote>(`/products/${encodeURIComponent(slug)}/quote/`, {
          params: { variant: variantId, quantity, ...pin },
        })
      ).data,
    enabled: enabled && quantity >= 1,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

/** Live curated lists with products (empty or out-of-date lists are never returned). */
export function useCollections() {
  const pin = usePinParams()
  return useQuery({
    queryKey: [...catalogKeys.collections, pin.postal_code ?? ''],
    queryFn: async () => (await api.get<Collection[]>('/collections/', { params: pin })).data,
    staleTime: 5 * 60_000,
  })
}
