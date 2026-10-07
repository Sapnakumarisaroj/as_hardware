import { Link, useParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { EmptyState, ErrorState, PageSpinner } from '@/components/feedback'
import { useBrand, useBrands } from '@/features/catalog/api'
import { ProductBrowser } from '@/features/catalog/components/ProductBrowser'
import type { Brand } from '@/features/catalog/types'
import { isNotFound } from '@/lib/api/errors'
import { pluralize } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

function BrandMark({ brand, size = 'md' }: { brand: Brand; size?: 'md' | 'lg' }) {
  const box = size === 'lg' ? 'size-16 text-2xl' : 'size-12 text-lg'
  if (brand.logo) {
    return <img src={brand.logo} alt="" loading="lazy" className={`${box} rounded-md bg-white object-contain ring-1 ring-steel-200`} />
  }
  return (
    <span aria-hidden className={`${box} grid place-items-center rounded-md bg-ink-900 font-extrabold text-amber-500`}>
      {brand.name.charAt(0).toUpperCase()}
    </span>
  )
}

/** /brands — every brand with products customers can see, A–Z. */
export function BrandsPage() {
  const brands = useBrands()
  usePageMeta('Brands', 'Shop plywood, Fevicol, furniture fittings, locks and tools by brand.')
  const visible = (brands.data ?? []).filter((b) => (b.product_count ?? 0) > 0)
  const groups = new Map<string, Brand[]>()
  for (const brand of visible) {
    const first = brand.name.charAt(0).toUpperCase()
    const letter = /[A-Z]/.test(first) ? first : '#'
    groups.set(letter, [...(groups.get(letter) ?? []), brand])
  }

  return (
    <div className="container-page py-6">
      <Breadcrumbs items={[{ label: 'Brands' }]} />
      <h1 className="mt-3 text-2xl font-bold text-ink-950">Brands</h1>
      {brands.isPending ? (
        <PageSpinner label="Loading brands…" />
      ) : brands.isError ? (
        <ErrorState error={brands.error} onRetry={() => brands.refetch()} title="Couldn’t load brands" />
      ) : visible.length === 0 ? (
        <EmptyState title="No brands yet">Brands appear here once their products are on sale.</EmptyState>
      ) : (
        <>
          <p className="mt-1 text-sm text-ink-600">{pluralize(visible.length, 'brand')}</p>
          {[...groups.entries()].map(([letter, items]) => (
            <section key={letter} aria-labelledby={`brands-${letter}`} className="mt-6">
              <h2 id={`brands-${letter}`} className="mb-2 text-sm font-bold uppercase tracking-wide text-ink-600">
                {letter}
              </h2>
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((brand) => (
                  <li key={brand.id}>
                    <Link
                      to={`/brand/${brand.slug}`}
                      className="flex items-center gap-3 rounded-lg bg-white p-3 ring-1 ring-steel-200 hover:ring-amber-500 focus-visible:ring-amber-500"
                    >
                      <BrandMark brand={brand} />
                      <span>
                        <span className="block font-semibold text-ink-950">{brand.name}</span>
                        <span className="text-xs text-ink-600">{pluralize(brand.product_count ?? 0, 'product')}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </div>
  )
}

/** /brand/:slug — the brand's products with the usual filters (categories, options, price…). */
export function BrandPage() {
  const { slug = '' } = useParams()
  const brand = useBrand(slug)
  const data = brand.data
  usePageMeta(
    data ? `${data.name} products` : null,
    data ? data.description || `Buy ${data.name} products: prices, specifications and stock.` : undefined,
  )

  if (brand.isPending) return <PageSpinner label="Loading brand…" />
  if (brand.isError || !data) {
    if (isNotFound(brand.error)) return <NotFoundPage />
    return (
      <div className="container-page py-10">
        <ErrorState error={brand.error} onRetry={() => brand.refetch()} title="Couldn’t load this brand" />
      </div>
    )
  }

  return (
    <>
      <div className="border-b border-steel-200 bg-white">
        <div className="container-page py-4">
          <Breadcrumbs items={[{ label: 'Brands', to: '/brands' }, { label: data.name }]} />
          <div className="mt-3 flex items-start gap-4">
            <BrandMark brand={data} size="lg" />
            <div>
              {data.description && <p className="max-w-2xl text-sm text-ink-800">{data.description}</p>}
            </div>
          </div>
        </div>
      </div>
      <ProductBrowser
        key={slug}
        fixed={{ brand: slug }}
        heading={<h1 className="text-2xl font-bold text-ink-950">{data.name}</h1>}
        emptyHint="No products of this brand are on sale right now."
      />
    </>
  )
}
