import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { ErrorState, PageSpinner } from '@/components/feedback'
import { ChevronDownIcon, ClockIcon, ReceiptIcon, ReturnIcon, StarIcon, TruckIcon } from '@/components/icons'
import { QuantityStepper } from '@/components/QuantityStepper'
import { AddToCartButton } from '@/features/cart/AddToCartButton'
import { useProduct, useProductReviews } from '@/features/catalog/api'
import { FastDeliveryBadge, PriceBlock, Rating, StockLabel } from '@/features/catalog/components/badges'
import { BulkPriceTable, PaymentOptionsNote, QuantityPriceQuote } from '@/features/catalog/components/BulkPricing'
import { OptionPicker } from '@/features/catalog/components/OptionPicker'
import { ProductCard } from '@/features/catalog/components/ProductCard'
import { ProductRail } from '@/features/catalog/components/ProductCollections'
import { ProductGallery } from '@/features/catalog/components/ProductGallery'
import { VariantSelector } from '@/features/catalog/components/VariantSelector'
import { recordView } from '@/features/catalog/recentlyViewed'
import type { ProductDetail, ProductVariant } from '@/features/catalog/types'
import { variantLabel } from '@/features/catalog/variants'
import { CompareButton } from '@/features/compare/CompareButton'
import { useProductEstimate } from '@/features/delivery/api'
import { DeliveryEstimate, FreeDeliveryNote, PincodeForm } from '@/features/delivery/components'
import { savePincode, usePincode } from '@/features/delivery/location'
import { ProductOfferCallout } from '@/features/offers/components'
import { WishlistButton } from '@/features/wishlist/WishlistButton'
import { isNotFound } from '@/lib/api/errors'
import { formatDate, formatPrice } from '@/lib/format'
import { AccessoryGroups, CompatibilityChecker } from '@/features/compatibility/ProductCompatibility'
import { ProductRecommendations } from '@/features/shopping/ProductRecommendations'
import { ProductEnquiry } from '@/features/support/ProductEnquiry'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

function pickVariant(product: ProductDetail, requested: string | null): ProductVariant | undefined {
  const byId = product.variants.find((v) => String(v.id) === requested)
  return byId ?? product.variants.find((v) => v.is_default) ?? product.variants[0]
}

/**
 * Delivery for the shopper's PIN, from the Phase 9 engine: fast (with the calculated minutes) or the
 * standard window, why fast isn't offered, the fee and the free-delivery gap. Nothing is promised
 * without a PIN — the shopper is asked for one.
 */
function DeliveryInfo({ product, variant, quantity }: { product: ProductDetail; variant: ProductVariant; quantity: number }) {
  const pincode = usePincode()
  const outOfStock = variant.stock_status === 'out_of_stock'
  const estimate = useProductEstimate(variant.id, quantity, pincode, !outOfStock)
  if (outOfStock) {
    return (
      <p className="flex items-start gap-2 text-sm text-ink-800">
        <ClockIcon className="mt-0.5 size-4 shrink-0 text-ink-600" />
        Currently unavailable for delivery. Save it to your wishlist to find it again later.
      </p>
    )
  }
  const freeRule = product.free_delivery && (
    <p className="text-xs text-ink-600" data-testid="free-delivery-rule">
      {product.free_delivery.name}
    </p>
  )
  if (pincode && estimate.data) {
    const quote = estimate.data
    return (
      <div aria-live="polite" aria-busy={estimate.isFetching} className="space-y-2">
        <p className="text-xs text-ink-600">
          Delivering to PIN <span className="font-semibold text-ink-900">{pincode}</span>{' '}
          <button type="button" onClick={() => savePincode('')} className="font-semibold text-amber-700 hover:underline">
            Change
          </button>
        </p>
        <DeliveryEstimate quote={quote} showFee={false} />
        {quote.available && quote.delivery_type && (
          <>
            <p className="text-sm text-ink-800">
              Delivery fee for {quantity}:{' '}
              {quote.fee === '0.00' ? (
                <span className="font-semibold text-success-600">Free</span>
              ) : (
                <span className="font-semibold">{formatPrice(quote.fee)}</span>
              )}
            </p>
            <FreeDeliveryNote
              fee={quote.fee}
              reason={quote.free_delivery_reason}
              amountToFree={quote.amount_to_free_delivery}
              hint={quote.free_delivery_hint}
              threshold={quote.free_delivery_min_order}
            />
          </>
        )}
        {freeRule}
      </div>
    )
  }
  return (
    <div className="space-y-2 text-sm">
      {pincode && estimate.isPending ? (
        <p className="text-ink-600">Checking delivery to {pincode}…</p>
      ) : (
        <>
          {pincode && estimate.isError && (
            <p className="text-ink-600">Couldn’t check delivery to {pincode} right now. The time is confirmed at checkout.</p>
          )}
          <PincodeForm current={pincode} label="Enter your PIN code to see delivery time, fee and fast delivery" />
        </>
      )}
      {freeRule}
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
  rows.push({ label: 'GST', value: `${Number(product.gst_rate)}% (included in the price)` })

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
    <section id="reviews" aria-labelledby="reviews-heading" className="scroll-mt-32 rounded-2xl bg-white shadow-(--shadow-card) p-5 ring-1 ring-steel-200">
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

function Panel({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="rounded-2xl bg-white shadow-(--shadow-card) p-5 ring-1 ring-steel-200">
      <h2 id={id} className="mb-2 text-lg font-bold">
        {title}
      </h2>
      {children}
    </section>
  )
}

/** Uses, installation steps and FAQ written by the shop; each block only when filled in. */
function ProductGuide({ product }: { product: ProductDetail }) {
  const uses = product.uses ?? []
  const steps = product.installation_steps ?? []
  const faqs = product.faqs ?? []
  return (
    <>
      {uses.length > 0 && (
        <Panel id="uses-heading" title="Recommended uses">
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-800">
            {uses.map((use) => (
              <li key={use}>{use}</li>
            ))}
          </ul>
        </Panel>
      )}
      {steps.length > 0 && (
        <Panel id="steps-heading" title="How to install / use">
          <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-800">
            {steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </Panel>
      )}
      {faqs.length > 0 && (
        <Panel id="faq-heading" title="Questions & answers">
          <div className="divide-y divide-steel-100">
            {faqs.map((faq) => (
              <details key={faq.question} className="group py-2">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-ink-900 [&::-webkit-details-marker]:hidden">
                  {faq.question}
                  <ChevronDownIcon className="size-4 shrink-0 transition group-open:rotate-180" />
                </summary>
                <p className="mt-1 text-sm text-ink-800">{faq.answer}</p>
              </details>
            ))}
          </div>
        </Panel>
      )}
    </>
  )
}

function Accessories({ product }: { product: ProductDetail }) {
  const items = product.accessories ?? []
  if (!items.length) return null
  return (
    <section aria-labelledby="accessories-heading" className="py-6">
      <h2 id="accessories-heading" className="mb-4 text-xl font-bold text-ink-950">
        Goes well with
      </h2>
      <ul role="list" className="scrollbar-none -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2 sm:gap-4">
        {items.map((item) => (
          <li key={item.id} className="flex w-44 shrink-0 snap-start flex-col sm:w-56">
            {item.relation_note && <p className="mb-1 text-xs font-medium text-ink-600">{item.relation_note}</p>}
            <div className="w-full flex-1">
              <ProductCard product={item} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function productJsonLd(product: ProductDetail, variant: ProductVariant) {
  return {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: product.name,
    sku: variant.sku,
    description: product.short_description || product.description.slice(0, 300) || undefined,
    image: product.images.map((image) => image.image),
    brand: product.brand ? { '@type': 'Brand', name: product.brand.name } : undefined,
    offers: {
      '@type': 'Offer',
      priceCurrency: 'INR',
      price: variant.price,
      availability:
        variant.stock_status === 'out_of_stock' ? 'https://schema.org/OutOfStock' : 'https://schema.org/InStock',
      url: window.location.href,
    },
    aggregateRating: product.rating_count
      ? { '@type': 'AggregateRating', ratingValue: product.rating_avg, reviewCount: product.rating_count }
      : undefined,
  }
}

export function ProductDetailPage() {
  const { slug = '' } = useParams()
  const product = useProduct(slug)
  const [params, setParams] = useSearchParams()
  const [quantity, setQuantity] = useState(1)

  const data = product.data
  const variant = data ? pickVariant(data, params.get('variant')) : undefined
  usePageMeta(
    data?.name,
    data ? data.short_description || `${data.name} — price, specifications and availability.` : undefined,
    { type: 'product', image: data?.image ?? null, jsonLd: data && variant ? productJsonLd(data, variant) : null },
  )
  useEffect(() => {
    if (data?.slug) recordView(data.slug)
  }, [data?.slug])

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
  const hasTiers = (variant.price_tiers?.length ?? 0) > 1
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
  const productName = variant.name ? `${data.name} (${variant.name})` : data.name
  const addButton = (
    <AddToCartButton
      variantId={variant.id}
      productName={productName}
      quantity={safeQuantity}
      disabled={outOfStock}
      label={outOfStock ? 'Out of stock' : 'Add to cart'}
      className="btn-secondary min-h-12 flex-1 whitespace-nowrap px-2.5 py-3 text-sm sm:px-4 sm:text-base"
    />
  )
  const buyNowButton = !outOfStock && (
    <AddToCartButton
      buyNow
      variantId={variant.id}
      productName={productName}
      quantity={safeQuantity}
      className="btn-primary min-h-12 flex-1 whitespace-nowrap px-2.5 py-3 text-sm sm:px-4 sm:text-base"
    />
  )

  return (
    <div className="pb-28 lg:pb-0">
      <div className="border-b border-steel-200 bg-white">
        <div className="container-page py-3">
          <Breadcrumbs
            items={[
              // Department › category › subcategory, from the server (up to three levels).
              ...(data.breadcrumb?.length
                ? data.breadcrumb.map((c) => ({ label: c.name, to: `/c/${c.slug}` }))
                : [
                    { label: data.category.name, to: `/c/${data.category.slug}` },
                    ...(data.subcategory ? [{ label: data.subcategory.name, to: `/c/${data.subcategory.slug}` }] : []),
                  ]),
              { label: data.name },
            ]}
          />
        </div>
      </div>

      <div className="container-page grid gap-8 py-6 lg:grid-cols-2 lg:gap-12 lg:py-10">
        <div className="lg:sticky lg:top-32 lg:self-start">
          <ProductGallery images={data.images} productName={data.name} variantId={variant.id} />
        </div>

        <div className="space-y-5">
          <div>
            {data.brand && (
              <Link
                to={`/brand/${encodeURIComponent(data.brand.slug)}`}
                className="text-sm font-semibold uppercase tracking-wide text-amber-700 hover:underline"
              >
                {data.brand.name}
              </Link>
            )}
            <h1 className="mt-1 text-2xl font-bold leading-tight text-ink-950 sm:text-3xl lg:text-[2rem]">{data.name}</h1>
            {data.is_demo && (
              <p className="mt-2 inline-flex rounded-full bg-ink-900 px-2.5 py-0.5 text-xs font-semibold text-white" data-testid="demo-notice">
                Demo product: sample listing for the website preview
              </p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-ink-600">
              {data.rating_count > 0 ? (
                <a href="#reviews" className="hover:underline">
                  <Rating average={data.rating_avg} count={data.rating_count} />
                </a>
              ) : (
                <Rating average={data.rating_avg} count={data.rating_count} />
              )}
              <span>
                SKU: <span className="font-mono text-ink-800">{variant.sku}</span>
              </span>
              {data.delivery?.fast && !outOfStock && <FastDeliveryBadge pincode={data.delivery.postal_code} />}
            </div>
            {data.quick_answer && (
              <p className="mt-3 rounded-md bg-steel-100 px-3 py-2 text-sm text-ink-900" data-testid="quick-answer">
                {data.quick_answer}
              </p>
            )}
          </div>

          <PriceBlock
            size="lg"
            price={variant.price}
            mrp={variant.mrp}
            discountPercent={variant.discount_percent}
            discountAmount={variant.discount_amount}
          />
          <p className="-mt-3 text-xs text-ink-600">Price includes {Number(data.gst_rate)}% GST. Delivery fee is shown below.</p>

          {data.offer && !outOfStock && <ProductOfferCallout offer={data.offer} />}

          {data.options?.length ? (
            <OptionPicker options={data.options} variants={data.variants} selected={variant} onSelect={selectVariant} />
          ) : (
            <VariantSelector variants={data.variants} selectedId={variant.id} onSelect={selectVariant} />
          )}

          {hasTiers && !outOfStock && (
            <section aria-label="Bulk pricing" className="rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200">
              <BulkPriceTable tiers={variant.price_tiers ?? []} quantity={safeQuantity} />
            </section>
          )}

          <div className="space-y-3 rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200">
            <div className="flex flex-wrap items-center gap-3">
              <QuantityStepper value={safeQuantity} max={maxQuantity} onChange={setQuantity} disabled={outOfStock} />
              <span className="text-xs text-ink-600">Max {data.max_order_quantity} per order</span>
            </div>
            {!outOfStock && <QuantityPriceQuote slug={data.slug} variantId={variant.id} quantity={safeQuantity} />}
            {/* On small screens the sticky bar at the bottom holds the buttons. */}
            <div className="hidden items-center gap-3 lg:flex">
              {addButton}
              {buyNowButton}
            </div>
            <div className="flex flex-wrap gap-2">
              <WishlistButton productId={data.id} productName={data.name} variant="button" />
              <CompareButton product={{ slug: data.slug, name: data.name, image: (data.images.find((i) => i.is_primary) ?? data.images[0])?.image ?? null }} variant="button" />
            </div>
            <ul className="grid grid-cols-3 gap-2 border-t border-steel-100 pt-3 text-xs text-ink-600" aria-label="Buying with us">
              <li className="flex items-center gap-1.5">
                <TruckIcon className="size-4 shrink-0 text-amber-700" />
                Bengaluru delivery
              </li>
              <li className="flex items-center gap-1.5">
                <ReturnIcon className="size-4 shrink-0 text-amber-700" />
                {data.is_returnable ? 'Returnable' : 'Not returnable'}
              </li>
              <li className="flex items-center gap-1.5">
                <ReceiptIcon className="size-4 shrink-0 text-amber-700" />
                GST included
              </li>
            </ul>
          </div>

          <div className="space-y-3 rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200">
            <p aria-live="polite">
              <StockLabel status={variant.stock_status} lowQuantity={variant.available_quantity} />
              {data.variants.length > 1 && (
                <span className="ml-2 text-sm text-ink-600">
                  for {variantLabel(variant, data.variants.indexOf(variant))}
                </span>
              )}
            </p>
            <DeliveryInfo product={data} variant={variant} quantity={safeQuantity} />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {!outOfStock && (
              <div className="rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200">
                <h2 className="mb-1 text-sm font-bold text-ink-950">Payment</h2>
                <PaymentOptionsNote slug={data.slug} variantId={variant.id} quantity={safeQuantity} />
              </div>
            )}
            <div className="rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200">
              <h2 className="mb-1 text-sm font-bold text-ink-950">Returns</h2>
              <p className="text-sm text-ink-800" data-testid="return-policy">
                {data.return_policy?.text ?? (data.is_returnable ? 'Returnable' : 'Not returnable')}
              </p>
            </div>
          </div>

          {data.short_description && <p className="text-ink-800">{data.short_description}</p>}

          <ProductEnquiry productId={data.id} productName={data.name} />
        </div>
      </div>

      <div className="container-page grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          <Panel id="specs-heading" title="Specifications">
            <SpecTable product={data} variant={variant} />
          </Panel>
          {data.description && (
            <Panel id="description-heading" title="Description">
              <p className="whitespace-pre-line text-sm leading-relaxed text-ink-800">{data.description}</p>
            </Panel>
          )}
          <ProductGuide product={data} />
        </div>
        <Reviews product={data} />
      </div>

      <div className="container-page space-y-6">
        <CompatibilityChecker product={data} variantId={variant.id} />
        <ProductRecommendations
          productId={data.id}
          variantId={variant.id}
          fallback={<AccessoryGroups productId={data.id} variantId={variant.id} fallback={<Accessories product={data} />} />}
        />
        <ProductRail
          title={`More in ${subcategory.name}`}
          params={{ category: subcategory.slug, exclude: data.slug }}
          viewAllHref={`/c/${subcategory.slug}`}
        />
      </div>

      {/* Mobile sticky purchase bar */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-steel-200 bg-white p-3 shadow-[0_-4px_12px_rgba(0,0,0,0.06)] lg:hidden">
        <div className="flex items-center gap-2">
          <div className="min-w-0 shrink">
            <p className="text-lg font-bold leading-tight">{formatPrice(variant.price)}</p>
            <p className="truncate text-xs text-ink-600">
              {safeQuantity > 1 ? `Qty ${safeQuantity}` : variant.name || data.name}
            </p>
          </div>
          {addButton}
          {buyNowButton}
        </div>
      </div>
    </div>
  )
}
