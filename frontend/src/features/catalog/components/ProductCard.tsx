import { Link } from 'react-router'

import { AddToCartButton } from '@/features/cart/AddToCartButton'
import { WishlistButton } from '@/features/wishlist/WishlistButton'
import { formatPercent } from '@/lib/format'

import type { ProductSummary } from '../types'
import { FastDeliveryBadge, PriceBlock, Rating, StockLabel } from './badges'
import { ProductImage } from './ProductImage'

export function ProductCard({ product }: { product: ProductSummary }) {
  const href = `/p/${product.slug}`
  const percent = formatPercent(product.discount_percent)
  const outOfStock = product.stock_status === 'out_of_stock'
  const hasOptions = product.variant_count > 1

  return (
    <article className="group relative flex flex-col rounded-lg bg-white p-3 ring-1 ring-steel-200 transition-shadow hover:shadow-md">
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

      <div className="mt-3 flex flex-1 flex-col gap-1.5">
        {product.brand && <p className="text-xs font-medium uppercase tracking-wide text-ink-600">{product.brand.name}</p>}
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-ink-900">
          <Link to={href} className="hover:text-amber-600 focus-visible:text-amber-600">
            {product.name}
          </Link>
        </h3>
        <Rating average={product.rating_avg} count={product.rating_count} compact />
        <PriceBlock price={product.price} mrp={product.mrp} discountPercent={product.discount_percent} />
        {hasOptions && <p className="text-xs text-ink-600">{product.variant_count} options available</p>}
        <div className="flex flex-wrap items-center gap-2">
          <StockLabel status={product.stock_status} />
          {product.fast_delivery && !outOfStock && <FastDeliveryBadge />}
        </div>
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
            <AddToCartButton variantId={product.default_variant_id} productName={product.name} />
          )}
        </div>
      </div>
    </article>
  )
}
