import { Link, useNavigate } from 'react-router'

import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { HeartIcon, TrashIcon } from '@/components/icons'
import { QuantityStepper } from '@/components/QuantityStepper'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { useCart, useRemoveCartItem, useUpdateCartItem, type CartLine } from '@/features/cart/api'
import { useAddresses } from '@/features/addresses/api'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { useCartEstimate } from '@/features/delivery/api'
import { DeliveryEstimate, PincodeForm } from '@/features/delivery/components'
import { usePincode } from '@/features/delivery/location'
import { CartOfferNotes } from '@/features/offers/components'
import { PriceSummary } from '@/features/orders/components'
import { useAddToWishlist } from '@/features/wishlist/api'
import { ApiError, isUnauthorized } from '@/lib/api/errors'
import { formatPercent, formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

function attributeText(attributes: CartLine['attributes']): string {
  return Object.entries(attributes ?? {})
    .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${value}`)
    .join(' · ')
}

function StockMessage({ line }: { line: CartLine }) {
  if (!line.purchasable) {
    return <p className="text-xs font-semibold text-danger-600">No longer available — please remove it.</p>
  }
  if (!line.in_stock) {
    return (
      <p className="text-xs font-semibold text-danger-600">
        {line.available_quantity > 0
          ? `Only ${line.available_quantity} available — reduce the quantity to continue.`
          : 'Out of stock — remove it or save it for later.'}
      </p>
    )
  }
  if (line.available_quantity <= 5) {
    return <p className="text-xs font-semibold text-amber-600">Only {line.available_quantity} left</p>
  }
  return <p className="text-xs font-semibold text-success-600">In stock</p>
}

function Line({ line }: { line: CartLine }) {
  const update = useUpdateCartItem()
  const remove = useRemoveCartItem()
  const saveForLater = useAddToWishlist()
  const toast = useToast()
  const onError = (error: unknown) =>
    toast.show(error instanceof ApiError ? error.message : 'Could not update your cart.', { tone: 'error' })
  const busy = update.isPending || remove.isPending || saveForLater.isPending
  const percent = formatPercent(line.discount_percent)
  const attrs = attributeText(line.attributes)
  const max = Math.max(line.quantity, Math.min(line.available_quantity, line.max_order_quantity))

  function moveToWishlist() {
    saveForLater.mutate(line.product_id, {
      onSuccess: () =>
        remove.mutate(line.id, {
          onSuccess: () => toast.show(`Saved for later: ${line.product_name}`, { action: { label: 'View', to: '/wishlist' } }),
          onError,
        }),
      onError,
    })
  }

  return (
    <li className="flex gap-3 py-4 sm:gap-4">
      <Link to={`/p/${line.product_slug}`} tabIndex={-1} aria-hidden="true" className="shrink-0">
        <ProductImage src={line.image} alt={line.product_name} className="size-20 rounded sm:size-24" />
      </Link>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
          <div className="min-w-0">
            {line.brand_name && <p className="text-xs uppercase tracking-wide text-ink-600">{line.brand_name}</p>}
            <Link to={`/p/${line.product_slug}`} className="font-semibold text-ink-900 hover:text-amber-600">
              {line.product_name}
            </Link>
            {line.variant_name && <p className="text-sm text-ink-800">{line.variant_name}</p>}
            {attrs && <p className="text-xs capitalize text-ink-600">{attrs}</p>}
            <p className="text-xs text-ink-600">SKU {line.sku}</p>
          </div>
          <div className="text-right">
            <p className="font-bold">{line.line_total ? formatPrice(line.line_total) : '—'}</p>
            {line.line_mrp_total && line.line_mrp_total !== line.line_total && (
              <p className="text-xs text-ink-600 line-through">
                <span className="sr-only">MRP </span>
                {formatPrice(line.line_mrp_total)}
              </p>
            )}
          </div>
        </div>
        <p className="mt-1 text-sm">
          {formatPrice(line.unit_price)} each
          {percent && (
            <>
              <span className="ml-2 text-xs text-ink-600 line-through">{formatPrice(line.unit_mrp)}</span>
              <span className="ml-2 text-xs font-semibold text-success-600">{percent} off</span>
            </>
          )}
        </p>
        {line.price_changed && (
          <p className="mt-1 text-xs font-medium text-amber-600">
            Price changed since you added this (was {formatPrice(line.price_at_add)}).
          </p>
        )}
        <div className="mt-1">
          <StockMessage line={line} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
          <QuantityStepper
            label={`Quantity of ${line.product_name}`}
            value={line.quantity}
            max={max}
            disabled={busy || !line.purchasable}
            onChange={(quantity) => update.mutate({ itemId: line.id, quantity }, { onError })}
          />
          <button
            type="button"
            onClick={moveToWishlist}
            disabled={busy}
            className="inline-flex min-h-9 items-center gap-1 text-sm text-ink-600 hover:text-ink-900"
          >
            <HeartIcon className="size-4" />
            Save for later<span className="sr-only"> {line.product_name}</span>
          </button>
          <button
            type="button"
            onClick={() => remove.mutate(line.id, { onSuccess: () => toast.show(`Removed ${line.product_name}`), onError })}
            disabled={busy}
            className="inline-flex min-h-9 items-center gap-1 text-sm text-ink-600 hover:text-danger-600"
          >
            <TrashIcon className="size-4" />
            Remove<span className="sr-only"> {line.product_name}</span>
          </button>
        </div>
      </div>
    </li>
  )
}

/**
 * Delivery estimate for the whole cart: to the default saved address when there is one,
 * otherwise to the PIN code chosen in the header. Hidden if it can't be loaded (checkout
 * shows the binding estimate either way).
 */
function CartDelivery({ cartVersion }: { cartVersion: string }) {
  const pincode = usePincode()
  const addresses = useAddresses()
  const saved = addresses.data?.find((a) => a.is_default) ?? addresses.data?.[0]
  const target = saved ? { addressId: saved.id } : pincode ? { pincode } : null
  const estimate = useCartEstimate(addresses.isPending ? null : target, cartVersion)

  if (addresses.isPending) return null
  // A saved address that can't be checked right now: checkout shows the estimate instead.
  if (saved && estimate.isError) return null
  return (
    <section aria-labelledby="cart-delivery" className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
      <h2 id="cart-delivery" className="mb-2 text-base font-bold">
        Delivery
      </h2>
      {target && estimate.isPending ? (
        <p className="text-sm text-ink-600">Checking delivery…</p>
      ) : estimate.data && target ? (
        <div aria-busy={estimate.isFetching}>
          <p className="mb-1 text-xs text-ink-600">
            To{' '}
            <span className="font-semibold text-ink-900">
              {saved ? `${saved.name}, ${saved.area || saved.city} ${saved.postal_code}` : `PIN ${pincode}`}
            </span>
          </p>
          <DeliveryEstimate quote={estimate.data} />
        </div>
      ) : (
        <PincodeForm label="Enter your PIN code to see when your order can arrive" />
      )}
    </section>
  )
}

export function CartPage() {
  usePageMeta('Your cart')
  const { status } = useAuth()
  const cart = useCart()
  const navigate = useNavigate()

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

  const { items, totals, issues, can_checkout, offers } = cart.data
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

  const units = items.reduce((sum, line) => sum + line.quantity, 0)
  const checkoutButton = (className: string) => (
    <button type="button" onClick={() => navigate('/checkout')} disabled={!can_checkout} className={className}>
      Proceed to checkout
    </button>
  )

  return (
    <div className="container-page grid gap-6 pb-28 pt-6 lg:grid-cols-[1fr_22rem] lg:pb-6">
      <section aria-labelledby="cart-heading" className="rounded-lg bg-white px-4 ring-1 ring-steel-200 sm:px-5">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-steel-100 py-4">
          <h1 id="cart-heading" className="text-xl font-bold">
            Cart ({units} {units === 1 ? 'item' : 'items'})
          </h1>
          <Link to="/products" className="text-sm font-semibold text-amber-600 hover:underline">
            Continue shopping
          </Link>
        </div>
        {issues.length > 0 && (
          <div role="alert" className="mt-4 rounded-md bg-amber-100 p-3 text-sm text-ink-900">
            <p className="font-semibold">Please fix these before checkout:</p>
            <ul className="mt-1 list-disc pl-5">
              {issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </div>
        )}
        <ul className="divide-y divide-steel-100">
          {items.map((line) => (
            <Line key={line.id} line={line} />
          ))}
        </ul>
      </section>

      <aside className="h-fit space-y-3 lg:sticky lg:top-32">
        <CartOfferNotes offers={offers} />
        <CartDelivery cartVersion={items.map((line) => `${line.variant_id}x${line.quantity}`).join(',')} />
        <div className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
          <PriceSummary
            totals={totals}
            offers={offers.applied}
            footer={
              totals.savings_vs_mrp !== '0.00' && (
                <p className="mt-3 rounded-md bg-success-600/10 px-3 py-2 text-sm font-medium text-success-600">
                  You save {formatPrice(totals.savings_vs_mrp)} on this order
                </p>
              )
            }
          />
          <div className="mt-4 hidden lg:block">{checkoutButton('btn-primary w-full py-3 text-base')}</div>
          <p className="mt-2 text-xs text-ink-600">Coupons, delivery address and payment are chosen at checkout.</p>
        </div>
      </aside>

      {/* Mobile sticky checkout bar */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-steel-200 bg-white p-3 shadow-[0_-4px_12px_rgba(0,0,0,0.06)] lg:hidden">
        <div className="flex items-center gap-3">
          <div className="min-w-0">
            <p className="text-lg font-bold leading-tight">{formatPrice(totals.grand_total)}</p>
            <p className="text-xs text-ink-600">{can_checkout ? 'Total payable' : 'Fix cart issues to continue'}</p>
          </div>
          {checkoutButton('btn-primary flex-1 py-3 text-base')}
        </div>
      </div>
    </div>
  )
}
