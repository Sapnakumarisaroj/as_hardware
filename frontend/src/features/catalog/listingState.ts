import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'

import type { ListingParams } from './api'

/** Listing state lives in the URL, so results are shareable and Back/Forward work. */
export const FILTER_KEYS = [
  'q',
  'category',
  'brand',
  'min_price',
  'max_price',
  'rating',
  'discount',
  'availability',
  'fast_delivery',
] as const
export const PAGE_SIZE = 24

export const SORT_OPTIONS: { value: string; label: string; searchOnly?: boolean }[] = [
  { value: 'relevance', label: 'Relevance', searchOnly: true },
  { value: '', label: 'Featured' },
  { value: 'popular', label: 'Popularity' },
  { value: 'price', label: 'Price: low to high' },
  { value: '-price', label: 'Price: high to low' },
  { value: 'newest', label: 'Newest first' },
  { value: 'rating', label: 'Customer rating' },
  { value: 'discount', label: 'Biggest discount' },
]

function isListingKey(key: string) {
  return (FILTER_KEYS as readonly string[]).includes(key) || key.startsWith('spec_') || key === 'ordering'
}

export function csv(value: string | null | undefined): string[] {
  return (value ?? '').split(',').filter(Boolean)
}

export function useListingState(fixed: ListingParams = {}) {
  const [searchParams, setSearchParams] = useSearchParams()

  const filters = useMemo(() => {
    const out: ListingParams = {}
    searchParams.forEach((value, key) => {
      if (value && isListingKey(key)) out[key] = value
    })
    return out
  }, [searchParams])

  const page = Math.max(1, Number(searchParams.get('page')) || 1)
  const fixedKey = JSON.stringify(fixed)
  const apiParams = useMemo<ListingParams>(
    () => ({ ...filters, ...(JSON.parse(fixedKey) as ListingParams), page: String(page), page_size: String(PAGE_SIZE) }),
    [filters, fixedKey, page],
  )
  const facetParams = useMemo<ListingParams>(() => {
    const rest: ListingParams = { ...filters, ...(JSON.parse(fixedKey) as ListingParams) }
    delete rest.ordering // sorting does not change filter counts
    return rest
  }, [filters, fixedKey])

  const update = useCallback(
    (mutate: (next: URLSearchParams) => void, { keepPage = false } = {}) => {
      setSearchParams((current) => {
        const next = new URLSearchParams(current)
        mutate(next)
        if (!keepPage) next.delete('page')
        return next
      })
    },
    [setSearchParams],
  )

  /** Set several params in one URL update (null/empty removes a param). */
  const setParams = useCallback(
    (entries: Record<string, string | null>) =>
      update((next) => {
        for (const [key, value] of Object.entries(entries)) {
          if (value) next.set(key, value)
          else next.delete(key)
        }
      }),
    [update],
  )

  const setParam = useCallback((key: string, value: string | null) => setParams({ [key]: value }), [setParams])

  const toggleValue = useCallback(
    (key: string, value: string) =>
      update((next) => {
        const values = new Set(csv(next.get(key)))
        if (values.has(value)) values.delete(value)
        else values.add(value)
        if (values.size) next.set(key, [...values].join(','))
        else next.delete(key)
      }),
    [update],
  )

  const clearFilters = useCallback(
    () =>
      update((next) => {
        for (const key of [...next.keys()]) {
          if (isListingKey(key) && key !== 'q' && key !== 'ordering') next.delete(key)
        }
      }),
    [update],
  )

  const setPage = useCallback(
    (value: number) =>
      update(
        (next) => {
          if (value > 1) next.set('page', String(value))
          else next.delete('page')
        },
        { keepPage: true },
      ),
    [update],
  )

  return { filters, apiParams, facetParams, page, setParam, setParams, toggleValue, clearFilters, setPage }
}

export type ListingState = ReturnType<typeof useListingState>
