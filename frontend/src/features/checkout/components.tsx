import { useState, type FormEvent } from 'react'

import { useToast } from '@/components/toast'
import { useUpdateAddress, type Address } from '@/features/addresses/api'
import { useRemoveCartItem, useUpdateCartItem, type CartLine } from '@/features/cart/api'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { ApiError } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'

import type { CheckoutUnloading } from './api'

/** Optional paid unloading at ground level; the server decides whether it's offered and its price. */
export function UnloadingCard({
  unloading,
  onChange,
  busy,
}: {
  unloading: CheckoutUnloading
  onChange: (selected: boolean) => void
  busy: boolean
}) {
  if (!unloading.available) {
    return <p className="text-sm text-ink-600">{unloading.message}</p>
  }
  return (
    <div className="flex flex-col gap-3 rounded-md p-3 ring-1 ring-steel-200 sm:flex-row sm:items-center" data-testid="unloading-card">
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold">
          Unloading service · {formatPrice(unloading.fee)}
          {unloading.selected && <span className="ml-2 text-xs font-semibold text-success-600">Added</span>}
        </p>
        <p className="text-xs text-ink-600">{unloading.message}</p>
      </div>
      <button
        type="button"
        onClick={() => onChange(!unloading.selected)}
        disabled={busy}
        className={unloading.selected ? 'btn-secondary shrink-0' : 'btn-primary shrink-0'}
      >
        {unloading.selected ? 'Remove' : 'Add'} <span className="sr-only">unloading service</span>
      </button>
    </div>
  )
}

// Format only (state code, PAN, entity number, "Z", check character); not verified with the GST portal.
export const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/

/** Optional GSTIN for a tax invoice, saved on the delivery address (the invoice prints it). */
export function GstinBox({ address }: { address: Address }) {
  const update = useUpdateAddress()
  const toast = useToast()
  const [value, setValue] = useState(address.gstin ?? '')
  const [error, setError] = useState<string | null>(null)
  const cleaned = value.trim().toUpperCase()

  function save(event: FormEvent) {
    event.preventDefault()
    if (cleaned && !GSTIN_RE.test(cleaned)) {
      setError('Enter a valid 15-character GSTIN, e.g. 29ABCDE1234F1Z5.')
      return
    }
    setError(null)
    update.mutate(
      { id: address.id, input: { gstin: cleaned } },
      {
        onSuccess: () => toast.show(cleaned ? 'GSTIN saved for this address' : 'GSTIN removed'),
        onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not save the GSTIN.'),
      },
    )
  }

  return (
    <form onSubmit={save} noValidate className="mt-3 space-y-1">
      <label htmlFor="checkout-gstin" className="label">
        GSTIN <span className="font-normal text-ink-600">(optional, for a GST invoice)</span>
      </label>
      <div className="flex gap-2">
        <input
          id="checkout-gstin"
          value={value}
          onChange={(e) => setValue(e.target.value.toUpperCase())}
          maxLength={15}
          autoComplete="off"
          placeholder="29ABCDE1234F1Z5"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'checkout-gstin-error' : 'checkout-gstin-help'}
          className="input min-w-0 flex-1 uppercase"
        />
        <button type="submit" className="btn-secondary shrink-0" disabled={update.isPending || cleaned === (address.gstin ?? '')}>
          {update.isPending ? 'Saving…' : 'Save'}
        </button>
      </div>
      {error ? (
        <p id="checkout-gstin-error" role="alert" className="text-xs text-danger-600">
          {error}
        </p>
      ) : (
        <p id="checkout-gstin-help" className="text-xs text-ink-600">
          We check the format only; it isn’t verified with the GST portal.
        </p>
      )}
    </form>
  )
}

/** One checkout line: picture, option, MRP vs price, quantity controls and remove (the cart API re-prices). */
export function CheckoutItem({ line, editable, onChanged }: { line: CartLine; editable: boolean; onChanged: () => void }) {
  const updateItem = useUpdateCartItem()
  const removeItem = useRemoveCartItem()
  const busy = updateItem.isPending || removeItem.isPending
  const max = Math.min(line.max_order_quantity, Math.max(line.available_quantity, line.quantity))
  const setQuantity = (quantity: number) => updateItem.mutate({ itemId: line.id, quantity }, { onSuccess: onChanged })
  const discounted = line.unit_mrp && line.unit_price && line.unit_mrp !== line.unit_price
  return (
    <li className="flex gap-3 py-3">
      <ProductImage src={line.image} alt={line.product_name} className="size-16 shrink-0 rounded" />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-medium">{line.product_name}</p>
        {line.variant_name && <p className="text-xs text-ink-600">{line.variant_name}</p>}
        <p className="mt-0.5 text-xs">
          <span className="font-semibold">{formatPrice(line.unit_price)}</span>
          {discounted && <span className="ml-1.5 text-ink-600 line-through">MRP {formatPrice(line.unit_mrp)}</span>}
        </p>
        {editable ? (
          <div className="mt-2 flex items-center gap-3">
            <div className="inline-flex items-center rounded-md ring-1 ring-steel-200">
              <button
                type="button"
                className="size-8 font-bold disabled:opacity-40"
                onClick={() => setQuantity(line.quantity - 1)}
                disabled={busy || line.quantity <= 1}
                aria-label={`Decrease quantity of ${line.product_name}`}
              >
                −
              </button>
              <span className="min-w-8 text-center tabular-nums" aria-live="polite">
                {line.quantity}
              </span>
              <button
                type="button"
                className="size-8 font-bold disabled:opacity-40"
                onClick={() => setQuantity(line.quantity + 1)}
                disabled={busy || line.quantity >= max}
                aria-label={`Increase quantity of ${line.product_name}`}
              >
                +
              </button>
            </div>
            <button
              type="button"
              onClick={() => removeItem.mutate(line.id, { onSuccess: onChanged })}
              disabled={busy}
              className="text-xs font-semibold text-danger-600 hover:underline"
            >
              Remove <span className="sr-only">{line.product_name}</span>
            </button>
          </div>
        ) : (
          <p className="text-xs text-ink-600">Qty {line.quantity}</p>
        )}
      </div>
      <p className="shrink-0 text-sm font-semibold">{line.line_total ? formatPrice(line.line_total) : '—'}</p>
    </li>
  )
}
