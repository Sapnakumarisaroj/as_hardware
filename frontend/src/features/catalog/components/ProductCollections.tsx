import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { CardSkeleton, ErrorState } from '@/components/feedback'
import { ChevronRightIcon } from '@/components/icons'

import { useProducts, type ListingParams } from '../api'
import type { ProductSummary } from '../types'
import { ProductCard } from './ProductCard'

/** How a section sits on the page: plain, a soft amber band, or a dark band (one design system, varied rhythm). */
export type SectionTone = 'plain' | 'tinted' | 'dark'

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

function railId(title: string) {
  return `rail-${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
}

/** Section heading with an optional "View all" link (shared by every product row). */
function RailHeading({
  title,
  subtitle,
  eyebrow,
  viewAllHref,
  icon,
  tone,
}: {
  title: string
  subtitle?: string
  eyebrow?: string
  viewAllHref?: string
  icon?: ReactNode
  tone: SectionTone
}) {
  const dark = tone === 'dark'
  return (
    <div className="mb-4 flex items-end justify-between gap-4 sm:mb-5">
      <div className="min-w-0">
        {eyebrow && <p className={dark ? 'eyebrow text-amber-400' : 'eyebrow'}>{eyebrow}</p>}
        <h2 id={railId(title)} className={`section-title flex items-center gap-2 ${dark ? 'text-white' : ''}`}>
          {icon}
          {title}
        </h2>
        {subtitle && <p className={`mt-1 text-sm ${dark ? 'text-steel-200' : 'text-ink-600'}`}>{subtitle}</p>}
      </div>
      {viewAllHref && (
        <Link
          to={viewAllHref}
          className={`group/all inline-flex shrink-0 items-center gap-1 rounded-full px-3 py-1.5 text-sm font-semibold transition ${
            dark ? 'text-amber-400 ring-1 ring-white/20 hover:bg-white/10' : 'text-amber-700 ring-1 ring-steel-200 hover:bg-white hover:ring-steel-300'
          }`}
        >
          View all
          <span className="sr-only"> {title}</span>
          <ChevronRightIcon className="size-4 transition-transform group-hover/all:translate-x-0.5" />
        </Link>
      )}
    </div>
  )
}

const ROW_ITEM = 'flex shrink-0 snap-start basis-[46%] sm:basis-[31%] lg:basis-[23.5%] xl:basis-[19%]'

function ProductRow({ products, contained }: { products: ProductSummary[]; contained: boolean }) {
  // Plain rows run to the screen edge on scroll; rows inside a band stay inside it.
  const bleed = contained ? '' : '-mx-4 px-4 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8'
  return (
    <ul role="list" className={`scrollbar-none flex snap-x gap-3 overflow-x-auto pb-2 sm:gap-4 ${bleed}`}>
      {products.map((product) => (
        <li key={product.id} className={ROW_ITEM}>
          <div className="w-full">
            <ProductCard product={product} />
          </div>
        </li>
      ))}
    </ul>
  )
}

function Section({ title, tone, children }: { title: string; tone: SectionTone; children: ReactNode }) {
  const shell =
    tone === 'dark'
      ? 'my-6 rounded-3xl bg-ink-900 p-4 sm:p-6 lg:p-8'
      : tone === 'tinted'
        ? 'my-6 rounded-3xl bg-gradient-to-br from-amber-50 via-white to-amber-50/60 p-4 ring-1 ring-amber-100 sm:p-6 lg:p-8'
        : 'py-6 sm:py-8'
  return (
    <section aria-labelledby={railId(title)} className={`animate-rise ${shell}`}>
      {children}
    </section>
  )
}

interface SectionProps {
  title: string
  subtitle?: string
  eyebrow?: string
  viewAllHref?: string
  icon?: ReactNode
  tone?: SectionTone
  /** Show the products as a grid instead of a scrolling row. */
  layout?: 'row' | 'grid'
}

function Products({ products, tone, layout }: { products: ProductSummary[]; tone: SectionTone; layout: 'row' | 'grid' }) {
  return layout === 'grid' ? <ProductGrid products={products} /> : <ProductRow products={products} contained={tone !== 'plain'} />
}

/** A row of products the page already has (a curated list, recently viewed…). Hidden when empty. */
export function ProductStrip({
  products,
  tone = 'plain',
  layout = 'row',
  ...heading
}: SectionProps & { products: ProductSummary[] }) {
  if (!products.length) return null
  return (
    <Section title={heading.title} tone={tone}>
      <RailHeading {...heading} tone={tone} />
      <Products products={products} tone={tone} layout={layout} />
    </Section>
  )
}

/**
 * A homepage/related-products section fed by the listing API. Sections with no matching
 * products are hidden rather than padded with placeholders.
 */
export function ProductRail({
  params,
  enabled = true,
  hideWhenEmpty = true,
  tone = 'plain',
  layout = 'row',
  hideOnError = false,
  limit = 8,
  ...heading
}: SectionProps & { params: ListingParams; enabled?: boolean; hideWhenEmpty?: boolean; hideOnError?: boolean; limit?: number }) {
  const query = useProducts({ page_size: String(limit), ...params }, { enabled })
  if (!enabled) return null
  if (query.isSuccess && query.data.results.length === 0 && hideWhenEmpty) return null
  // The home page leaves a failed section out rather than showing a heading over an error.
  if (query.isError && hideOnError) return null

  return (
    <Section title={heading.title} tone={tone}>
      <RailHeading {...heading} tone={tone} />
      {query.isPending ? (
        <div role="status" aria-label={`Loading ${heading.title}`} className="flex gap-3 overflow-hidden sm:gap-4">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className={ROW_ITEM}>
              <div className="w-full">
                <CardSkeleton />
              </div>
            </div>
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} title={`Couldn’t load ${heading.title.toLowerCase()}`} />
      ) : query.data.results.length === 0 ? (
        <p className={`text-sm ${tone === 'dark' ? 'text-steel-200' : 'text-ink-600'}`}>Nothing here yet.</p>
      ) : (
        <Products products={query.data.results} tone={tone} layout={layout} />
      )}
    </Section>
  )
}
