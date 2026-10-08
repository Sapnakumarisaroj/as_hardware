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
        <span className={`font-bold tracking-tight text-ink-950 ${big ? 'text-3xl' : 'text-lg'}`}>
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

export function StockLabel({
  status,
  lowQuantity,
  compact = false,
}: {
  status: StockStatus
  lowQuantity?: number | null
  compact?: boolean
}) {
  const [text, tone, dot] =
    status === 'out_of_stock'
      ? ['Out of stock', 'text-danger-600', 'bg-danger-600']
      : status === 'low_stock'
        ? [lowQuantity ? `Only ${lowQuantity} left` : 'Limited stock', 'text-amber-700', 'bg-amber-500']
        : ['In stock', 'text-success-600', 'bg-success-600']
  return (
    <span className={`inline-flex items-center gap-1.5 font-semibold ${tone} ${compact ? 'text-xs' : 'text-sm'}`}>
      <span aria-hidden className={`size-1.5 rounded-full ${dot}`} />
      {text}
    </span>
  )
}

/** Only rendered when the server said fast delivery is possible to the shopper's PIN (Phase 16). */
export function FastDeliveryBadge({ pincode }: { pincode?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-ink-900"
      data-testid="fast-badge"
    >
      <BoltIcon className="size-3.5 text-amber-700" />
      Fast delivery
      {pincode && <span className="sr-only"> to {pincode}</span>}
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
