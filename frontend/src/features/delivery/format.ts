import type { DeliveryQuote } from './types'

const TIME_ZONE = 'Asia/Kolkata' // stores run on Indian time wherever the browser is

/** "2:30 pm" style clock time in the stores' time zone. */
export function formatClock(iso: string): string {
  return new Date(iso)
    .toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: TIME_ZONE })
    .toUpperCase()
}

/** "42 minutes" for fast delivery, the delivery window for standard. */
export function estimateText(quote: Pick<DeliveryQuote, 'delivery_type' | 'eta_minutes' | 'label'>): string {
  if (quote.delivery_type === 'fast' && quote.eta_minutes !== null) return `${quote.eta_minutes} minutes`
  return quote.label
}
