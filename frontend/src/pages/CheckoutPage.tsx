import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, Navigate, useNavigate } from 'react-router'

import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { BoltIcon, ClockIcon } from '@/components/icons'
import { useToast } from '@/components/toast'
import { AddressFormModal, AddressList } from '@/features/addresses/components'
import { useAddresses } from '@/features/addresses/api'
import { useAuth } from '@/features/auth/context'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { checkoutKeys, useCheckoutPreview, type CheckoutPreview } from '@/features/checkout/api'
import { newIdempotencyKey, usePlaceOrder } from '@/features/orders/api'
import { PriceSummary } from '@/features/orders/components'
import type { PaymentMethod } from '@/features/orders/types'
import { api } from '@/lib/api/client'
import { ApiError } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

function Step({ n, title, children, action }: { n: number; title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section aria-labelledby={`step-${n}`} className="rounded-lg bg-white p-4 ring-1 ring-steel-200 sm:p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id={`step-${n}`} className="flex items-center gap-2 text-base font-bold">
          <span aria-hidden className="grid size-6 place-items-center rounded-full bg-ink-900 text-xs text-white">
            {n}
          </span>
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function DeliveryInfo({ delivery }: { delivery: CheckoutPreview['delivery'] }) {
  if (!delivery.available) {
    return (
      <p role="alert" className="text-sm font-semibold text-danger-600">
        {delivery.message}
      </p>
    )
  }
  return (
    <div className="space-y-2 text-sm">
      <p className="flex items-start gap-2 font-semibold text-ink-900">
        {delivery.fast_delivery_possible ? (
          <>
            <BoltIcon className="mt-0.5 size-4 shrink-0 text-amber-600" />
            Available for delivery · stocked at a store with fast delivery
          </>
        ) : (
          <>
            <ClockIcon className="mt-0.5 size-4 shrink-0 text-ink-600" />
            Available for delivery from our stores
          </>
        )}
      </p>
      <p className="pl-6 text-ink-600">
        {delivery.eta_minutes ? `Estimated delivery in about ${delivery.eta_minutes} minutes.` : delivery.message}
      </p>
      <p className="pl-6 text-ink-800">
        Delivery fee: {delivery.fee === '0.00' ? <span className="font-semibold text-success-600">Free</span> : formatPrice(delivery.fee)}
        {delivery.amount_to_free_delivery !== '0.00' && (
          <span className="block text-xs text-ink-600">
            Add {formatPrice(delivery.amount_to_free_delivery)} more for free delivery (orders from{' '}
            {formatPrice(delivery.free_delivery_min_order)}).
          </span>
        )}
      </p>
    </div>
  )
}

function CouponBox({
  applied,
  preview,
  onApply,
  onRemove,
}: {
  applied: string
  preview: CheckoutPreview
  onApply: (code: string) => Promise<string | null>
  onRemove: () => void
}) {
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const value = code.trim()
    if (!value) return
    setBusy(true)
    setError('')
    const problem = await onApply(value)
    setBusy(false)
    if (problem) setError(problem)
    else setCode('')
  }

  if (applied && preview.coupon) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-success-600/10 px-3 py-2 text-sm">
        <p>
          <span className="font-semibold text-success-600">{preview.coupon.code}</span> applied — you save{' '}
          <span className="font-semibold">{formatPrice(preview.coupon.discount)}</span>
          {preview.coupon.description && <span className="block text-xs text-ink-600">{preview.coupon.description}</span>}
        </p>
        <button type="button" onClick={onRemove} className="font-semibold text-ink-800 hover:underline">
          Remove<span className="sr-only"> coupon {preview.coupon.code}</span>
        </button>
      </div>
    )
  }
  return (
    <form onSubmit={submit} className="space-y-1" noValidate>
      <label htmlFor="coupon-code" className="label">
        Coupon code
      </label>
      <div className="flex gap-2">
        <input
          id="coupon-code"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          maxLength={30}
          autoComplete="off"
          className="input uppercase"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? 'coupon-error' : undefined}
          placeholder="Enter code"
        />
        <button type="submit" disabled={busy || !code.trim()} className="btn-secondary shrink-0">
          {busy ? 'Checking…' : 'Apply'}
        </button>
      </div>
      {error && (
        <p id="coupon-error" role="alert" className="text-xs text-danger-600">
          {error}
        </p>
      )}
    </form>
  )
}

export function CheckoutPage() {
  usePageMeta('Checkout')
  const { status } = useAuth()
  const addresses = useAddresses()
  const [chosenAddressId, setChosenAddressId] = useState<number | null>(null)
  const [coupon, setCoupon] = useState('')
  const [method, setMethod] = useState<PaymentMethod | null>(null)
  const [note, setNote] = useState('')
  const [addingAddress, setAddingAddress] = useState(false)
  const [orderError, setOrderError] = useState<string | null>(null)
  // One key per checkout attempt: a double click or a retried request can't create two orders.
  const [idempotencyKey] = useState(newIdempotencyKey)

  const list = addresses.data ?? []
  const addressId =
    (chosenAddressId !== null && list.some((a) => a.id === chosenAddressId) ? chosenAddressId : null) ??
    list.find((a) => a.is_default)?.id ??
    list[0]?.id ??
    null

  const preview = useCheckoutPreview(addressId, coupon)
  const placeOrder = usePlaceOrder()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()

  if (status === 'loading') return <PageSpinner />
  if (status === 'anonymous') {
    return (
      <div className="container-page py-10">
        <SignInPrompt message="Sign in to check out." next="/checkout" />
      </div>
    )
  }
  if (preview.isPending || addresses.isPending) return <PageSpinner label="Preparing checkout…" />
  if (preview.isError || addresses.isError) {
    const error = preview.error ?? addresses.error
    return (
      <div className="container-page py-10">
        <ErrorState
          error={error}
          title="Couldn’t load checkout"
          onRetry={() => {
            void preview.refetch()
            void addresses.refetch()
          }}
        />
      </div>
    )
  }

  const data = preview.data
  if (!data.cart.items.length && !placeOrder.isSuccess) {
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
          Add products to your cart to check out.
        </EmptyState>
      </div>
    )
  }
  if (data.cart.issues.length) return <Navigate to="/cart" replace />

  const paymentMethod: PaymentMethod = method ?? data.payment_methods[0]?.value ?? 'cod'
  const issues = data.blocking_issues.filter((i) => i.code !== 'coupon_invalid')
  const canPlace = data.can_place_order && !preview.isFetching && !placeOrder.isPending

  async function applyCoupon(code: string): Promise<string | null> {
    try {
      const result = await queryClient.fetchQuery({
        queryKey: checkoutKeys.preview(addressId, code),
        queryFn: async () =>
          (await api.post<CheckoutPreview>('/checkout/preview/', { address_id: addressId, coupon_code: code })).data,
      })
      if (result.coupon_error) return result.coupon_error.message
      setCoupon(code)
      toast.show(`Coupon ${code} applied`)
      return null
    } catch (err) {
      return err instanceof ApiError ? err.message : 'Could not check the coupon. Please try again.'
    }
  }

  function submitOrder() {
    if (!addressId || !canPlace) return
    setOrderError(null)
    placeOrder.mutate(
      {
        addressId,
        paymentMethod,
        couponCode: coupon,
        customerNote: note.trim(),
        expectedTotal: data.totals.grand_total,
        idempotencyKey,
      },
      {
        onSuccess: (order) => {
          navigate(
            order.payment_method === 'online' && order.status === 'pending'
              ? `/orders/${order.order_number}/pay`
              : `/order-confirmation/${order.order_number}`,
            { replace: true },
          )
        },
        onError: (error) => {
          const code = error instanceof ApiError ? error.code : ''
          if (code === 'totals_changed') {
            setOrderError('Prices changed since you opened checkout. Please review the updated total and place the order again.')
          } else {
            setOrderError(error instanceof ApiError ? error.message : 'Could not place the order. Please try again.')
          }
          void queryClient.invalidateQueries({ queryKey: checkoutKeys.all })
          void queryClient.invalidateQueries({ queryKey: ['cart'] })
        },
      },
    )
  }

  const placeButton = (className: string) => (
    <button type="button" onClick={submitOrder} disabled={!canPlace} className={className}>
      {placeOrder.isPending
        ? 'Placing order…'
        : paymentMethod === 'online'
          ? `Continue to payment · ${formatPrice(data.totals.grand_total)}`
          : `Place order · ${formatPrice(data.totals.grand_total)}`}
    </button>
  )

  return (
    <div className="container-page pb-32 pt-6 lg:pb-8">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Checkout</h1>
        <Link to="/cart" className="text-sm font-semibold text-amber-600 hover:underline">
          Back to cart
        </Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem] lg:gap-6">
        <div className="space-y-4">
          <Step
            n={1}
            title="Delivery address"
            action={
              list.length > 0 && (
                <button type="button" onClick={() => setAddingAddress(true)} className="text-sm font-semibold text-amber-600 hover:underline">
                  + Add new
                </button>
              )
            }
          >
            {list.length === 0 ? (
              <div className="rounded-md border border-dashed border-steel-200 p-4 text-center">
                <p className="text-sm text-ink-800">Add an address so we know where to deliver.</p>
                <button type="button" onClick={() => setAddingAddress(true)} className="btn-primary mt-3">
                  Add delivery address
                </button>
              </div>
            ) : (
              <AddressList addresses={list} selectedId={addressId} onSelect={setChosenAddressId} />
            )}
          </Step>

          <Step n={2} title="Delivery information">
            <DeliveryInfo delivery={data.delivery} />
          </Step>

          <Step n={3} title={`Order items (${data.cart.items.length})`}>
            <ul className="divide-y divide-steel-100">
              {data.cart.items.map((line) => (
                <li key={line.id} className="flex items-center gap-3 py-2">
                  <ProductImage src={line.image} alt={line.product_name} className="size-12 shrink-0 rounded" />
                  <div className="min-w-0 flex-1 text-sm">
                    <p className="truncate font-medium">{line.product_name}</p>
                    <p className="text-xs text-ink-600">
                      {line.variant_name && `${line.variant_name} · `}Qty {line.quantity}
                    </p>
                  </div>
                  <p className="text-sm font-semibold">{line.line_total ? formatPrice(line.line_total) : '—'}</p>
                </li>
              ))}
            </ul>
            {data.cart.items.some((l) => l.price_changed) && (
              <p className="mt-2 text-xs font-medium text-amber-600">Some prices changed since you added them; totals use today’s prices.</p>
            )}
          </Step>

          <Step n={4} title="Coupon">
            <CouponBox applied={coupon} preview={data} onApply={applyCoupon} onRemove={() => setCoupon('')} />
            {coupon && data.coupon_error && (
              <p role="alert" className="mt-2 text-sm text-danger-600">
                {data.coupon_error.message}{' '}
                <button type="button" onClick={() => setCoupon('')} className="font-semibold underline">
                  Remove coupon
                </button>
              </p>
            )}
          </Step>

          <Step n={5} title="Payment method">
            <fieldset>
              <legend className="sr-only">Choose how to pay</legend>
              <div className="space-y-2">
                {data.payment_methods.map((option) => (
                  <label
                    key={option.value}
                    className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md px-3 py-2 ring-1 ring-steel-200 has-checked:bg-amber-100 has-checked:ring-2 has-checked:ring-amber-500"
                  >
                    <input
                      type="radio"
                      name="payment-method"
                      value={option.value}
                      checked={paymentMethod === option.value}
                      onChange={() => setMethod(option.value)}
                      className="size-5 accent-amber-600"
                    />
                    <span className="text-sm">
                      <span className="block font-semibold">{option.value === 'cod' ? 'Cash on delivery' : option.label}</span>
                      <span className="block text-xs text-ink-600">
                        {option.value === 'cod'
                          ? 'Pay in cash or UPI when your order arrives.'
                          : option.test_mode
                            ? 'Development mode: you choose success, failure or cancellation on the next screen. No money moves.'
                            : 'UPI, card or net banking.'}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="mt-4">
              <label htmlFor="order-note" className="label">
                Delivery note <span className="font-normal text-ink-600">(optional)</span>
              </label>
              <input
                id="order-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={500}
                placeholder="e.g. Call before delivery, gate 2"
                className="input"
              />
            </div>
          </Step>
        </div>

        <aside className="h-fit space-y-3 lg:sticky lg:top-32">
          <div className="rounded-lg bg-white p-5 ring-1 ring-steel-200" aria-busy={preview.isFetching}>
            <PriceSummary totals={data.totals} couponCode={data.coupon?.code} heading="Order summary" />
            {issues.length > 0 && (
              <ul role="alert" className="mt-3 space-y-1 rounded-md bg-amber-100 p-3 text-sm text-ink-900">
                {issues.map((issue) => (
                  <li key={issue.code}>{issue.message}</li>
                ))}
              </ul>
            )}
            {orderError && (
              <p role="alert" className="mt-3 rounded-md bg-danger-600/10 p-3 text-sm text-danger-600">
                {orderError}
              </p>
            )}
            <div className="mt-4 hidden lg:block">{placeButton('btn-primary w-full py-3 text-base')}</div>
            <p className="mt-2 text-xs text-ink-600">
              By placing the order you agree to pay the total shown. Prices and stock are re-checked when you place it.
            </p>
          </div>
        </aside>
      </div>

      {/* Mobile sticky order total + action */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-steel-200 bg-white p-3 shadow-[0_-4px_12px_rgba(0,0,0,0.06)] lg:hidden">
        {placeButton('btn-primary w-full py-3.5 text-base')}
      </div>

      <AddressFormModal open={addingAddress} onClose={() => setAddingAddress(false)} onSaved={(a) => setChosenAddressId(a.id)} />
    </div>
  )
}
