import { useProductQuote } from '@/features/catalog/api'
import { formatPrice } from '@/lib/format'

import type { BulkPricingSummary, PriceTier } from '../types'

function rangeLabel(tier: PriceTier): string {
  if (tier.max_quantity === null) return `${tier.min_quantity}+ units`
  if (tier.min_quantity === tier.max_quantity) return `${tier.min_quantity} unit${tier.min_quantity === 1 ? '' : 's'}`
  return `${tier.min_quantity}–${tier.max_quantity} units`
}

/** Product card line: "Bulk price from ₹395 (10+)". Text, not colour, carries the meaning. */
export function BulkPriceIndicator({ bulk }: { bulk: BulkPricingSummary }) {
  return (
    <p className="text-xs font-semibold text-ink-900" data-testid="bulk-indicator">
      <span className="rounded bg-steel-100 px-1.5 py-0.5">Bulk price</span>{' '}
      <span className="font-normal text-ink-600">
        from {formatPrice(bulk.lowest_unit_price)}/unit
        {bulk.from_quantity ? ` (${bulk.from_quantity}+)` : ''}
      </span>
    </p>
  )
}

/** The variant's bulk price table, with the row for the chosen quantity highlighted. */
export function BulkPriceTable({ tiers, quantity }: { tiers: PriceTier[]; quantity: number }) {
  if (tiers.length < 2) return null
  const active = [...tiers].reverse().find((tier) => quantity >= tier.min_quantity)
  return (
    <table className="w-full text-sm">
      <caption className="mb-1 text-left text-sm font-semibold text-ink-900">Bulk prices</caption>
      <thead>
        <tr className="text-left text-xs text-ink-600">
          <th scope="col" className="py-1 font-medium">
            Quantity
          </th>
          <th scope="col" className="py-1 font-medium">
            Price per unit
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            You save
          </th>
        </tr>
      </thead>
      <tbody>
        {tiers.map((tier) => {
          const isActive = tier === active
          return (
            <tr
              key={tier.min_quantity}
              aria-current={isActive ? 'true' : undefined}
              className={`border-t border-steel-100 ${isActive ? 'bg-amber-100 font-semibold' : ''}`}
            >
              <td className="py-1.5 pl-1">{rangeLabel(tier)}</td>
              <td className="py-1.5">{formatPrice(tier.unit_price)}</td>
              <td className="py-1.5 pr-1 text-right text-success-600">
                {tier.is_base ? '—' : `${Number(tier.saving_percent).toFixed(1).replace(/\.0$/, '')}%`}
                {isActive && <span className="sr-only">{' (your quantity)'}</span>}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/**
 * "Quantity 10 → ₹415/unit" and "10 × ₹415 = ₹4,150" from the shop's pricing engine
 * (GET /products/{slug}/quote/), so the product page never calculates a price itself. The cart and
 * checkout price again from the database.
 */
export function QuantityPriceQuote({ slug, variantId, quantity }: { slug: string; variantId: number; quantity: number }) {
  const quote = useProductQuote(slug, variantId, quantity)
  if (quote.isPending) return <p className="text-sm text-ink-600">Checking the price for {quantity}…</p>
  if (quote.isError || !quote.data) return null
  const data = quote.data
  return (
    <div className="space-y-1 text-sm" aria-live="polite" aria-busy={quote.isFetching} data-testid="price-quote">
      <p className="text-base">
        Quantity {data.quantity} → <span className="font-bold text-ink-950">{formatPrice(data.unit_price)}/unit</span>
        {data.applied_tier && (
          <span className="ml-2 rounded bg-success-600/10 px-1.5 py-0.5 text-xs font-semibold text-success-600">
            Bulk price applied
          </span>
        )}
      </p>
      <p className="text-ink-800">
        {data.quantity} × {formatPrice(data.unit_price)} ={' '}
        <span className="font-semibold text-ink-950">{formatPrice(data.line_total)}</span>
      </p>
      {data.bulk_saving !== '0.00' && (
        <p className="text-success-600">
          You save {formatPrice(data.bulk_saving)} with the {data.applied_tier?.min_quantity}+ price
        </p>
      )}
      {data.offers.map((offer) => (
        <p key={offer.name} className="text-success-600">
          Offer {offer.name}: {offer.badge} (−{formatPrice(data.offer_discount)} in the cart)
        </p>
      ))}
      {data.next_tier?.reachable && (
        <p className="font-medium text-ink-900" data-testid="next-tier">
          Add {data.next_tier.units_more} more to unlock {formatPrice(data.next_tier.unit_price)}/unit
        </p>
      )}
      {!data.within_stock && <p className="text-danger-600">Not enough stock for {data.quantity} right now.</p>}
      <p className="text-xs text-ink-600">Final price, delivery fee and offers are confirmed in your cart.</p>
    </div>
  )
}

/** Payment choices for this amount: online always; cash on delivery with the shop's rule and reason. */
export function PaymentOptionsNote({ slug, variantId, quantity }: { slug: string; variantId: number; quantity: number }) {
  const quote = useProductQuote(slug, variantId, quantity)
  const options = quote.data?.payment_options
  if (!options) return null
  const cod = options.cod
  return (
    <ul className="space-y-1 text-sm" aria-label="Payment options" data-testid="payment-options">
      <li className="text-ink-800">✓ Pay online (UPI, cards, net banking)</li>
      {cod.available ? (
        <li className="text-ink-800">
          ✓ Cash on delivery
          {cod.max_order_value && (
            <span className="text-ink-600"> · for orders up to {formatPrice(cod.max_order_value)}</span>
          )}
        </li>
      ) : (
        <li className="text-ink-600">✗ {cod.message || 'Cash on delivery isn’t available for this order.'}</li>
      )}
    </ul>
  )
}
