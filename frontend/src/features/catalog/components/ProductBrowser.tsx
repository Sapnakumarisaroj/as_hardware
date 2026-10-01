import { useState, type ReactNode } from 'react'

import { Drawer } from '@/components/Drawer'
import { EmptyState, ErrorState, GridSkeleton } from '@/components/feedback'
import { CloseIcon, FilterIcon } from '@/components/icons'
import { Pagination } from '@/components/Pagination'
import { formatPrice, pluralize } from '@/lib/format'

import { useProductFacets, useProducts, type ListingParams } from '../api'
import { csv, PAGE_SIZE, SORT_OPTIONS, useListingState, type ListingState } from '../listingState'
import type { ProductFacets } from '../types'
import { FilterPanel } from './FilterPanel'
import { ProductGrid } from './ProductCollections'

interface Props {
  /** Params fixed by the page (e.g. the category slug from the URL path). */
  fixed?: ListingParams
  heading: ReactNode
  categoryLinks?: boolean
  emptyHint?: ReactNode
}

/** Listing with server-side search, filters, sorting and pagination. */
export function ProductBrowser({ fixed = {}, heading, categoryLinks = false, emptyHint }: Props) {
  const state = useListingState(fixed)
  const products = useProducts(state.apiParams)
  const facets = useProductFacets(state.facetParams)
  const [filtersOpen, setFiltersOpen] = useState(false)

  const searching = Boolean(state.filters.q)
  const ordering = state.filters.ordering ?? (searching ? 'relevance' : '')
  const activeCount = countActive(state)
  const total = products.data?.count ?? facets.data?.total

  const panel = facets.data ? (
    <FilterPanel facets={facets.data} state={state} categoryLinks={categoryLinks} />
  ) : facets.isError ? (
    <p className="text-sm text-ink-600">Filters are unavailable right now.</p>
  ) : (
    <p className="text-sm text-ink-600">Loading filters…</p>
  )

  function changePage(page: number) {
    state.setPage(page)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="container-page py-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          {heading}
          <p className="mt-1 text-sm text-ink-600" aria-live="polite">
            {total === undefined ? 'Loading products…' : pluralize(total, 'product')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setFiltersOpen(true)} className="btn-secondary lg:hidden">
            <FilterIcon className="size-4" />
            Filters{activeCount > 0 && ` (${activeCount})`}
          </button>
          <label className="flex items-center gap-2 text-sm">
            <span className="hidden text-ink-600 sm:inline">Sort by</span>
            <select
              value={ordering}
              onChange={(e) => state.setParam('ordering', e.target.value || null)}
              className="input w-auto py-2"
              aria-label="Sort products"
            >
              {SORT_OPTIONS.filter((o) => !o.searchOnly || searching).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {facets.data && <ActiveFilters state={state} facets={facets.data} />}

      <div className="mt-5 grid gap-6 lg:grid-cols-[16rem_1fr]">
        <aside aria-label="Filters" className="hidden lg:block">
          <div className="sticky top-32 max-h-[calc(100vh-9rem)] overflow-y-auto rounded-lg bg-white p-4 ring-1 ring-steel-200">
            {panel}
          </div>
        </aside>

        <div aria-busy={products.isFetching}>
          {products.data?.search?.matched === 'related' && (
            <p className="mb-3 rounded-md bg-amber-100 px-3 py-2 text-sm text-ink-900" role="status">
              We didn’t find those exact words in “{products.data.search.query}”, so we searched for what you probably
              mean
              {products.data.search.related_terms?.length
                ? `: ${products.data.search.related_terms.slice(0, 4).join(', ')}`
                : ''}
              .
            </p>
          )}
          {products.data?.search?.matched === 'some_terms' && (
            <p className="mb-3 rounded-md bg-amber-100 px-3 py-2 text-sm text-ink-900">
              No products match every word in “{products.data.search.query}”. Showing the closest matches instead.
            </p>
          )}
          {products.isPending ? (
            <GridSkeleton />
          ) : products.isError ? (
            <ErrorState error={products.error} onRetry={() => products.refetch()} title="Couldn’t load products" />
          ) : products.data.results.length === 0 ? (
            <EmptyState
              title={searching ? `No results for “${state.filters.q}”` : 'No products found'}
              action={
                activeCount > 0 ? (
                  <button type="button" onClick={state.clearFilters} className="btn-secondary">
                    Clear filters
                  </button>
                ) : undefined
              }
            >
              {activeCount > 0
                ? 'Try removing some filters.'
                : (emptyHint ?? 'Check the spelling or try a more general word, such as “drill” or “pipe”.')}
            </EmptyState>
          ) : (
            <div className={products.isPlaceholderData ? 'opacity-60 transition-opacity' : ''}>
              <ProductGrid products={products.data.results} />
              <Pagination page={state.page} pageSize={PAGE_SIZE} total={products.data.count} onChange={changePage} />
            </div>
          )}
        </div>
      </div>

      <Drawer
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        title="Filters"
        footer={
          <div className="flex gap-2">
            <button type="button" onClick={state.clearFilters} className="btn-secondary flex-1">
              Clear all
            </button>
            <button type="button" onClick={() => setFiltersOpen(false)} className="btn-primary flex-1">
              Show {total === undefined ? '' : pluralize(total, 'result')}
            </button>
          </div>
        }
      >
        {panel}
      </Drawer>
    </div>
  )
}

function countActive({ filters }: ListingState): number {
  return Object.keys(filters).filter((key) => key !== 'q' && key !== 'ordering').length
}

function ActiveFilters({ state, facets }: { state: ListingState; facets: ProductFacets }) {
  const { filters } = state
  const chips: { label: string; remove: () => void }[] = []
  const brandName = (slug: string) => facets.brands.find((b) => b.slug === slug)?.name ?? slug

  if (filters.category) {
    const name = facets.categories.find((c) => c.slug === filters.category)?.name ?? filters.category
    chips.push({ label: name, remove: () => state.setParam('category', null) })
  }
  for (const slug of csv(filters.brand)) {
    chips.push({ label: brandName(slug), remove: () => state.toggleValue('brand', slug) })
  }
  if (filters.min_price || filters.max_price) {
    const label = `${filters.min_price ? formatPrice(filters.min_price) : 'Any'} – ${filters.max_price ? formatPrice(filters.max_price) : 'Any'}`
    chips.push({ label, remove: () => state.setParams({ min_price: null, max_price: null }) })
  }
  if (filters.rating) chips.push({ label: `${filters.rating}★ & above`, remove: () => state.setParam('rating', null) })
  if (filters.discount) chips.push({ label: `${filters.discount}%+ off`, remove: () => state.setParam('discount', null) })
  if (filters.availability) chips.push({ label: 'In stock', remove: () => state.setParam('availability', null) })
  if (filters.fast_delivery) chips.push({ label: 'Fast delivery', remove: () => state.setParam('fast_delivery', null) })
  for (const [key, value] of Object.entries(filters)) {
    if (!key.startsWith('spec_')) continue
    const spec = facets.specifications.find((s) => `spec_${s.key}` === key)
    for (const item of csv(value)) {
      const label = `${spec?.name ?? key.slice(5)}: ${item}${spec?.unit ? ` ${spec.unit}` : ''}`
      chips.push({ label, remove: () => state.toggleValue(key, item) })
    }
  }
  if (!chips.length) return null

  return (
    <div className="mt-4 flex flex-wrap items-center gap-2" aria-label="Active filters">
      {chips.map((chip) => (
        <button
          key={chip.label}
          type="button"
          onClick={chip.remove}
          className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1 text-sm text-ink-900 ring-1 ring-steel-200 hover:ring-amber-500"
          aria-label={`Remove filter ${chip.label}`}
        >
          {chip.label}
          <CloseIcon className="size-3.5" />
        </button>
      ))}
      <button type="button" onClick={state.clearFilters} className="text-sm font-semibold text-amber-600 hover:underline">
        Clear all
      </button>
    </div>
  )
}
