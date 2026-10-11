import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { useProduct } from '@/features/admin/api'
import type { AdminProduct, AdminVariant } from '@/features/admin/types'
import { PageHeader, Panel } from '@/features/admin/ui'
import { isNotFound } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from '../NotFoundPage'

/** Staff-only look at a product as customers would see it, built from the dashboard API (never the shop
 * API, which only returns published products). Drafts carry a "DRAFT — NOT FOR SALE" banner, prices that
 * aren't approved are shown only as marked reference figures, and unverified pictures are labelled. There
 * is no add-to-cart: the cart refuses unpublished products and off-sale variants anyway. */
export function AdminProductPreviewPage() {
  const { id } = useParams()
  const query = useProduct(id)
  usePageMeta(query.data ? `Preview: ${query.data.name}` : 'Preview')
  if (query.isPending) return <PageSpinner label="Loading the product…" />
  if (isNotFound(query.error)) return <NotFoundPage />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn’t load the product" />
  return <Preview product={query.data} />
}

function blockers(product: AdminProduct): string[] {
  const reasons: string[] = []
  if (product.state !== 'live') reasons.push('Not published.')
  const unapproved = product.variants.filter((v) => !v.price_approved).length
  if (unapproved) reasons.push(`${unapproved} of ${product.variants.length} options have prices that are not approved.`)
  if (!product.variants.length) reasons.push('No option has a price yet.')
  const unverified = product.images.filter((i) => i.source_type === 'unverified').length
  if (unverified) reasons.push(`${unverified} picture${unverified === 1 ? '' : 's'} with usage rights not confirmed.`)
  if (!product.variants.some((v) => v.stock_available > 0)) reasons.push('No stock entered.')
  return reasons
}

function Preview({ product }: { product: AdminProduct }) {
  const [chosen, setChosen] = useState<number | undefined>(product.variants.find((v) => v.is_default)?.id)
  const variant = product.variants.find((v) => v.id === chosen) ?? product.variants[0]
  const image = product.images.find((i) => i.is_primary) ?? product.images[0]
  const draft = product.state !== 'live'
  const reasons = blockers(product)

  return (
    <>
      <PageHeader
        title={`Preview: ${product.name}`}
        crumbs={[
          { label: 'Products', to: '/admin/products' },
          { label: product.name, to: `/admin/products/${product.id}` },
        ]}
        description="Staff only. Customers can't open this page or buy from it."
      />
      {draft && (
        <div role="alert" className="mb-5 rounded-md border-2 border-danger-600 bg-amber-50 px-4 py-3">
          <p className="text-lg font-bold tracking-wide text-danger-600">DRAFT — NOT FOR SALE</p>
          <ul className="mt-1 list-disc pl-5 text-sm">
            {reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid gap-6 md:grid-cols-2">
        <figure className="relative overflow-hidden rounded-md border border-steel-200 bg-white">
          {image ? (
            <>
              <img src={image.image} alt={image.alt_text || product.name} className={image.source_type === 'unverified' ? 'opacity-60' : ''} />
              {image.source_type === 'unverified' && (
                <figcaption className="absolute inset-x-0 bottom-0 bg-ink-900/80 px-3 py-1.5 text-center text-xs font-semibold text-white">
                  Unverified picture — usage rights not confirmed
                </figcaption>
              )}
            </>
          ) : (
            <p className="p-8 text-center text-sm text-ink-600">No picture</p>
          )}
        </figure>
        <div className="space-y-4">
          <div>
            {product.brand && <p className="text-sm text-ink-600">{product.brand.name}</p>}
            <h2 className="text-xl font-bold">{product.name}</h2>
            {product.short_description && <p className="mt-1 text-sm">{product.short_description}</p>}
          </div>
          {product.variants.length > 1 && (
            <fieldset>
              <legend className="mb-1 text-sm font-semibold">Option</legend>
              <div className="flex flex-wrap gap-2">
                {product.variants.map((v) => (
                  <button
                    key={v.id}
                    type="button"
                    aria-pressed={v.id === variant?.id}
                    onClick={() => setChosen(v.id)}
                    className={`rounded-md border px-3 py-1.5 text-sm ${v.id === variant?.id ? 'border-amber-600 bg-amber-50 font-semibold' : 'border-steel-200'}`}
                  >
                    {v.name || 'Standard'}
                  </button>
                ))}
              </div>
            </fieldset>
          )}
          {variant ? <PriceBox variant={variant} /> : <p className="text-sm text-ink-600">No option has a price yet.</p>}
          <button type="button" className="btn-primary w-full" disabled>
            {draft ? 'Not for sale (draft)' : 'Add to cart in the shop'}
          </button>
        </div>
      </div>
      {(product.description || product.specifications.length > 0) && (
        <div className="mt-6 grid gap-5 md:grid-cols-2">
          {product.description && (
            <Panel title="Description">
              <p className="whitespace-pre-line text-sm">{product.description}</p>
            </Panel>
          )}
          {product.specifications.length > 0 && (
            <Panel title="Specifications">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                {product.specifications.map((spec) => (
                  <div key={spec.name} className="contents">
                    <dt className="text-ink-600">{spec.name}</dt>
                    <dd className="font-medium">{spec.value}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          )}
        </div>
      )}
      <p className="mt-6 text-sm">
        <Link to={`/admin/products/${product.id}`} className="font-semibold text-amber-700 hover:underline">
          Back to editing
        </Link>
      </p>
    </>
  )
}

function PriceBox({ variant }: { variant: AdminVariant }) {
  if (!variant.price_approved) {
    return (
      <div data-testid="unapproved-price" className="rounded-md border border-dashed border-steel-300 px-3 py-2 text-sm">
        <p className="font-semibold text-danger-600">Price not approved — not shown to customers</p>
        <p className="text-ink-600">
          Reference only: {formatPrice(variant.price)} (MRP {formatPrice(variant.mrp)})
          {variant.price_source && <span className="block text-xs">Source: {variant.price_source}</span>}
        </p>
      </div>
    )
  }
  const mrp = Number(variant.mrp)
  const price = Number(variant.price)
  const off = mrp > price ? Math.round(((mrp - price) * 100) / mrp) : 0
  return (
    <p className="text-2xl font-bold tabular-nums">
      {formatPrice(variant.price)}
      {off > 0 && (
        <>
          <span className="ml-2 text-base font-normal text-ink-600 line-through">MRP {formatPrice(variant.mrp)}</span>
          <span className="ml-2 text-base font-semibold text-success-600">{off}% off</span>
        </>
      )}
    </p>
  )
}
