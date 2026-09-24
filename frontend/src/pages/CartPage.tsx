import { Link } from 'react-router'

import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { TrashIcon } from '@/components/icons'
import { QuantityStepper } from '@/components/QuantityStepper'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { useCart, useRemoveCartItem, useUpdateCartItem, type CartLine } from '@/features/cart/api'
import { ApiError, isUnauthorized } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

function Line({ line }: { line: CartLine }) {
  const update = useUpdateCartItem()
  const remove = useRemoveCartItem()
  const toast = useToast()
  const onError = (error: unknown) =>
    toast.show(error instanceof ApiError ? error.message : 'Could not update your cart.', { tone: 'error' })
  const busy = update.isPending || remove.isPending

  return (
    <li className="flex gap-4 py-4">
      <div className="min-w-0 flex-1">
        <Link to={`/p/${line.product_slug}`} className="font-semibold text-ink-900 hover:text-amber-600">
          {line.product_name}
        </Link>
        {line.variant_name && <p className="text-sm text-ink-600">{line.variant_name}</p>}
        <p className="text-xs text-ink-600">SKU {line.sku}</p>
        <p className="mt-1 text-sm">
          {formatPrice(line.unit_price)}
          {line.unit_mrp !== line.unit_price && (
            <span className="ml-2 text-xs text-ink-600 line-through">{formatPrice(line.unit_mrp)}</span>
          )}
        </p>
        {line.price_changed && (
          <p className="mt-1 text-xs font-medium text-amber-600">
            Price changed since you added this (was {formatPrice(line.price_at_add)}).
          </p>
        )}
        {!line.purchasable ? (
          <p className="mt-1 text-xs font-semibold text-danger-600">No longer available — please remove it.</p>
        ) : !line.in_stock ? (
          <p className="mt-1 text-xs font-semibold text-danger-600">
            {line.available_quantity > 0 ? `Only ${line.available_quantity} available` : 'Out of stock'}
          </p>
        ) : null}
        <div className="mt-2 flex items-center gap-3">
          <QuantityStepper
            label={`Quantity of ${line.product_name}`}
            value={line.quantity}
            max={Math.max(line.quantity, line.available_quantity)}
            disabled={busy}
            onChange={(quantity) => update.mutate({ itemId: line.id, quantity }, { onError })}
          />
          <button
            type="button"
            onClick={() =>
              remove.mutate(line.id, { onSuccess: () => toast.show(`Removed ${line.product_name}`), onError })
            }
            disabled={busy}
            className="inline-flex items-center gap-1 text-sm text-ink-600 hover:text-danger-600"
          >
            <TrashIcon className="size-4" />
            Remove<span className="sr-only"> {line.product_name}</span>
          </button>
        </div>
      </div>
      <p className="shrink-0 font-semibold">{formatPrice(line.line_total)}</p>
    </li>
  )
}

export function CartPage() {
  usePageMeta('Your cart')
  const { status } = useAuth()
  const cart = useCart()

  if (status === 'loading') return <PageSpinner />
  if (status === 'anonymous') {
    return (
      <div className="container-page py-10">
        <SignInPrompt message="Sign in to see your cart and add products." next="/cart" />
      </div>
    )
  }
  if (cart.isPending) return <PageSpinner label="Loading your cart…" />
  if (cart.isError) {
    return (
      <div className="container-page py-10">
        {isUnauthorized(cart.error) ? (
          <SignInPrompt message="Your session has ended. Please sign in again." next="/cart" />
        ) : (
          <ErrorState error={cart.error} onRetry={() => cart.refetch()} title="Couldn’t load your cart" />
        )}
      </div>
    )
  }

  const { items, totals, issues } = cart.data
  if (!items.length) {
    return (
      <div className="container-page py-10">
        <EmptyState
          title="Your cart is empty"
          action={
            <Link to="/products" className="btn-primary">
              Start shopping
            </Link>
          }
        >
          Browse categories or search to find what you need.
        </EmptyState>
      </div>
    )
  }

  const row = 'flex justify-between py-1 text-sm'
  return (
    <div className="container-page grid gap-6 py-6 lg:grid-cols-[1fr_22rem]">
      <section aria-labelledby="cart-heading" className="rounded-lg bg-white px-5 ring-1 ring-steel-200">
        <h1 id="cart-heading" className="border-b border-steel-100 py-4 text-xl font-bold">
          Cart ({items.length} {items.length === 1 ? 'item' : 'items'})
        </h1>
        {issues.length > 0 && (
          <ul role="alert" className="mt-4 space-y-1 rounded-md bg-amber-100 p-3 text-sm text-ink-900">
            {issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        )}
        <ul className="divide-y divide-steel-100">
          {items.map((line) => (
            <Line key={line.id} line={line} />
          ))}
        </ul>
      </section>
      <aside aria-labelledby="summary-heading" className="h-fit rounded-lg bg-white p-5 ring-1 ring-steel-200 lg:sticky lg:top-32">
        <h2 id="summary-heading" className="mb-3 text-lg font-bold">
          Price details
        </h2>
        <dl>
          <div className={row}>
            <dt>Total MRP</dt>
            <dd>{formatPrice(totals.mrp_total)}</dd>
          </div>
          <div className={`${row} text-success-600`}>
            <dt>Discount on MRP</dt>
            <dd>−{formatPrice(totals.savings_vs_mrp)}</dd>
          </div>
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
        <button type="button" disabled className="btn-primary mt-4 w-full">
          Checkout — coming soon
        </button>
        <p className="mt-2 text-xs text-ink-600">
          Checkout, address selection and delivery time are being added next. Your cart is saved to your account.
        </p>
      </aside>
    </div>
  )
}
