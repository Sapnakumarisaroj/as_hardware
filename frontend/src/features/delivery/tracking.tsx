import { useEffect, useState } from 'react'

import { PinIcon } from '@/components/icons'
import { fetchPrivateImage, useNewDeliveryCode } from '@/features/orders/api'
import { ApiError } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'

import { formatClock } from './format'
import type { DeliveryCode, OrderShipment, ShipmentStatus } from './types'

const STEPS: { status: ShipmentStatus; label: string }[] = [
  { status: 'assigned', label: 'Delivery partner assigned' },
  { status: 'picked_up', label: 'Picked up from the store' },
  { status: 'out_for_delivery', label: 'Out for delivery' },
  { status: 'delivered', label: 'Delivered' },
]
const RANK: Record<ShipmentStatus, number> = {
  pending: -1,
  assigned: 0,
  picked_up: 1,
  out_for_delivery: 2,
  delivered: 3,
  failed: 2,
  cancelled: -1,
}

function when(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  const day = date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' })
  return `${day}, ${formatClock(iso)}`
}

/** The code to tell the rider at the door, large enough to read out, with its validity. */
function DeliveryCodeBox({
  code,
  orderNumber,
  sequence,
}: {
  code: DeliveryCode
  orderNumber: string
  sequence: number
}) {
  const renew = useNewDeliveryCode(orderNumber)
  const [error, setError] = useState('')

  async function request() {
    setError('')
    try {
      await renew.mutateAsync(sequence)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not get a new code. Please try again.')
    }
  }

  const usable = code.state === 'active' && code.code
  return (
    <div className="rounded-lg bg-amber-100 p-4" role="group" aria-label="Delivery code">
      <p className="text-sm font-semibold text-ink-900">Your delivery code</p>
      {usable ? (
        <>
          <p className="mt-1 font-mono text-3xl font-bold tracking-[0.3em] text-ink-950" aria-live="polite">
            <span className="sr-only">Code: {code.code!.split('').join(' ')}</span>
            <span aria-hidden="true">{code.code}</span>
          </p>
          <p className="mt-1 text-xs text-ink-800">
            Give this code to the delivery partner only when you receive your order.
            {code.expires_at && ` Valid until ${formatClock(code.expires_at)}.`} Never share it on a call or message.
          </p>
        </>
      ) : (
        <p className="mt-1 text-sm text-ink-900">
          {code.state === 'locked'
            ? 'Too many wrong codes were entered, so this code was blocked.'
            : 'Your code has expired.'}{' '}
          Get a new code to receive your order.
        </p>
      )}
      {(!usable || code.can_request_new) && (
        <button
          type="button"
          onClick={() => void request()}
          disabled={renew.isPending}
          className={`mt-3 ${usable ? 'text-sm font-semibold text-ink-800 underline' : 'btn-primary'}`}
        >
          {renew.isPending ? 'Getting a new code…' : 'Get a new code'}
        </button>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs text-danger-600">
          {error}
        </p>
      )}
    </div>
  )
}

/** Shows the photo taken at delivery. It is fetched only when asked for, with the session token. */
function DeliveryPhoto({ orderNumber, sequence }: { orderNumber: string; sequence: number }) {
  const [url, setUrl] = useState<string | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url])

  async function show() {
    setState('loading')
    try {
      setUrl(await fetchPrivateImage(`/orders/${encodeURIComponent(orderNumber)}/shipments/${sequence}/proof/`))
      setState('idle')
    } catch {
      setState('error')
    }
  }

  if (url) {
    return <img src={url} alt="Photo taken when your order was delivered" className="mt-2 max-h-80 rounded-md ring-1 ring-steel-200" />
  }
  return (
    <div className="mt-2">
      <button type="button" onClick={() => void show()} disabled={state === 'loading'} className="btn-secondary px-3 py-1.5 text-sm">
        {state === 'loading' ? 'Loading photo…' : 'View delivery photo'}
      </button>
      {state === 'error' && (
        <p role="alert" className="mt-1 text-xs text-danger-600">
          The photo couldn’t be loaded. Please try again.
        </p>
      )}
    </div>
  )
}

function Steps({ shipment }: { shipment: OrderShipment }) {
  const rank = RANK[shipment.status]
  const times: Partial<Record<ShipmentStatus, string | null>> = {
    picked_up: shipment.picked_up_at,
    out_for_delivery: shipment.out_for_delivery_at,
    delivered: shipment.delivered_at,
  }
  const failed = shipment.status === 'failed'
  return (
    <ol className="space-y-2" aria-label="Delivery progress">
      {STEPS.map((step, index) => {
        const done = failed ? index < rank : index <= rank
        const current = !failed && index === rank && shipment.status !== 'delivered'
        return (
          <li key={step.status} className="flex items-start gap-2 text-sm" aria-current={current ? 'step' : undefined}>
            <span
              aria-hidden
              className={`mt-1 size-3 shrink-0 rounded-full ${done ? 'bg-success-600' : 'bg-white ring-2 ring-steel-200'}`}
            />
            <span className={done ? 'font-semibold text-ink-900' : 'text-ink-600'}>
              {step.label}
              <span className="sr-only">{done ? ' — done' : ' — not yet'}</span>
              {current && <span className="ml-2 text-xs font-normal text-amber-700">Now</span>}
              {done && times[step.status] && (
                <span className="ml-2 text-xs font-normal text-ink-600">{when(times[step.status] ?? null)}</span>
              )}
            </span>
          </li>
        )
      })}
      {failed && (
        <li className="flex items-start gap-2 text-sm" aria-current="step">
          <span aria-hidden className="mt-1 size-3 shrink-0 rounded-full bg-danger-600" />
          <span className="font-semibold text-danger-600">
            Delivery attempt failed
            {shipment.failure?.failed_at && (
              <span className="ml-2 text-xs font-normal text-ink-600">{when(shipment.failure.failed_at)}</span>
            )}
          </span>
        </li>
      )}
    </ol>
  )
}

function Shipment({
  shipment,
  orderNumber,
  itemNames,
  split,
}: {
  shipment: OrderShipment
  orderNumber: string
  itemNames: string[]
  split: boolean
}) {
  const { rider, failure } = shipment
  if (shipment.status === 'cancelled') return null
  return (
    <li className={split ? 'rounded-md bg-steel-50 p-4' : ''}>
      {split && (
        <p className="mb-2 text-sm font-semibold">
          From {shipment.store_name}
          <span className="block text-xs font-normal text-ink-600">{itemNames.join(', ')}</span>
        </p>
      )}
      {shipment.status === 'pending' ? (
        <p className="text-sm text-ink-800">
          {shipment.delivery_attempts > 0
            ? 'The store is arranging another delivery attempt.'
            : 'The store is preparing your order. A delivery partner will be assigned when it is packed.'}
        </p>
      ) : (
        <Steps shipment={shipment} />
      )}

      {failure && (
        <div role="alert" className="mt-3 rounded-md bg-danger-600/10 p-3 text-sm">
          <p className="font-semibold text-danger-600">We couldn’t deliver this: {failure.reason.toLowerCase()}.</p>
          <p className="mt-1 text-ink-800">{failure.next_step}</p>
        </div>
      )}

      {shipment.delivery_code && (
        <div className="mt-3">
          <DeliveryCodeBox code={shipment.delivery_code} orderNumber={orderNumber} sequence={shipment.sequence} />
        </div>
      )}

      {shipment.amount_to_pay && (
        <p className="mt-3 rounded-md bg-steel-50 px-3 py-2 text-sm text-ink-900">
          Cash on delivery: pay <span className="font-bold">{formatPrice(shipment.amount_to_pay)}</span> to the delivery
          partner (cash or UPI).
        </p>
      )}

      {rider && !['delivered', 'failed'].includes(shipment.status) && (
        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="flex items-center gap-1.5">
            <PinIcon className="size-4 text-amber-700" />
            <span>
              <span className="font-semibold">{rider.name}</span> · {rider.vehicle}
            </span>
          </span>
          {rider.phone && (
            <a href={`tel:${rider.phone}`} className="font-semibold text-amber-700 hover:underline">
              Call {rider.name}
              <span className="sr-only"> on {rider.phone}</span>
            </a>
          )}
        </p>
      )}

      {shipment.status === 'delivered' && (
        <div className="mt-3 text-sm">
          <p className="font-semibold text-success-600">
            Delivered{shipment.delivered_at && ` on ${when(shipment.delivered_at)}`}
          </p>
          {shipment.received_by && <p className="text-ink-600">Received by {shipment.received_by}</p>}
          {shipment.proof_available && <DeliveryPhoto orderNumber={orderNumber} sequence={shipment.sequence} />}
        </div>
      )}
      {shipment.delivery_attempts > 1 && shipment.status !== 'delivered' && (
        <p className="mt-2 text-xs text-ink-600">Delivery attempt {shipment.delivery_attempts}</p>
      )}
    </li>
  )
}

/** Live delivery progress per shipment: rider, delivery code, cash due, completion or failure. */
export function DeliveryTracking({
  order,
}: {
  order: {
    order_number: string
    status: string
    shipments: OrderShipment[]
    items: { id: number; product_name: string }[]
  }
}) {
  const shipments = order.shipments.filter((shipment) => shipment.status !== 'cancelled')
  const started = shipments.some((shipment) => shipment.status !== 'pending' || shipment.delivery_attempts > 0)
  if (!started || ['pending', 'cancelled'].includes(order.status)) return null
  const names = (shipment: OrderShipment) =>
    shipment.item_ids.map((id) => order.items.find((item) => item.id === id)?.product_name ?? '').filter(Boolean)

  return (
    <section aria-labelledby="tracking-heading" className="rounded-2xl bg-white shadow-(--shadow-card) p-5 ring-1 ring-steel-200">
      <h2 id="tracking-heading" className="mb-3 text-base font-bold">
        Track delivery
      </h2>
      <ul className="space-y-3">
        {shipments.map((shipment) => (
          <Shipment
            key={shipment.sequence}
            shipment={shipment}
            orderNumber={order.order_number}
            itemNames={names(shipment)}
            split={shipments.length > 1}
          />
        ))}
      </ul>
    </section>
  )
}
