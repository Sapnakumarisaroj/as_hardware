import { BoltIcon, StarIcon } from '@/components/icons'
import { formatPercent, formatPrice, formatRating } from '@/lib/format'

import type { StockStatus } from '../types'

/** Server-computed price, MRP and saving. Nothing here is calculated in the browser. */
export function PriceBlock({
  price,
  mrp,
  discountPercent,
  discountAmount,
  size = 'md',
}: {
  price: string | null
  mrp: string | null
  discountPercent: string | null
  discountAmount?: string | null
  size?: 'md' | 'lg'
}) {
  if (price === null) return <p className="text-sm text-ink-600">Price unavailable</p>
  const percent = formatPercent(discountPercent)
  const big = size === 'lg'
  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className={`font-bold text-ink-950 ${big ? 'text-3xl' : 'text-lg'}`}>
          <span className="sr-only">Price: </span>
          {formatPrice(price)}
        </span>
        {percent && mrp && (
          <>
            <span className={`text-ink-600 line-through ${big ? 'text-base' : 'text-sm'}`}>
              <span className="sr-only">MRP: </span>
              {formatPrice(mrp)}
            </span>
            <span className={`font-semibold text-success-600 ${big ? 'text-base' : 'text-sm'}`}>{percent} off</span>
          </>
        )}
      </div>
      {big && percent && discountAmount && (
        <p className="mt-1 text-sm font-medium text-success-600">You save {formatPrice(discountAmount)}</p>
      )}
      {big && <p className="mt-1 text-xs text-ink-600">Inclusive of all taxes · MRP {formatPrice(mrp)}</p>}
    </div>
  )
}

export function StockLabel({ status, lowQuantity }: { status: StockStatus; lowQuantity?: number | null }) {
  if (status === 'out_of_stock') return <span className="text-sm font-semibold text-danger-600">Out of stock</span>
  if (status === 'low_stock') {
    return (
      <span className="text-sm font-semibold text-amber-600">
        {lowQuantity ? `Only ${lowQuantity} left` : 'Limited stock'}
      </span>
    )
  }
  return <span className="text-sm font-semibold text-success-600">In stock</span>
}

export function FastDeliveryBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-ink-900">
      <BoltIcon className="size-3.5 text-amber-600" />
      Fast delivery
    </span>
  )
}

export function Rating({ average, count, compact = false }: { average: string; count: number; compact?: boolean }) {
  if (!count) return <span className="text-xs text-ink-600">No reviews yet</span>
  const value = formatRating(average)
  return (
    <span className="inline-flex items-center gap-1 text-xs text-ink-800">
      <span className="inline-flex items-center gap-0.5 rounded bg-success-600 px-1.5 py-0.5 font-semibold text-white">
        {value}
        <StarIcon className="size-3" />
      </span>
      <span>
        <span className="sr-only">average rating from </span>
        {compact ? `(${count})` : `${count} ${count === 1 ? 'review' : 'reviews'}`}
      </span>
    </span>
  )
}
