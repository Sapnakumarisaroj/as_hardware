import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { Pagination } from '@/components/Pagination'
import { useAddresses } from '@/features/addresses/api'
import { AddressFormModal, AddressList, AddressText } from '@/features/addresses/components'
import { useAuth } from '@/features/auth/context'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { OrderDeliveryCard } from '@/features/delivery/components'
import { DeliveryTracking } from '@/features/delivery/tracking'
import { orderStatusLabel } from '@/features/orders/status'
import { ORDERS_PAGE_SIZE, useOrder, useOrders, useRetryPayment, useReturns } from '@/features/orders/api'
import {
  CancelOrderDialog,
  OrderItemsList,
  OrderStatusBadge,
  OrderTimeline,
  PaymentStatusBadge,
  PriceSummary,
} from '@/features/orders/components'
import { BuyAgainButton, ReturnCard, ReturnDialog } from '@/features/orders/returns'
import type { OrderDetail } from '@/features/orders/types'
import { isNotFound } from '@/lib/api/errors'
import { formatDate, formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

function useSignedIn(message: string, next: string) {
  const { status, user } = useAuth()
  if (status === 'loading') return { gate: <PageSpinner />, user: null }
  if (!user) {
    return {
      gate: (
        <div className="container-page py-10">
          <SignInPrompt message={message} next={next} />
        </div>
      ),
      user: null,
    }
  }
  return { gate: null, user }
}

export function AccountPage() {
  usePageMeta('My account')
  const { logout } = useAuth()
  const { gate, user } = useSignedIn('Sign in to view your account.', '/account')
  if (gate || !user) return gate
  const tile = 'block h-full rounded-lg bg-white p-4 ring-1 ring-steel-200 hover:ring-amber-500'
  const tiles = [
    { to: '/account/orders', title: 'Orders', text: 'Track, cancel, return and buy again' },
    { to: '/account/returns', title: 'Returns', text: 'Return requests and refunds' },
    { to: '/account/wallet', title: 'Wallet', text: 'Credits, cashback and your referral code' },
    { to: '/account/addresses', title: 'Addresses', text: 'Manage delivery addresses' },
    { to: '/wishlist', title: 'Wishlist', text: 'Items you saved' },
    { to: '/cart', title: 'Cart', text: 'Ready to check out' },
  ]
  return (
    <div className="container-page max-w-3xl py-8">
      <h1 className="text-2xl font-bold">Hello, {user.full_name.split(' ')[0] || 'there'}</h1>
      <dl className="mt-4 grid gap-2 rounded-lg bg-white p-5 text-sm ring-1 ring-steel-200 sm:grid-cols-2">
        <div>
          <dt className="text-ink-600">Name</dt>
          <dd className="font-medium">{user.full_name}</dd>
        </div>
        <div>
          <dt className="text-ink-600">Email</dt>
          <dd className="font-medium">{user.email}</dd>
        </div>
        <div>
          <dt className="text-ink-600">Mobile</dt>
          <dd className="font-medium">{user.phone || '—'}</dd>
        </div>
      </dl>
      <ul className="mt-6 grid gap-3 sm:grid-cols-2">
        {tiles.map((t) => (
          <li key={t.to}>
            <Link to={t.to} className={tile}>
              <span className="font-semibold">{t.title}</span>
              <span className="block text-xs text-ink-600">{t.text}</span>
            </Link>
          </li>
        ))}
      </ul>
      <button type="button" onClick={() => void logout()} className="btn-secondary mt-6">
        Logout
      </button>
    </div>
  )
}

export function OrdersPage() {
  usePageMeta('Your orders')
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page')) || 1)
  const orders = useOrders(page)
  const { gate } = useSignedIn('Sign in to see your orders.', '/account/orders')
  if (gate) return gate

  let body
  if (orders.isPending) {
    body = (
      <ul aria-label="Loading orders" className="space-y-3">
        {Array.from({ length: 3 }, (_, i) => (
          <li key={i} className="h-24 animate-pulse rounded-lg bg-white ring-1 ring-steel-200" />
        ))}
      </ul>
    )
  } else if (orders.isError) {
    body = <ErrorState error={orders.error} onRetry={() => orders.refetch()} title="Couldn’t load your orders" />
  } else if (!orders.data.results.length) {
    body = (
      <EmptyState
        title="No orders yet"
        action={
          <Link to="/products" className="btn-primary">
            Start shopping
          </Link>
        }
      >
        When you place an order it will appear here.
      </EmptyState>
    )
  } else {
    body = (
      <>
        <ul className="space-y-3" aria-busy={orders.isFetching}>
          {orders.data.results.map((order) => (
            <li key={order.order_number}>
              <Link
                to={`/account/orders/${order.order_number}`}
                className="flex gap-3 rounded-lg bg-white p-4 ring-1 ring-steel-200 hover:ring-amber-500"
              >
                <ProductImage src={order.image} alt="" className="size-16 shrink-0 rounded" />
                <div className="min-w-0 flex-1 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold">
                      <span className="sr-only">Order </span>
                      {order.order_number}
                    </p>
                    <OrderStatusBadge order={order} />
                  </div>
                  <p className="truncate text-ink-800">{order.item_names.join(', ')}</p>
                  <p className="text-ink-600">
                    {formatDate(order.created_at)} · {order.item_count} {order.item_count === 1 ? 'item' : 'items'} ·{' '}
                    <span className="font-semibold text-ink-900">{formatPrice(order.grand_total)}</span>
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <PaymentStatusBadge order={order} />
                    {order.delivery_message && (
                      <span className={`text-xs ${order.delivery.type ? 'font-semibold text-ink-900' : 'text-ink-600'}`}>
                        {order.delivery_message}
                      </span>
                    )}
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
        <Pagination
          page={page}
          pageSize={ORDERS_PAGE_SIZE}
          total={orders.data.count}
          onChange={(p) => setParams(p > 1 ? { page: String(p) } : {})}
        />
      </>
    )
  }

  return (
    <div className="container-page max-w-3xl py-8">
      <Breadcrumbs items={[{ label: 'Account', to: '/account' }, { label: 'Orders' }]} />
      <h1 className="mb-4 mt-2 text-2xl font-bold">Your orders</h1>
      {body}
    </div>
  )
}

function refundText(refund: OrderDetail['refunds'][number]): string {
  const amount = formatPrice(refund.amount)
  if (refund.status === 'processed') {
    const when = refund.processed_at ? ` on ${formatDate(refund.processed_at)}` : ''
    return refund.manual
      ? `Refunded ${amount} by the store${when}.`
      : `Refunded ${amount}${when} to your original payment method. Banks can take 5–7 working days to show it.`
  }
  if (refund.status === 'failed') {
    return `Refund of ${amount} is delayed. Our team has been alerted and will complete it; no action is needed from you.`
  }
  return refund.manual
    ? `Refund of ${amount} requested — the store will pay it back to you.`
    : `Refund of ${amount} requested — it is being processed to your original payment method.`
}

function PaymentInfo({ order }: { order: OrderDetail }) {
  const captured = order.payments.find((p) => p.status === 'captured')
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span>{order.payment_method === 'cod' ? 'Cash on delivery' : 'Online payment'}</span>
        <PaymentStatusBadge order={order} />
      </div>
      {captured && (
        <p className="text-ink-600">
          Paid {formatPrice(captured.amount)}
          {captured.provider === 'mock' && ' (development mock payment)'}
        </p>
      )}
      {order.refunds.map((refund) => (
        <p
          key={refund.public_id}
          className={`rounded-md px-3 py-2 ${refund.status === 'processed' ? 'bg-success-600/10 text-success-600' : 'bg-amber-100 text-ink-900'}`}
        >
          {refundText(refund)}
        </p>
      ))}
    </div>
  )
}

/** Credits used on this order and cashback earned with it (Phase 17), straight from the ledger. */
function OrderCredits({ order }: { order: OrderDetail }) {
  const loyalty = order.loyalty
  if (!loyalty) return null
  const used = loyalty.credits_used !== '0.00'
  const live = loyalty.earned.filter((e) => e.status !== 'reversed')
  if (!used && !live.length) return null
  return (
    <section aria-labelledby="credits-heading" className="rounded-lg bg-white p-5 text-sm ring-1 ring-steel-200">
      <h2 id="credits-heading" className="mb-2 text-base font-bold">
        Credits & cashback
      </h2>
      {used && (
        <p>
          Credits used: <span className="font-semibold">{formatPrice(loyalty.credits_used)}</span>
          {loyalty.credits_restored !== '0.00' && ` · ${formatPrice(loyalty.credits_restored)} given back`}
        </p>
      )}
      {live.map((entry, index) => (
        <p key={index} className="mt-1">
          {entry.kind === 'cashback' ? 'Cashback' : 'Reward'}:{' '}
          <span className="font-semibold text-success-600">{formatPrice(entry.amount)}</span> · {entry.status_label}
          {entry.status === 'eligible' && entry.available_at && ` (usable from ${formatDate(entry.available_at)})`}
          {entry.status === 'pending' && ' (usable after delivery and the return window)'}
        </p>
      ))}
      <Link to="/account/wallet" className="mt-2 inline-block font-semibold text-amber-600 hover:underline">
        Your wallet
      </Link>
    </section>
  )
}

export function OrderDetailPage() {
  const { number = '' } = useParams()
  usePageMeta(`Order ${number}`)
  const order = useOrder(number, 'tracking')
  const retry = useRetryPayment(number)
  const [cancelling, setCancelling] = useState(false)
  const [returning, setReturning] = useState(false)
  const { gate } = useSignedIn('Sign in to see this order.', `/account/orders/${number}`)
  if (gate) return gate
  if (order.isPending) return <PageSpinner label="Loading order…" />
  if (order.isError) {
    if (isNotFound(order.error)) return <NotFoundPage />
    return (
      <div className="container-page py-10">
        <ErrorState error={order.error} onRetry={() => order.refetch()} title="Couldn’t load this order" />
      </div>
    )
  }

  const data = order.data
  const awaitingPayment = data.payment_method === 'online' && data.status === 'pending'
  const openAttempt = data.payments.some((p) => p.status === 'created')

  return (
    <div className="container-page max-w-5xl py-6">
      <Breadcrumbs
        items={[{ label: 'Account', to: '/account' }, { label: 'Orders', to: '/account/orders' }, { label: data.order_number }]}
      />
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Order {data.order_number}</h1>
          <p className="text-sm text-ink-600">Placed on {formatDate(data.created_at)}</p>
        </div>
        <OrderStatusBadge order={data} />
      </div>

      {awaitingPayment && (
        <div role="status" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-amber-100 p-4 text-sm">
          <p>
            <span className="font-semibold">Payment pending.</span> Complete the payment of {formatPrice(data.grand_total)} to
            confirm this order.
          </p>
          {openAttempt ? (
            <Link to={`/orders/${data.order_number}/pay`} className="btn-primary">
              Complete payment
            </Link>
          ) : (
            data.can_retry_payment && (
              <button type="button" onClick={() => retry.mutate()} disabled={retry.isPending} className="btn-primary">
                {retry.isPending ? 'Starting…' : 'Retry payment'}
              </button>
            )
          )}
        </div>
      )}
      {data.status === 'cancelled' && (
        <p className="mt-4 rounded-lg bg-danger-600/10 p-4 text-sm text-danger-600">
          Cancelled{data.cancelled_at && ` on ${formatDate(data.cancelled_at)}`}
          {data.cancellation_reason && ` — ${data.cancellation_reason}`}
        </p>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-5">
          <section aria-labelledby="progress-heading" className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
            <h2 id="progress-heading" className="mb-3 text-base font-bold">
              Order status
            </h2>
            {data.delivery_message && <p className="mb-4 text-sm font-semibold text-ink-900">{data.delivery_message}</p>}
            <OrderTimeline order={data} />
          </section>
          <DeliveryTracking order={data} />
          <OrderDeliveryCard order={data} statusLabel={orderStatusLabel(data)} headingId="delivery-heading" />
          <section aria-labelledby="items-heading" className="rounded-lg bg-white px-5 py-4 ring-1 ring-steel-200">
            <h2 id="items-heading" className="text-base font-bold">
              Items
            </h2>
            <OrderItemsList items={data.items} />
          </section>
          {data.returns.length > 0 && (
            <section aria-labelledby="returns-heading" className="space-y-3">
              <h2 id="returns-heading" className="text-base font-bold">
                Returns
              </h2>
              {data.returns.map((ret) => (
                <ReturnCard key={ret.return_number} ret={ret} />
              ))}
            </section>
          )}
        </div>
        <div className="space-y-5">
          <div className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
            <PriceSummary totals={data} couponCode={data.coupon_code} offers={data.applied_offers} />
          </div>
          <section aria-labelledby="payment-heading" className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
            <h2 id="payment-heading" className="mb-2 text-base font-bold">
              Payment
            </h2>
            <PaymentInfo order={data} />
          </section>
          <OrderCredits order={data} />
          <section aria-labelledby="address-heading" className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
            <h2 id="address-heading" className="mb-2 text-base font-bold">
              Delivery address
            </h2>
            <AddressText address={data.address_snapshot} />
            {data.customer_note && <p className="mt-2 text-xs text-ink-600">Note: {data.customer_note}</p>}
          </section>
          {data.can_reorder && <BuyAgainButton orderNumber={data.order_number} />}
          {data.can_return && (
            <div>
              <button type="button" onClick={() => setReturning(true)} className="btn-secondary w-full">
                Return items
              </button>
              {data.return_window_ends_at && (
                <p className="mt-1 text-xs text-ink-600">Returns open until {formatDate(data.return_window_ends_at)}</p>
              )}
            </div>
          )}
          {data.can_cancel && (
            <button type="button" onClick={() => setCancelling(true)} className="btn-secondary w-full">
              Cancel order
            </button>
          )}
          {!data.can_cancel && !['cancelled', 'delivered', 'returned', 'delivery_failed'].includes(data.status) && (
            <p className="text-xs text-ink-600">This order is already being packed or delivered, so it can’t be cancelled online.</p>
          )}
        </div>
      </div>
      <CancelOrderDialog order={data} open={cancelling} onClose={() => setCancelling(false)} />
      {data.can_return && <ReturnDialog order={data} open={returning} onClose={() => setReturning(false)} />}
    </div>
  )
}

export function ReturnsPage() {
  usePageMeta('Your returns')
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page')) || 1)
  const returns = useReturns(page)
  const { gate } = useSignedIn('Sign in to see your returns.', '/account/returns')
  if (gate) return gate

  let body
  if (returns.isPending) body = <PageSpinner label="Loading returns…" />
  else if (returns.isError)
    body = <ErrorState error={returns.error} onRetry={() => returns.refetch()} title="Couldn’t load your returns" />
  else if (!returns.data.results.length)
    body = (
      <EmptyState
        title="No returns"
        action={
          <Link to="/account/orders" className="btn-primary">
            Go to your orders
          </Link>
        }
      >
        You can return items from a delivered order’s page.
      </EmptyState>
    )
  else
    body = (
      <>
        <div className="space-y-3" aria-busy={returns.isFetching}>
          {returns.data.results.map((ret) => (
            <ReturnCard key={ret.return_number} ret={ret} showOrder />
          ))}
        </div>
        <Pagination
          page={page}
          pageSize={ORDERS_PAGE_SIZE}
          total={returns.data.count}
          onChange={(p) => setParams(p > 1 ? { page: String(p) } : {})}
        />
      </>
    )

  return (
    <div className="container-page max-w-3xl py-8">
      <Breadcrumbs items={[{ label: 'Account', to: '/account' }, { label: 'Returns' }]} />
      <h1 className="mb-4 mt-2 text-2xl font-bold">Your returns</h1>
      {body}
    </div>
  )
}

export function AddressesPage() {
  usePageMeta('Your addresses')
  const addresses = useAddresses()
  const [adding, setAdding] = useState(false)
  const { gate } = useSignedIn('Sign in to manage your addresses.', '/account/addresses')
  if (gate) return gate

  let body
  if (addresses.isPending) body = <PageSpinner label="Loading addresses…" />
  else if (addresses.isError)
    body = <ErrorState error={addresses.error} onRetry={() => addresses.refetch()} title="Couldn’t load your addresses" />
  else if (!addresses.data.length)
    body = (
      <EmptyState
        title="No saved addresses"
        action={
          <button type="button" onClick={() => setAdding(true)} className="btn-primary">
            Add an address
          </button>
        }
      >
        Save an address to check out faster.
      </EmptyState>
    )
  else body = <AddressList addresses={addresses.data} />

  return (
    <div className="container-page max-w-3xl py-8">
      <Breadcrumbs items={[{ label: 'Account', to: '/account' }, { label: 'Addresses' }]} />
      <div className="mb-4 mt-2 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Your addresses</h1>
        {addresses.data?.length ? (
          <button type="button" onClick={() => setAdding(true)} className="btn-secondary">
            + Add new
          </button>
        ) : null}
      </div>
      {body}
      <AddressFormModal open={adding} onClose={() => setAdding(false)} />
    </div>
  )
}
