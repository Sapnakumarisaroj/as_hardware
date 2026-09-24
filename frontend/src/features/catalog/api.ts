import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api/client'

import type { Brand, Category, Paginated, ProductDetail, ProductFacets, ProductPage, Review } from './types'

/** Query parameters understood by GET /products/ and /products/facets/ (see docs/API.md). */
export type ListingParams = Record<string, string>

export const catalogKeys = {
  categories: ['catalog', 'categories'] as const,
  category: (slug: string) => ['catalog', 'category', slug] as const,
  brands: ['catalog', 'brands'] as const,
  products: (params: ListingParams) => ['catalog', 'products', params] as const,
  facets: (params: ListingParams) => ['catalog', 'facets', params] as const,
  product: (slug: string) => ['catalog', 'product', slug] as const,
  reviews: (slug: string) => ['catalog', 'reviews', slug] as const,
}

const TEN_MINUTES = 10 * 60_000

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

export function useBrands() {
  return useQuery({
    queryKey: catalogKeys.brands,
    queryFn: async () => (await api.get<Brand[]>('/brands/')).data,
    staleTime: TEN_MINUTES,
  })
}

export function useProducts(params: ListingParams, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: catalogKeys.products(params),
    queryFn: async () => (await api.get<ProductPage>('/products/', { params })).data,
    placeholderData: keepPreviousData, // keep the grid visible while the next page/filter loads
    enabled: options.enabled ?? true,
  })
}

export function useProductFacets(params: ListingParams) {
  return useQuery({
    queryKey: catalogKeys.facets(params),
    queryFn: async () => (await api.get<ProductFacets>('/products/facets/', { params })).data,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}

export function useProduct(slug: string) {
  return useQuery({
    queryKey: catalogKeys.product(slug),
    queryFn: async () => (await api.get<ProductDetail>(`/products/${encodeURIComponent(slug)}/`)).data,
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
