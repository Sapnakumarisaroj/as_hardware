import { useId, useState, type FormEvent, type ReactNode } from 'react'

import { formatPrice } from '@/lib/format'

import { estimateText, formatClock, freeDeliveryHint } from './format'
import { isValidPincode, savePincode } from './location'
import type { DeliveryQuote, DeliveryType, OrderDelivery, OrderShipment } from './types'

function Emoji({ children }: { children: string }) {
  return (
    <span aria-hidden="true" className="mr-1.5">
      {children}
    </span>
  )
}

/** "⚡ Fast delivery" / "🚚 Standard delivery" (text carries the meaning; the emoji is decoration). */
export function DeliveryTypeHeading({ type, suffix = '' }: { type: DeliveryType; suffix?: string }) {
  return (
    <p className="font-semibold text-ink-900">
      <Emoji>{type === 'fast' ? '⚡' : '🚚'}</Emoji>
      {type === 'fast' ? `Fast delivery${suffix}` : 'Standard delivery'}
    </p>
  )
}

/**
 * A delivery estimate exactly as the backend calculated it: fast or standard, the time, why fast
 * delivery isn't offered (with the next option), or why the items can't be delivered at all.
 */
export function DeliveryEstimate({
  quote,
  showFee = false,
  children,
}: {
  quote: DeliveryQuote
  showFee?: boolean
  children?: ReactNode
}) {
  if (!quote.available) {
    return (
      <div className="space-y-1 text-sm">
        <p role="alert" className="font-semibold text-danger-600">
          {quote.message}
        </p>
        {children}
      </div>
    )
  }
  if (!quote.delivery_type) {
    // In stock, but no location yet: nothing is promised.
    return (
      <div className="space-y-1 text-sm">
        <p className="text-ink-800">{quote.message}</p>
        {children}
      </div>
    )
  }
  const split = quote.shipments.length > 1
  return (
    <div className="space-y-1.5 text-sm">
      {quote.delivery_type === 'standard' && quote.fast_unavailable_reason && (
        <p className="text-ink-600">
          <span className="font-semibold text-ink-800">Fast delivery unavailable</span> — {quote.fast_unavailable_reason}
        </p>
      )}
      <DeliveryTypeHeading type={quote.delivery_type} suffix=" available" />
      <p className="text-ink-900">
        Estimated delivery: <span className="font-semibold">{estimateText(quote)}</span>
      </p>
      {split ? (
        <div className="text-ink-600">
          <p>Your items come from {quote.shipments.length} stores and may arrive separately:</p>
          <ul className="mt-1 list-disc pl-5">
            {quote.shipments.map((shipment) => (
              <li key={shipment.sequence}>
                {shipment.line_count} {shipment.line_count === 1 ? 'item' : 'items'} from {shipment.store_name}
                {shipment.label && ` · ${shipment.label}`}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        quote.store_name && (
          <p className="text-ink-600">
            From {quote.store_name}
            {quote.prep_minutes !== null && ` · about ${quote.prep_minutes} min to pack`}
          </p>
        )
      )}
      {quote.location_precision && quote.location_precision !== 'exact' && (
        <p className="text-xs text-ink-600">Based on your PIN code. The exact time is confirmed for your address at checkout.</p>
      )}
      {showFee && (
        <p className="text-ink-800">
          Delivery fee:{' '}
          {quote.fee === '0.00' ? <span className="font-semibold text-success-600">Free</span> : formatPrice(quote.fee)}
          {quote.amount_to_free_delivery !== '0.00' && (
            <span className="block text-xs text-ink-600">
              Add {formatPrice(quote.amount_to_free_delivery)} more for free delivery (orders from{' '}
              {formatPrice(quote.free_delivery_min_order)}).
            </span>
          )}
        </p>
      )}
      {children}
    </div>
  )
}

/** Small PIN code form used where no delivery location is known yet. */
export function PincodeForm({ current = '', label = 'Check delivery to your PIN code' }: { current?: string; label?: string }) {
  const id = useId()
  const [draft, setDraft] = useState(current)
  const [error, setError] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    const value = draft.trim()
    if (!isValidPincode(value)) {
      setError('Enter a valid 6-digit PIN code.')
      return
    }
    setError('')
    savePincode(value)
  }

  return (
    <form onSubmit={submit} noValidate className="text-sm">
      <label htmlFor={id} className="mb-1 block text-xs font-semibold text-ink-800">
        {label}
      </label>
      <div className="flex max-w-xs gap-2">
        <input
          id={id}
          inputMode="numeric"
          autoComplete="postal-code"
          maxLength={6}
          value={draft}
          onChange={(e) => setDraft(e.target.value.replace(/\D/g, ''))}
          aria-invalid={Boolean(error)}
          className="input"
          placeholder="e.g. 560041"
        />
        <button type="submit" className="btn-secondary shrink-0 px-3">
          Check
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-1 text-xs text-danger-600">
          {error}
        </p>
      )}
    </form>
  )
}

const FINISHED = ['delivered', 'delivery_failed', 'cancelled', 'return_requested', 'returned']

/** Delivery section of an order (confirmation and order detail pages). */
export function OrderDeliveryCard({
  order,
  statusLabel,
  headingId,
}: {
  order: {
    status: string
    delivery: OrderDelivery
    delivery_message: string
    store_name: string | null
    shipments: OrderShipment[]
    items: { id: number; product_name: string }[]
  }
  statusLabel: string
  headingId: string
}) {
  const { delivery, shipments } = order
  const active = !FINISHED.includes(order.status) && order.status !== 'pending'
  const prep = shipments.length ? Math.max(...shipments.map((s) => s.prep_minutes)) : null
  const itemName = (id: number) => order.items.find((item) => item.id === id)?.product_name
  const row = 'flex flex-wrap justify-between gap-x-4 py-1'

  return (
    <section aria-labelledby={headingId} className="rounded-2xl bg-white shadow-(--shadow-card) p-5 text-sm ring-1 ring-steel-200">
      <h2 id={headingId} className="mb-2 text-base font-bold">
        Delivery
      </h2>
      {delivery.type ? (
        <>
          <DeliveryTypeHeading type={delivery.type} />
          {active && delivery.label && (
            <p className="mt-1 text-ink-900">
              Estimated delivery: <span className="font-semibold">{delivery.label.replace(/^Delivery in /, '')}</span>
            </p>
          )}
          {order.status === 'pending' && <p className="mt-1 text-ink-800">{order.delivery_message}</p>}
        </>
      ) : (
        order.delivery_message && <p className="text-ink-800">{order.delivery_message}</p>
      )}
      <dl className="mt-2 divide-y divide-steel-100">
        <div className={row}>
          <dt className="text-ink-600">Delivery status</dt>
          <dd className="font-medium">{statusLabel}</dd>
        </div>
        {delivery.type && (
          <div className={row}>
            <dt className="text-ink-600">Fast delivery</dt>
            <dd className="font-medium">{delivery.fast ? 'Eligible' : 'Not available for this order'}</dd>
          </div>
        )}
        {active && delivery.window_start && delivery.window_end && (
          <div className={row}>
            <dt className="text-ink-600">Delivery window</dt>
            <dd className="font-medium">
              {delivery.fast
                ? `${formatClock(delivery.window_start)} – ${formatClock(delivery.window_end)}`
                : delivery.label}
            </dd>
          </div>
        )}
        {active && prep !== null && delivery.type && (
          <div className={row}>
            <dt className="text-ink-600">Preparation time</dt>
            <dd className="font-medium">
              About {prep} minutes
              {delivery.estimated_ready_at && ` (ready by ${formatClock(delivery.estimated_ready_at)})`}
            </dd>
          </div>
        )}
        {shipments.length <= 1 && order.store_name && (
          <div className={row}>
            <dt className="text-ink-600">Fulfilled by</dt>
            <dd className="font-medium">
              {order.store_name}
              {shipments[0]?.store_area && `, ${shipments[0].store_area}`}
            </dd>
          </div>
        )}
      </dl>
      {shipments.length > 1 && (
        <div className="mt-3">
          <p className="font-semibold">This order ships from {shipments.length} stores</p>
          <ul className="mt-1 space-y-2">
            {shipments.map((shipment) => (
              <li key={shipment.sequence} className="rounded-md bg-steel-50 p-3">
                <p className="font-medium">
                  {shipment.store_name}
                  {shipment.store_area && `, ${shipment.store_area}`}
                </p>
                <p className="text-xs text-ink-600">
                  {shipment.item_ids.map(itemName).filter(Boolean).join(', ')}
                </p>
                {active && shipment.window_start && shipment.window_end && (
                  <p className="text-xs text-ink-800">
                    {shipment.delivery_type === 'fast' ? 'Fast' : 'Standard'} delivery · {formatClock(shipment.window_start)} –{' '}
                    {formatClock(shipment.window_end)}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

/** Cart/checkout banner: "Free delivery unlocked" or "Add ₹X more for free delivery". */
export function FreeDeliveryNote({
  fee,
  reason,
  amountToFree,
  hint,
  threshold,
}: {
  fee: string
  reason?: string
  amountToFree?: string
  hint?: string
  threshold?: string | null
}) {
  if (fee === '0.00' && reason) {
    return (
      <p className="rounded-md bg-success-600/10 px-3 py-2 text-sm font-medium text-success-600" role="status">
        Free delivery unlocked <span className="font-normal">· {reason}</span>
      </p>
    )
  }
  if (fee !== '0.00' && amountToFree && amountToFree !== '0.00') {
    return (
      <p className="rounded-md bg-amber-100 px-3 py-2 text-sm text-ink-900" role="status">
        {freeDeliveryHint(amountToFree, hint, threshold)}
      </p>
    )
  }
  return null
}
