import { formatPrice } from '@/lib/format'

import type { DeliveryQuote } from './types'

const TIME_ZONE = 'Asia/Kolkata' // stores run on Indian time wherever the browser is

/** "2:30 pm" style clock time in the stores' time zone. */
export function formatClock(iso: string): string {
  return new Date(iso)
    .toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: TIME_ZONE })
    .toUpperCase()
}

/** Orders on the move are refreshed regularly, so the delivery code and the progress stay current. */
export function trackingPollMs(status: string | undefined): number | false {
  return status && ['packed', 'assigned', 'picked_up', 'out_for_delivery'].includes(status) ? 20_000 : false
}

/** "42 minutes" for fast delivery, the delivery window for standard. */
export function estimateText(quote: Pick<DeliveryQuote, 'delivery_type' | 'eta_minutes' | 'label'>): string {
  if (quote.delivery_type === 'fast' && quote.eta_minutes !== null) return `${quote.eta_minutes} minutes`
  return quote.label
}

/** "Add ₹400 more of Cement for free delivery" (amounts and the items that count come from the server). */
export function freeDeliveryHint(amount: string, hint?: string, threshold?: string | null): string {
  const what = hint ? ` of ${hint}` : ''
  const from = threshold && !hint ? ` (orders from ${formatPrice(threshold)})` : ''
  return `Add ${formatPrice(amount)} more${what} for free delivery${from}.`
}
