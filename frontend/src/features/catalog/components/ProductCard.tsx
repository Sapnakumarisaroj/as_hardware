import { useState } from 'react'
import { Link } from 'react-router'

import { ClockIcon } from '@/components/icons'
import { QuantityStepper } from '@/components/QuantityStepper'
import { AddToCartButton } from '@/features/cart/AddToCartButton'
import { CompareButton } from '@/features/compare/CompareButton'
import { useServiceability } from '@/features/delivery/api'
import { isValidPincode, usePincode } from '@/features/delivery/location'
import { OfferBadge } from '@/features/offers/components'
import { WishlistButton } from '@/features/wishlist/WishlistButton'
import { formatPercent, formatPrice } from '@/lib/format'

import type { ProductSummary } from '../types'
import { FastDeliveryBadge, PriceBlock, Rating, StockLabel } from './badges'
import { BulkPriceIndicator } from './BulkPricing'
import { ProductImage } from './ProductImage'

/**
 * Product card. Every figure is the server's: price, MRP, saving, bulk price, offer, free-delivery rule.
 * Fast delivery is shown only for the shopper's chosen PIN (`product.delivery`, Phase 16), never as a
 * general promise; with a PIN the card also says when no store serving that PIN has the item.
 */
export function ProductCard({ product }: { product: ProductSummary }) {
  const [quantity, setQuantity] = useState(1)
  const href = `/p/${product.slug}`
  const percent = formatPercent(product.discount_percent)
  const outOfStock = product.stock_status === 'out_of_stock'
  const hasOptions = product.variant_count > 1
  const delivery = product.delivery
  // The shopper's PIN: the per-PIN answer is on the product (`delivery`); the area-wide one (do we
  // deliver there at all, the estimate for an item in stock nearby) is one cached check for all cards.
  const pincode = usePincode()
  const hasPin = isValidPincode(pincode)
  const area = useServiceability(pincode).data
  const notServed = hasPin && area?.serviceable === false
  const notHere = Boolean(delivery && !delivery.deliverable && !outOfStock && !notServed)
  const saving = percent && product.discount_amount && product.discount_amount !== '0.00' ? product.discount_amount : null

  return (
    <article className="card card-hover group relative flex h-full flex-col overflow-hidden">
      <div className="relative bg-gradient-to-b from-steel-50 to-white">
        <Link to={href} tabIndex={-1} aria-hidden="true" className="block overflow-hidden">
          <ProductImage
            src={product.image}
            alt={product.image_alt}
            className="aspect-square w-full bg-transparent p-3 transition-transform duration-300 ease-out group-hover:scale-[1.04] sm:p-4"
          />
        </Link>
        {(percent || product.is_demo) && (
          <div className="absolute left-2.5 top-2.5 flex flex-col items-start gap-1">
            {percent && <span className="rounded-full bg-success-600 px-2 py-0.5 text-[11px] font-bold text-white shadow-sm">{percent} off</span>}
            {product.is_demo && (
              <span className="rounded-full bg-ink-900/85 px-2 py-0.5 text-[11px] font-semibold text-white shadow-sm" data-testid="demo-badge">
                Demo product
              </span>
            )}
          </div>
        )}
        <div className="absolute right-2 top-2 flex flex-col gap-2 [&>button]:relative [&>button]:after:absolute [&>button]:after:-inset-1 [&>button]:after:content-['']">
          <WishlistButton productId={product.id} productName={product.name} />
          <CompareButton product={{ slug: product.slug, name: product.name, image: product.image }} />
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-1.5 border-t border-steel-100 p-3 sm:p-4">
        {product.brand && (
          <p className="truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-600">{product.brand.name}</p>
        )}
        <h3 className="line-clamp-2 min-h-10 text-sm font-semibold leading-5 text-ink-900">
          <Link to={href} className="transition-colors hover:text-amber-700 focus-visible:text-amber-700">
            {product.name}
          </Link>
        </h3>
        {product.match_reason && product.match_type !== 'keyword' && (
          <p className="text-xs italic text-ink-600" data-testid="match-reason">
            {product.match_reason}
          </p>
        )}
        {(product.variant_label || product.unit) && (
          <p className="truncate text-xs text-ink-600" data-testid="variant-size">
            {[product.variant_label, product.unit && `per ${product.unit}`].filter(Boolean).join(' · ')}
          </p>
        )}
        <Rating average={product.rating_avg} count={product.rating_count} compact />
        <div className="mt-0.5">
          <PriceBlock price={product.price} mrp={product.mrp} discountPercent={product.discount_percent} />
          {saving && <p className="text-xs font-medium text-success-600">Save {formatPrice(saving)}</p>}
        </div>
        {(product.bulk_pricing && !outOfStock) || hasOptions ? (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {product.bulk_pricing && !outOfStock && <BulkPriceIndicator bulk={product.bulk_pricing} />}
            {hasOptions && <p className="text-xs text-ink-600">{product.variant_count} options</p>}
          </div>
        ) : null}

        <ul className="flex flex-wrap items-center gap-x-2.5 gap-y-1" aria-label="Availability and delivery">
          <li>
            <StockLabel status={product.stock_status} compact />
          </li>
          {delivery?.fast && !outOfStock && !notServed && (
            <li>
              <FastDeliveryBadge pincode={delivery.postal_code} />
            </li>
          )}
          {delivery?.fast && !outOfStock && !notServed && area?.fast_delivery_available && area.label && (
            <li className="text-xs font-medium text-ink-800" data-testid="card-eta">
              {area.label}
            </li>
          )}
          {delivery && delivery.deliverable && !delivery.fast && !outOfStock && !notServed && (
            <li className="inline-flex items-center gap-1 text-xs text-ink-600">
              <ClockIcon className="size-3.5" />
              Standard delivery
            </li>
          )}
          {product.offer && !outOfStock && (
            <li>
              <OfferBadge offer={product.offer} />
            </li>
          )}
          {product.free_delivery && !outOfStock && (
            <li>
              <span
                className="inline-flex rounded-md bg-steel-100 px-1.5 py-0.5 text-[11px] font-semibold text-ink-800"
                title={product.free_delivery.name}
                data-testid="free-delivery-badge"
              >
                Free delivery from {formatPrice(product.free_delivery.threshold)}
              </span>
            </li>
          )}
        </ul>
        {notHere && delivery && (
          <p className="text-xs text-ink-600" data-testid="not-deliverable">
            Not available for delivery to {delivery.postal_code}
          </p>
        )}
        {notServed && !outOfStock && (
          <p className="text-xs text-ink-600" data-testid="not-served">
            We don’t deliver to {pincode} yet
          </p>
        )}
        {!hasPin && !delivery && !outOfStock && (
          <p className="text-xs text-ink-600" data-testid="pin-prompt">
            Enter PIN to check delivery
          </p>
        )}

        <div className="mt-auto pt-2.5">
          {hasOptions ? (
            <Link to={href} className="btn-secondary min-h-11 w-full">
              Choose options
            </Link>
          ) : outOfStock || !product.default_variant_id ? (
            <button type="button" disabled className="btn-secondary min-h-11 w-full">
              Out of stock
            </button>
          ) : (
            // Wraps the Add button under the stepper when the card is too narrow for both (320px phones).
            <div className="flex flex-wrap items-center gap-1.5">
              <QuantityStepper
                size="sm"
                value={quantity}
                max={99}
                onChange={(value) => setQuantity(Math.max(1, Math.min(99, value)))}
                label={`Quantity of ${product.name}`}
              />
              <AddToCartButton
                variantId={product.default_variant_id}
                productName={product.name}
                quantity={quantity}
                label="Add"
                className="btn-primary min-h-11 min-w-16 flex-1 basis-16 px-2"
              />
            </div>
          )}
        </div>
      </div>
    </article>
  )
}
