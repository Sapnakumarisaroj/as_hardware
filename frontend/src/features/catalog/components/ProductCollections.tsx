import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { CardSkeleton, ErrorState } from '@/components/feedback'
import { ChevronRightIcon } from '@/components/icons'

import { useProducts, type ListingParams } from '../api'
import type { ProductSummary } from '../types'
import { ProductCard } from './ProductCard'

export function ProductGrid({ products }: { products: ProductSummary[] }) {
  return (
    <ul className="product-grid" role="list">
      {products.map((product) => (
        <li key={product.id} className="flex">
          <div className="w-full">
            <ProductCard product={product} />
          </div>
        </li>
      ))}
    </ul>
  )
}

/**
 * A homepage/related-products section fed by the listing API. Sections with no matching
 * products are hidden rather than padded with placeholders.
 */
export function ProductRail({
  title,
  subtitle,
  params,
  viewAllHref,
  icon,
  enabled = true,
  hideWhenEmpty = true,
}: {
  title: string
  subtitle?: string
  params: ListingParams
  viewAllHref?: string
  icon?: ReactNode
  enabled?: boolean
  hideWhenEmpty?: boolean
}) {
  const query = useProducts({ page_size: '8', ...params }, { enabled })
  if (!enabled) return null
  if (query.isSuccess && query.data.results.length === 0 && hideWhenEmpty) return null
  const headingId = `rail-${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`

  return (
    <section aria-labelledby={headingId} className="py-6">
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h2 id={headingId} className="flex items-center gap-2 text-xl font-bold text-ink-950">
            {icon}
            {title}
          </h2>
          {subtitle && <p className="mt-0.5 text-sm text-ink-600">{subtitle}</p>}
        </div>
        {viewAllHref && (
          <Link
            to={viewAllHref}
            className="inline-flex shrink-0 items-center gap-1 text-sm font-semibold text-amber-600 hover:underline"
          >
            View all
            <span className="sr-only"> {title}</span>
            <ChevronRightIcon className="size-4" />
          </Link>
        )}
      </div>
      {query.isPending ? (
        <div role="status" aria-label={`Loading ${title}`} className="flex gap-3 overflow-hidden">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="w-44 shrink-0 sm:w-56">
              <CardSkeleton />
            </div>
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} title={`Couldn’t load ${title.toLowerCase()}`} />
      ) : query.data.results.length === 0 ? (
        <p className="text-sm text-ink-600">Nothing here yet.</p>
      ) : (
        <ul role="list" className="scrollbar-none -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2 sm:gap-4">
          {query.data.results.map((product) => (
            <li key={product.id} className="flex w-44 shrink-0 snap-start sm:w-56">
              <div className="w-full">
                <ProductCard product={product} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
