import { useState } from 'react'
import { Link } from 'react-router'

import { QuantityStepper } from '@/components/QuantityStepper'
import { AddToCartButton } from '@/features/cart/AddToCartButton'
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
  const notHere = Boolean(delivery && !delivery.deliverable && !outOfStock)
  const saving = percent && product.discount_amount && product.discount_amount !== '0.00' ? product.discount_amount : null

  return (
    <article className="group relative flex h-full flex-col rounded-lg bg-white p-2.5 ring-1 ring-steel-200 transition-shadow hover:shadow-md sm:p-3">
      <div className="relative">
        <Link to={href} tabIndex={-1} aria-hidden="true">
          <ProductImage src={product.image} alt={product.image_alt} className="aspect-square w-full rounded" />
        </Link>
        {percent && (
          <span className="absolute left-2 top-2 rounded bg-success-600 px-1.5 py-0.5 text-xs font-bold text-white">
            {percent} off
          </span>
        )}
        <div className="absolute right-2 top-2">
          <WishlistButton productId={product.id} productName={product.name} />
        </div>
      </div>

      <div className="mt-2.5 flex flex-1 flex-col gap-1.5">
        {product.brand && (
          <p className="truncate text-[11px] font-medium uppercase tracking-wide text-ink-600 sm:text-xs">
            {product.brand.name}
          </p>
        )}
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-ink-900">
          <Link to={href} className="hover:text-amber-600 focus-visible:text-amber-600">
            {product.name}
          </Link>
        </h3>
        {product.match_reason && product.match_type !== 'keyword' && (
          <p className="text-xs italic text-ink-600" data-testid="match-reason">
            {product.match_reason}
          </p>
        )}
        <Rating average={product.rating_avg} count={product.rating_count} compact />
        <PriceBlock price={product.price} mrp={product.mrp} discountPercent={product.discount_percent} />
        {saving && <p className="-mt-1 text-xs font-medium text-success-600">Save {formatPrice(saving)}</p>}
        {product.bulk_pricing && !outOfStock && <BulkPriceIndicator bulk={product.bulk_pricing} />}
        {hasOptions && <p className="text-xs text-ink-600">{product.variant_count} options</p>}

        <ul className="flex flex-wrap items-center gap-1.5" aria-label="Availability and delivery">
          <li>
            <StockLabel status={product.stock_status} />
          </li>
          {delivery?.fast && !outOfStock && (
            <li>
              <FastDeliveryBadge pincode={delivery.postal_code} />
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
                className="inline-flex rounded bg-steel-100 px-1.5 py-0.5 text-xs font-semibold text-ink-900"
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

        <div className="mt-auto pt-2">
          {hasOptions ? (
            <Link to={href} className="btn-secondary w-full">
              Choose options
            </Link>
          ) : outOfStock || !product.default_variant_id ? (
            <button type="button" disabled className="btn-secondary w-full">
              Out of stock
            </button>
          ) : (
            <div className="flex items-center gap-1.5">
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
                className="btn-primary min-w-0 flex-1 px-2"
              />
            </div>
          )}
        </div>
      </div>
    </article>
  )
}
