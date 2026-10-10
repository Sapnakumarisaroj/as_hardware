import { keepPreviousData, useQuery } from '@tanstack/react-query'

import type { NamedRef, StockStatus } from '@/features/catalog/types'
import { api } from '@/lib/api/client'

/** One column of GET /products/compare/ (money is a decimal string; null when the product has no active variant). */
export interface CompareProduct {
  id: number
  name: string
  slug: string
  brand: { name: string; slug: string } | null
  category: { name: string; slug: string }
  department: NamedRef | null
  image: string | null
  image_alt: string
  unit: string
  unit_label: string
  default_variant_id: number | null
  variant_name: string
  price: string | null
  mrp: string | null
  discount_percent: string | null
  stock_status: StockStatus
  rating_avg: string | null
  rating_count: number
}

/** A specification merged across the products: one value per column ("—" when missing). */
export interface CompareRow {
  key: string
  name: string
  values: string[]
  differs: boolean
}

export interface CompareResult {
  products: CompareProduct[]
  specifications: CompareRow[]
  /** Slugs that are no longer on sale (unpublished, inactive or unknown). */
  missing: string[]
  mixed_departments: boolean
  max_products: number
}

export function useCompare(slugs: string[]) {
  const joined = slugs.join(',')
  return useQuery({
    queryKey: ['catalog', 'compare', joined],
    queryFn: async () => (await api.get<CompareResult>('/products/compare/', { params: { slugs: joined } })).data,
    enabled: slugs.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}
