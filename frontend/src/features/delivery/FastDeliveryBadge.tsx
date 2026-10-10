import { BoltIcon } from '@/components/icons'

import { useDeliveryPromise, useServiceability } from './api'
import { isValidPincode, usePincode } from './location'

/**
 * The "60 Mins" service indicator in the header. The number is the shop's fast-delivery limit
 * (FAST_DELIVERY_MAX_MINUTES); it is never a promise for an order. For the chosen PIN the delivery
 * engine says whether fast delivery is available right now (zone, stock, store, riders, travel time),
 * and the badge dims when it is not. A failed check stays quiet: the badge just stays neutral.
 */
export function FastDeliveryBadge() {
  const promise = useDeliveryPromise()
  const pincode = usePincode()
  const check = useServiceability(pincode)
  const minutes = promise.data?.fast_delivery_max_minutes
  if (!minutes) return null

  const data = isValidPincode(pincode) ? check.data : undefined
  // A PIN we don't deliver to gets no fast-delivery claim at all (the Deliver to chip says why).
  if (data && !data.serviceable) return null
  let state: 'neutral' | 'available' | 'unavailable' = 'neutral'
  let detail = `Fast delivery within ${minutes} minutes where we can. Choose your PIN code to check your area; your time is shown in the cart.`
  if (data?.serviceable && data.fast_delivery_available) {
    state = 'available'
    detail = `Fast delivery available to ${pincode}: ${data.label} for items in stock nearby. Your order’s time is shown in the cart.`
  } else if (data) {
    state = 'unavailable'
    detail = data.serviceable
      ? `Fast delivery isn’t available to ${pincode} right now${data.fast_unavailable_reason ? ` (${data.fast_unavailable_reason})` : ''}. ${data.label}.`
      : data.message
  }
  const tone = {
    neutral: 'bg-amber-500/15 text-amber-400 ring-amber-500/40',
    available: 'bg-amber-500 text-ink-950 ring-amber-500',
    unavailable: 'bg-ink-800 text-steel-400 ring-ink-700',
  }[state]

  return (
    <span
      title={detail}
      data-testid="fast-badge"
      data-state={state}
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-1 text-xs font-bold ring-1 ${tone}`}
    >
      <BoltIcon className="size-3.5" />
      {minutes} Mins
      <span className="sr-only">: {detail}</span>
    </span>
  )
}
