import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'

import { Modal } from '@/components/Modal'
import { useToast } from '@/components/toast'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { ApiError } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'

import { useCancelOrder } from './api'
import { buildTimeline, orderStatusLabel, orderTone, paymentStatusLabel, type Tone } from './status'
import type { OrderDetail, OrderItem, OrderStatus, PaymentStatus } from './types'

const TONE_CLASSES: Record<Tone, string> = {
  neutral: 'bg-steel-100 text-ink-800',
  progress: 'bg-amber-100 text-ink-900',
  success: 'bg-success-600/10 text-success-600',
  danger: 'bg-danger-600/10 text-danger-600',
  warning: 'bg-amber-100 text-amber-600',
}

export function OrderStatusBadge({ order }: { order: { status: OrderStatus; payment_method: string } }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${TONE_CLASSES[orderTone(order.status)]}`}>
      {orderStatusLabel(order)}
    </span>
  )
}

export function PaymentStatusBadge({
  order,
}: {
  order: { payment_status: PaymentStatus; payment_method: string; status: OrderStatus }
}) {
  const tone: Tone =
    order.payment_status === 'paid' ? 'success' : order.payment_status === 'failed' ? 'danger' : 'neutral'
  return (
    <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${TONE_CLASSES[tone]}`}>
      {paymentStatusLabel(order)}
    </span>
  )
}

export interface SummaryTotals {
  mrp_total: string
  subtotal: string
  discount_total: string
  delivery_fee: string
  tax_total: string
  grand_total: string
}

/** Server-calculated money only: the browser formats these strings but never adds them up. */
export function PriceSummary({
  totals,
  couponCode,
  heading = 'Price details',
  footer,
}: {
  totals: SummaryTotals
  couponCode?: string
  heading?: string
  footer?: ReactNode
}) {
  const row = 'flex justify-between gap-4 py-1 text-sm'
  const mrpSavings = totals.mrp_total !== totals.subtotal
  const hasCoupon = totals.discount_total !== '0.00'
  return (
    <section aria-label={heading}>
      <h2 className="mb-2 text-base font-bold">{heading}</h2>
      <dl>
        {mrpSavings && (
          <div className={row}>
            <dt>Total MRP</dt>
            <dd>{formatPrice(totals.mrp_total)}</dd>
          </div>
        )}
        <div className={row}>
          <dt>Items subtotal</dt>
          <dd>{formatPrice(totals.subtotal)}</dd>
        </div>
        {hasCoupon && (
          <div className={`${row} text-success-600`}>
            <dt>Coupon discount{couponCode ? ` (${couponCode})` : ''}</dt>
            <dd>−{formatPrice(totals.discount_total)}</dd>
          </div>
        )}
        <div className={row}>
          <dt>Delivery fee</dt>
          <dd>{totals.delivery_fee === '0.00' ? 'Free' : formatPrice(totals.delivery_fee)}</dd>
        </div>
        <div className="mt-2 flex justify-between border-t border-steel-200 pt-3 text-base font-bold">
          <dt>Total</dt>
          <dd>{formatPrice(totals.grand_total)}</dd>
        </div>
      </dl>
      <p className="mt-1 text-xs text-ink-600">Includes GST of {formatPrice(totals.tax_total)}</p>
      {footer}
    </section>
  )
}

export function OrderItemsList({ items }: { items: OrderItem[] }) {
  return (
    <ul className="divide-y divide-steel-100">
      {items.map((item) => (
        <li key={item.id} className="flex gap-3 py-3">
          <ProductImage src={item.image} alt={item.product_name} className="size-16 shrink-0 rounded" />
          <div className="min-w-0 flex-1 text-sm">
            {item.product_slug ? (
              <Link to={`/p/${item.product_slug}`} className="font-semibold text-ink-900 hover:text-amber-600">
                {item.product_name}
              </Link>
            ) : (
              <p className="font-semibold text-ink-900">{item.product_name}</p>
            )}
            {item.variant_name && <p className="text-ink-600">{item.variant_name}</p>}
            <p className="text-xs text-ink-600">
              SKU {item.sku} · Qty {item.quantity} × {formatPrice(item.unit_price)}
              {item.unit_mrp !== item.unit_price && (
                <>
                  {' '}
                  <span className="line-through">
                    <span className="sr-only">MRP </span>
                    {formatPrice(item.unit_mrp)}
                  </span>
                </>
              )}
            </p>
          </div>
          <p className="shrink-0 text-sm font-semibold">{formatPrice(item.line_total)}</p>
        </li>
      ))}
    </ul>
  )
}

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

/** Visual order timeline built only from statuses this order has (plus the normal steps still ahead). */
export function OrderTimeline({ order }: { order: Pick<OrderDetail, 'status' | 'status_history'> }) {
  const steps = buildTimeline(order)
  if (!steps.length) return null
  return (
    <ol className="relative space-y-4" aria-label="Order progress">
      {steps.map((step, index) => {
        const done = step.state !== 'upcoming'
        const cancelled = step.status === 'cancelled' || step.status === 'returned'
        const dot = cancelled ? 'bg-danger-600' : done ? 'bg-success-600' : 'bg-white ring-2 ring-steel-200'
        return (
          <li key={step.status} className="relative flex gap-3" aria-current={step.state === 'current' ? 'step' : undefined}>
            {index < steps.length - 1 && (
              <span
                aria-hidden
                className={`absolute left-[7px] top-5 h-[calc(100%+0.25rem)] w-0.5 ${steps[index + 1]!.state !== 'upcoming' ? 'bg-success-600' : 'bg-steel-200'}`}
              />
            )}
            <span aria-hidden className={`relative mt-1 size-4 shrink-0 rounded-full ${dot}`} />
            <div className="text-sm">
              <p className={done ? 'font-semibold text-ink-900' : 'text-ink-600'}>
                {step.label}
                {step.state === 'current' && <span className="ml-2 text-xs font-normal text-amber-600">Current</span>}
                <span className="sr-only">{done ? ' — completed' : ' — upcoming'}</span>
              </p>
              {step.at && <p className="text-xs text-ink-600">{formatDateTime(step.at)}</p>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

const CANCEL_REASONS = [
  'Ordered by mistake',
  'Need to change items or quantity',
  'Need to change the delivery address',
  'Found a better price',
  'Delivery will take too long',
  'Other',
]

export function CancelOrderDialog({ order, open, onClose }: { order: OrderDetail; open: boolean; onClose: () => void }) {
  const cancel = useCancelOrder(order.order_number)
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [details, setDetails] = useState('')
  const [error, setError] = useState('')
  const paid = order.payment_status === 'paid'

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!reason) {
      setError('Please choose a reason.')
      return
    }
    const text = reason === 'Other' && details.trim() ? `Other: ${details.trim()}` : reason
    setError('')
    try {
      await cancel.mutateAsync(text)
      toast.show(`Order ${order.order_number} cancelled`)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not cancel the order. Please try again.')
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Cancel this order?">
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-ink-800">
          {paid
            ? `A refund of ${formatPrice(order.grand_total)} will be requested to your original payment method.`
            : order.payment_method === 'cod'
              ? 'Nothing has been charged for this cash-on-delivery order.'
              : 'No payment has been taken for this order.'}
        </p>
        <fieldset>
          <legend className="label">Why are you cancelling?</legend>
          <div className="space-y-1.5">
            {CANCEL_REASONS.map((option) => (
              <label key={option} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-steel-50">
                <input
                  type="radio"
                  name="cancel-reason"
                  value={option}
                  checked={reason === option}
                  onChange={() => setReason(option)}
                  className="size-4 accent-amber-600"
                />
                {option}
              </label>
            ))}
          </div>
        </fieldset>
        {reason === 'Other' && (
          <div>
            <label htmlFor="cancel-details" className="label">
              Tell us more (optional)
            </label>
            <textarea
              id="cancel-details"
              value={details}
              onChange={(e) => setDetails(e.target.value)}
              maxLength={200}
              rows={2}
              className="input"
            />
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger-600">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">
            Keep order
          </button>
          <button type="submit" disabled={cancel.isPending} className="btn-dark flex-1">
            {cancel.isPending ? 'Cancelling…' : 'Cancel order'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
