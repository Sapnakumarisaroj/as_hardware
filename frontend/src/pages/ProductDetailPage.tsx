import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { ErrorState, PageSpinner } from '@/components/feedback'
import { BoltIcon, ClockIcon, StarIcon } from '@/components/icons'
import { QuantityStepper } from '@/components/QuantityStepper'
import { AddToCartButton } from '@/features/cart/AddToCartButton'
import { useProduct, useProductReviews } from '@/features/catalog/api'
import { PriceBlock, Rating, StockLabel } from '@/features/catalog/components/badges'
import { ProductRail } from '@/features/catalog/components/ProductCollections'
import { ProductGallery } from '@/features/catalog/components/ProductGallery'
import { VariantSelector } from '@/features/catalog/components/VariantSelector'
import { ProductOfferCallout } from '@/features/offers/components'
import type { ProductDetail, ProductVariant } from '@/features/catalog/types'
import { variantLabel } from '@/features/catalog/variants'
import { WishlistButton } from '@/features/wishlist/WishlistButton'
import { isNotFound } from '@/lib/api/errors'
import { formatDate, formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

function pickVariant(product: ProductDetail, requested: string | null): ProductVariant | undefined {
  const byId = product.variants.find((v) => String(v.id) === requested)
  return byId ?? product.variants.find((v) => v.is_default) ?? product.variants[0]
}

function DeliveryInfo({ variant }: { variant: ProductVariant }) {
  if (variant.stock_status === 'out_of_stock') {
    return (
      <p className="flex items-start gap-2 text-sm text-ink-800">
        <ClockIcon className="mt-0.5 size-4 shrink-0 text-ink-600" />
        Currently unavailable for delivery. Save it to your wishlist to find it again later.
      </p>
    )
  }
  return (
    <div className="space-y-1.5 text-sm">
      {variant.fast_delivery ? (
        <p className="flex items-start gap-2 font-semibold text-ink-900">
          <BoltIcon className="mt-0.5 size-4 shrink-0 text-amber-600" />
          Fast delivery available from a nearby store
        </p>
      ) : (
        <p className="flex items-start gap-2 text-ink-800">
          <ClockIcon className="mt-0.5 size-4 shrink-0 text-ink-600" />
          Standard delivery from our stores
        </p>
      )}
      <p className="pl-6 text-ink-600">Delivery availability and time are checked after you select your address.</p>
    </div>
  )
}

function SpecTable({ product, variant }: { product: ProductDetail; variant: ProductVariant }) {
  const rows: { label: string; value: string }[] = []
  if (product.variants.length > 1 && variant.name) rows.push({ label: 'Selected option', value: variant.name })
  for (const [key, value] of Object.entries(variant.attributes ?? {})) {
    rows.push({ label: key.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()), value: String(value) })
  }
  for (const spec of product.specifications) {
    rows.push({ label: spec.name, value: spec.unit ? `${spec.value} ${spec.unit}` : spec.value })
  }
  if (variant.weight_grams) rows.push({ label: 'Weight', value: `${variant.weight_grams} g` })
  if (variant.length_mm && variant.width_mm && variant.height_mm) {
    rows.push({ label: 'Dimensions (L × W × H)', value: `${variant.length_mm} × ${variant.width_mm} × ${variant.height_mm} mm` })
  }
  if (product.brand) rows.push({ label: 'Brand', value: product.brand.name })
  rows.push({ label: 'SKU', value: variant.sku })
  if (product.hsn_code) rows.push({ label: 'HSN code', value: product.hsn_code })

  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Specifications of {product.name}</caption>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label} className="border-b border-steel-100 last:border-0">
            <th scope="row" className="w-2/5 py-2 pr-4 text-left font-medium text-ink-600">
              {row.label}
            </th>
            <td className="py-2 text-ink-900">{row.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Reviews({ product }: { product: ProductDetail }) {
  const reviews = useProductReviews(product.slug)
  return (
    <section aria-labelledby="reviews-heading" className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
      <h2 id="reviews-heading" className="text-lg font-bold">
        Ratings & reviews
      </h2>
      <div className="mt-2">
        <Rating average={product.rating_avg} count={product.rating_count} />
      </div>
      {reviews.isPending ? (
        <p className="mt-3 text-sm text-ink-600">Loading reviews…</p>
      ) : reviews.isError ? (
        <p className="mt-3 text-sm text-ink-600">Reviews couldn’t be loaded.</p>
      ) : reviews.data.results.length === 0 ? (
        <p className="mt-3 text-sm text-ink-600">No reviews yet. Customers can review a product after it is delivered.</p>
      ) : (
        <ul className="mt-4 space-y-4">
          {reviews.data.results.map((review) => (
            <li key={review.id} className="border-t border-steel-100 pt-4 first:border-0 first:pt-0">
              <p className="flex items-center gap-2 text-sm">
                <span className="inline-flex items-center gap-0.5 rounded bg-success-600 px-1.5 py-0.5 text-xs font-semibold text-white">
                  {review.rating}
                  <StarIcon className="size-3" />
                </span>
                <span className="font-semibold">{review.title || 'Review'}</span>
              </p>
              {review.body && <p className="mt-1 text-sm text-ink-800">{review.body}</p>}
              <p className="mt-1 text-xs text-ink-600">
                {review.author} · {formatDate(review.created_at)}
                {review.is_verified_purchase && ' · Verified purchase'}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function ProductDetailPage() {
  const { slug = '' } = useParams()
  const product = useProduct(slug)
  const [params, setParams] = useSearchParams()
  const [quantity, setQuantity] = useState(1)

  const data = product.data
  const variant = data ? pickVariant(data, params.get('variant')) : undefined
  usePageMeta(data?.name, data ? data.short_description || `${data.name} — price, specifications and availability.` : undefined)

  if (product.isPending) return <PageSpinner label="Loading product…" />
  if (product.isError || !data || !variant) {
    if (isNotFound(product.error)) return <NotFoundPage />
    return (
      <div className="container-page py-10">
        <ErrorState error={product.error} onRetry={() => product.refetch()} title="Couldn’t load this product" />
      </div>
    )
  }

  const outOfStock = variant.stock_status === 'out_of_stock'
  const maxQuantity = Math.max(1, Math.min(data.max_order_quantity, variant.available_quantity ?? data.max_order_quantity))
  const safeQuantity = Math.min(quantity, maxQuantity)
  const subcategory = data.subcategory ?? data.category
  const selectVariant = (id: number) => {
    setQuantity(1)
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        next.set('variant', String(id))
        return next
      },
      { replace: true, preventScrollReset: true },
    )
  }
  const buyButton = (
    <AddToCartButton
      variantId={variant.id}
      productName={variant.name ? `${data.name} (${variant.name})` : data.name}
      quantity={safeQuantity}
      disabled={outOfStock}
      label={outOfStock ? 'Out of stock' : 'Add to cart'}
      className="btn-primary flex-1 py-3 text-base"
    />
  )

  return (
    <div className="pb-24 lg:pb-0">
      <div className="border-b border-steel-200 bg-white">
        <div className="container-page py-3">
          <Breadcrumbs
            items={[
              { label: data.category.name, to: `/c/${data.category.slug}` },
              ...(data.subcategory ? [{ label: data.subcategory.name, to: `/c/${data.subcategory.slug}` }] : []),
              { label: data.name },
            ]}
          />
        </div>
      </div>

      <div className="container-page grid gap-8 py-6 lg:grid-cols-2">
        <ProductGallery images={data.images} productName={data.name} variantId={variant.id} />

        <div className="space-y-5">
          <div>
            {data.brand && (
              <Link
                to={`/search?brand=${encodeURIComponent(data.brand.slug)}`}
                className="text-sm font-semibold uppercase tracking-wide text-amber-600 hover:underline"
              >
                {data.brand.name}
              </Link>
            )}
            <h1 className="mt-1 text-2xl font-bold leading-tight text-ink-950 sm:text-3xl">{data.name}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-ink-600">
              <Rating average={data.rating_avg} count={data.rating_count} />
              <span>
                SKU: <span className="font-mono text-ink-800">{variant.sku}</span>
              </span>
            </div>
          </div>

          <PriceBlock
            size="lg"
            price={variant.price}
            mrp={variant.mrp}
            discountPercent={variant.discount_percent}
            discountAmount={variant.discount_amount}
          />

          {data.offer && !outOfStock && <ProductOfferCallout offer={data.offer} />}

          <VariantSelector variants={data.variants} selectedId={variant.id} onSelect={selectVariant} />

          <div className="rounded-lg bg-white p-4 ring-1 ring-steel-200">
            <p aria-live="polite">
              <StockLabel status={variant.stock_status} lowQuantity={variant.available_quantity} />
              {data.variants.length > 1 && (
                <span className="ml-2 text-sm text-ink-600">
                  for {variantLabel(variant, data.variants.indexOf(variant))}
                </span>
              )}
            </p>
            <div className="mt-3">
              <DeliveryInfo variant={variant} />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <QuantityStepper value={safeQuantity} max={maxQuantity} onChange={setQuantity} disabled={outOfStock} />
            {/* On small screens the sticky bar at the bottom holds the add-to-cart button. */}
            <div className="hidden flex-1 lg:flex">{buyButton}</div>
            <WishlistButton productId={data.id} productName={data.name} variant="button" />
          </div>
          <p className="text-xs text-ink-600">
            Max {data.max_order_quantity} per order · {data.is_returnable ? 'Returnable' : 'Not returnable'} · Price
            includes {Number(data.gst_rate)}% GST
          </p>

          {data.short_description && <p className="text-ink-800">{data.short_description}</p>}
        </div>
      </div>

      <div className="container-page grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          <section aria-labelledby="specs-heading" className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
            <h2 id="specs-heading" className="mb-2 text-lg font-bold">
              Specifications
            </h2>
            <SpecTable product={data} variant={variant} />
          </section>
          {data.description && (
            <section aria-labelledby="description-heading" className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
              <h2 id="description-heading" className="mb-2 text-lg font-bold">
                Description
              </h2>
              <p className="whitespace-pre-line text-sm leading-relaxed text-ink-800">{data.description}</p>
            </section>
          )}
        </div>
        <Reviews product={data} />
      </div>

      <div className="container-page">
        <ProductRail
          title={`More in ${subcategory.name}`}
          params={{ category: subcategory.slug, exclude: data.slug }}
          viewAllHref={`/c/${subcategory.slug}`}
        />
      </div>

      {/* Mobile sticky purchase bar */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-steel-200 bg-white p-3 shadow-[0_-4px_12px_rgba(0,0,0,0.06)] lg:hidden">
        <div className="flex items-center gap-3">
          <div className="min-w-0">
            <p className="text-lg font-bold leading-tight">{formatPrice(variant.price)}</p>
            <p className="truncate text-xs text-ink-600">{variant.name || data.name}</p>
          </div>
          {buyButton}
        </div>
      </div>
    </div>
  )
}
