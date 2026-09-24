import { Link } from 'react-router'

import type { CartOffers } from '@/features/cart/api'
import type { ProductOffer } from '@/features/catalog/types'
import { formatPrice } from '@/lib/format'

import { useLiveOffers, type AvailableCoupon } from './api'

/** "Offer · 10% off" label. Text (not colour alone) says what it is. */
export function OfferBadge({ offer, className = '' }: { offer: ProductOffer; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-ink-900 ${className}`}
      title={offer.name}
    >
      <span aria-hidden>🏷</span>
      <span>
        <span className="sr-only">Offer: </span>
        {offer.badge}
      </span>
    </span>
  )
}

/** Product page callout: what the offer is and that it is applied in the cart automatically. */
export function ProductOfferCallout({ offer }: { offer: ProductOffer }) {
  const minimum = offer.min_order_value !== '0.00'
  return (
    <div className="rounded-lg bg-amber-100 p-3 text-sm text-ink-900" role="note">
      <p className="font-semibold">
        Offer: {offer.name} — {offer.badge}
      </p>
      <p className="text-xs text-ink-800">
        Applied automatically in your cart{minimum && ` when eligible items total ${formatPrice(offer.min_order_value)} or more`}.
        No code needed.
      </p>
    </div>
  )
}

/** Applied offers + "add ₹X more to unlock" hints from the server's cart evaluation. */
export function CartOfferNotes({ offers }: { offers: CartOffers }) {
  if (!offers.applied.length && !offers.missed.length) return null
  return (
    <div className="space-y-2" aria-live="polite">
      {offers.applied.map((offer) => (
        <p key={offer.id} className="rounded-md bg-success-600/10 px-3 py-2 text-sm text-success-600">
          <span className="font-semibold">{offer.name}</span> applied — you save {formatPrice(offer.discount)}
        </p>
      ))}
      {offers.missed.map((offer) => (
        <p key={offer.id} className="rounded-md bg-amber-100 px-3 py-2 text-sm text-ink-900">
          Add {formatPrice(offer.shortfall)} more of eligible items to unlock{' '}
          <span className="font-semibold">{offer.name}</span> ({offer.badge}).
        </p>
      ))}
    </div>
  )
}

/** Advertised coupons with the server's verdict; applicable ones can be applied with one tap. */
export function AvailableCouponList({
  coupons,
  onApply,
  busy,
}: {
  coupons: AvailableCoupon[]
  onApply: (code: string) => void
  busy?: boolean
}) {
  if (!coupons.length) return null
  return (
    <div className="mt-3">
      <p className="mb-2 text-sm font-semibold text-ink-900">Available coupons</p>
      <ul className="space-y-2">
        {coupons.map((coupon) => (
          <li
            key={coupon.code}
            className={`flex flex-wrap items-center justify-between gap-2 rounded-md px-3 py-2 text-sm ring-1 ${coupon.applicable ? 'ring-success-600/40' : 'ring-steel-200'}`}
          >
            <div className="min-w-0">
              <p>
                <span className="font-mono font-semibold">{coupon.code}</span> · {coupon.badge}
              </p>
              <p className="text-xs text-ink-600">
                {coupon.applicable && coupon.discount ? `Saves ${formatPrice(coupon.discount)} on this order` : coupon.message}
              </p>
            </div>
            <button
              type="button"
              onClick={() => onApply(coupon.code)}
              disabled={!coupon.applicable || busy}
              className="btn-secondary min-h-9 px-3 py-1"
            >
              Apply<span className="sr-only"> coupon {coupon.code}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Homepage strip of live offers. Hidden when there are none (or they can't be loaded). */
export function LiveOffersStrip() {
  const offers = useLiveOffers()
  if (!offers.data?.length) return null
  return (
    <section aria-labelledby="live-offers-heading" className="py-6">
      <h2 id="live-offers-heading" className="mb-3 text-xl font-bold text-ink-950">
        Offers running now
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {offers.data.map((offer) => {
          const target = offer.categories[0] ?? null
          return (
            <li key={offer.id} className="rounded-lg bg-white p-4 ring-1 ring-amber-500/40">
              <p className="text-lg font-bold text-ink-950">{offer.badge}</p>
              <p className="font-semibold">{offer.name}</p>
              {offer.description && <p className="mt-1 text-sm text-ink-600">{offer.description}</p>}
              <p className="mt-2 text-xs text-ink-600">
                Applied automatically in your cart
                {offer.min_order_value !== '0.00' && ` on eligible items worth ${formatPrice(offer.min_order_value)}+`}
                {offer.ends_at && ` · ends ${new Date(offer.ends_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`}
              </p>
              {target && (
                <Link to={`/c/${target.slug}`} className="mt-2 inline-block text-sm font-semibold text-amber-600 hover:underline">
                  Shop {target.name}
                  <span className="sr-only"> for offer {offer.name}</span>
                </Link>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
