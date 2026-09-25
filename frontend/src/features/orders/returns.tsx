import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'

import { Modal } from '@/components/Modal'
import { useToast } from '@/components/toast'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { ApiError } from '@/lib/api/errors'
import { formatDate, formatPrice } from '@/lib/format'

import { useCancelReturn, useCreateReturn, useReorder } from './api'
import type { OrderDetail, ReorderLine, ReturnReason, ReturnRequest, ReturnStatus } from './types'

const RETURN_REASONS: { value: ReturnReason; label: string }[] = [
  { value: 'damaged', label: 'Arrived damaged' },
  { value: 'defective', label: 'Defective / not working' },
  { value: 'wrong_item', label: 'Wrong item delivered' },
  { value: 'not_as_described', label: 'Not as described' },
  { value: 'no_longer_needed', label: 'No longer needed' },
  { value: 'other', label: 'Other' },
]

/** What happens next, in the customer's words (the status label alone is terse). */
const NEXT_STEP: Record<ReturnStatus, string> = {
  requested: 'We’re reviewing your request.',
  approved: 'Approved. Keep the items ready for pickup or drop them at the store.',
  rejected: 'This return was not accepted.',
  received: 'We received the items. Your refund has been initiated.',
  cancelled: 'You cancelled this request.',
}

const STATUS_CLASSES: Record<ReturnStatus, string> = {
  requested: 'bg-amber-100 text-amber-600',
  approved: 'bg-amber-100 text-ink-900',
  rejected: 'bg-danger-600/10 text-danger-600',
  received: 'bg-success-600/10 text-success-600',
  cancelled: 'bg-steel-100 text-ink-800',
}

export function ReturnDialog({ order, open, onClose }: { order: OrderDetail; open: boolean; onClose: () => void }) {
  const create = useCreateReturn(order.order_number)
  const toast = useToast()
  const returnable = order.items.filter((item) => item.returnable_quantity > 0)
  const [quantities, setQuantities] = useState<Record<number, number>>({})
  const [reason, setReason] = useState<ReturnReason | ''>('')
  const [details, setDetails] = useState('')
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    const items = Object.entries(quantities)
      .filter(([, quantity]) => quantity > 0)
      .map(([id, quantity]) => ({ order_item_id: Number(id), quantity }))
    if (!items.length) return setError('Choose at least one item to return.')
    if (!reason) return setError('Please choose a reason.')
    if (reason === 'other' && !details.trim()) return setError('Please describe the problem.')
    setError('')
    try {
      const created = await create.mutateAsync({ reason, details: details.trim(), items })
      toast.show(`Return ${created.return_number} requested`)
      setQuantities({})
      setReason('')
      setDetails('')
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not request the return. Please try again.')
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Return items">
      <form onSubmit={submit} className="space-y-4">
        {order.return_window_ends_at && (
          <p className="text-sm text-ink-800">Returns are open until {formatDate(order.return_window_ends_at)}.</p>
        )}
        <fieldset>
          <legend className="label">Which items?</legend>
          <ul className="divide-y divide-steel-100">
            {returnable.map((item) => {
              const id = `return-qty-${item.id}`
              return (
                <li key={item.id} className="flex items-center gap-3 py-2">
                  <ProductImage src={item.image} alt="" className="size-12 shrink-0 rounded" />
                  <label htmlFor={id} className="min-w-0 flex-1 text-sm">
                    <span className="block font-medium">{item.product_name}</span>
                    {item.variant_name && <span className="block text-xs text-ink-600">{item.variant_name}</span>}
                    <span className="block text-xs text-ink-600">You can return up to {item.returnable_quantity}</span>
                  </label>
                  <select
                    id={id}
                    aria-label={`Return quantity for ${item.product_name}`}
                    value={quantities[item.id] ?? 0}
                    onChange={(e) => setQuantities((q) => ({ ...q, [item.id]: Number(e.target.value) }))}
                    className="input w-20"
                  >
                    {Array.from({ length: item.returnable_quantity + 1 }, (_, n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </li>
              )
            })}
          </ul>
        </fieldset>
        <fieldset>
          <legend className="label">Why are you returning?</legend>
          <div className="space-y-1.5">
            {RETURN_REASONS.map((option) => (
              <label key={option.value} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-steel-50">
                <input
                  type="radio"
                  name="return-reason"
                  value={option.value}
                  checked={reason === option.value}
                  onChange={() => setReason(option.value)}
                  className="size-4 accent-amber-600"
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
        <div>
          <label htmlFor="return-details" className="label">
            Details {reason === 'other' ? '' : '(optional)'}
          </label>
          <textarea
            id="return-details"
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            maxLength={500}
            rows={2}
            className="input"
          />
        </div>
        <p className="text-xs text-ink-600">
          The refund is what you paid for these items after discounts; the delivery fee is not refunded. It starts once the
          store receives the items.
        </p>
        {error && (
          <p role="alert" className="text-sm text-danger-600">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">
            Close
          </button>
          <button type="submit" disabled={create.isPending} className="btn-dark flex-1">
            {create.isPending ? 'Sending…' : 'Request return'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export function ReturnCard({ ret, showOrder = false }: { ret: ReturnRequest; showOrder?: boolean }) {
  const cancel = useCancelReturn(ret.order_number)
  const toast = useToast()
  const [error, setError] = useState('')

  async function withdraw() {
    setError('')
    try {
      await cancel.mutateAsync(ret.return_number)
      toast.show(`Return ${ret.return_number} cancelled`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not cancel the return. Please try again.')
    }
  }

  return (
    <article aria-label={`Return ${ret.return_number}`} className="rounded-lg bg-white p-4 text-sm ring-1 ring-steel-200">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">
          Return {ret.return_number}
          {showOrder && (
            <>
              {' · '}
              <Link to={`/account/orders/${ret.order_number}`} className="font-normal text-amber-600 hover:underline">
                Order {ret.order_number}
              </Link>
            </>
          )}
        </p>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS_CLASSES[ret.status]}`}>{ret.status_label}</span>
      </div>
      <p className="mt-1 text-ink-800">{NEXT_STEP[ret.status]}</p>
      {ret.decision_note && ret.status !== 'cancelled' && <p className="mt-1 text-ink-600">Store note: {ret.decision_note}</p>}
      <ul className="mt-2 space-y-1">
        {ret.items.map((item) => (
          <li key={item.order_item_id} className="flex justify-between gap-3">
            <span>
              {item.quantity} × {item.product_name}
              {item.variant_name && <span className="text-ink-600"> ({item.variant_name})</span>}
            </span>
            <span>{formatPrice(item.refund_amount)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 flex justify-between border-t border-steel-100 pt-2 font-semibold">
        <span>
          Refund {ret.status === 'received' ? '' : '(once received)'}
          <span className="block text-xs font-normal text-ink-600">{ret.refund_method_label}</span>
        </span>
        <span>{formatPrice(ret.refund_amount)}</span>
      </p>
      <p className="mt-1 text-xs text-ink-600">
        Requested {formatDate(ret.created_at)} · Reason: {ret.reason_label}
      </p>
      {ret.can_cancel && (
        <button type="button" onClick={() => void withdraw()} disabled={cancel.isPending} className="btn-secondary mt-3">
          {cancel.isPending ? 'Cancelling…' : 'Cancel return request'}
        </button>
      )}
      {error && (
        <p role="alert" className="mt-2 text-danger-600">
          {error}
        </p>
      )}
    </article>
  )
}

/** "Buy again": the server adds what it can (today's prices, stock and order limits) and says what it skipped. */
export function BuyAgainButton({ orderNumber, className = 'btn-primary w-full' }: { orderNumber: string; className?: string }) {
  const reorder = useReorder(orderNumber)
  const toast = useToast()
  const [skipped, setSkipped] = useState<ReorderLine[]>([])
  const [error, setError] = useState('')

  async function run() {
    setError('')
    try {
      const result = await reorder.mutateAsync()
      setSkipped(result.skipped)
      const units = result.added.reduce((sum, line) => sum + line.added, 0)
      if (units) toast.show(`Added ${units} ${units === 1 ? 'item' : 'items'} to your cart`, { action: { label: 'View cart', to: '/cart' } })
      else toast.show('Nothing could be added to your cart', { tone: 'error' })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not add the items. Please try again.')
    }
  }

  return (
    <div>
      <button type="button" onClick={() => void run()} disabled={reorder.isPending} className={className}>
        {reorder.isPending ? 'Adding to cart…' : 'Buy again'}
      </button>
      {skipped.length > 0 && (
        <div role="status" className="mt-2 rounded-md bg-amber-100 px-3 py-2 text-sm">
          <p className="font-semibold">Not everything was added:</p>
          <ul className="mt-1 list-disc pl-5">
            {skipped.map((line) => (
              <li key={line.sku}>
                {line.name}: {line.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger-600">
          {error}
        </p>
      )}
    </div>
  )
}
