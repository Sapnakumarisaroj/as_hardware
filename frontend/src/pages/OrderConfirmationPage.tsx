import { Link, Navigate, useParams } from 'react-router'

import { ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { AddressText } from '@/features/addresses/components'
import { useAuth } from '@/features/auth/context'
import { OrderDeliveryCard } from '@/features/delivery/components'
import { useOrder } from '@/features/orders/api'
import { OrderItemsList, OrderStatusBadge, PaymentStatusBadge } from '@/features/orders/components'
import { orderStatusLabel } from '@/features/orders/status'
import { isNotFound } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

export function OrderConfirmationPage() {
  const { number = '' } = useParams()
  usePageMeta('Order confirmed')
  const { status } = useAuth()
  const order = useOrder(number)

  if (status === 'loading') return <PageSpinner />
  if (status === 'anonymous') {
    return (
      <div className="container-page py-10">
        <SignInPrompt message="Sign in to see your order." next={`/order-confirmation/${number}`} />
      </div>
    )
  }
  if (order.isPending) return <PageSpinner label="Loading your order…" />
  if (order.isError) {
    if (isNotFound(order.error)) return <NotFoundPage />
    return (
      <div className="container-page py-10">
        <ErrorState error={order.error} onRetry={() => order.refetch()} title="Couldn’t load your order" />
      </div>
    )
  }

  const data = order.data
  // An online order that isn't paid yet belongs on the payment step, not here.
  if (data.payment_method === 'online' && data.status === 'pending') {
    return <Navigate to={`/orders/${data.order_number}/pay`} replace />
  }

  return (
    <div className="container-page flex justify-center py-8">
      <div className="w-full max-w-2xl space-y-4">
        <section className="rounded-xl bg-white p-6 text-center shadow-sm ring-1 ring-steel-200">
          <div aria-hidden className="mx-auto grid size-12 place-items-center rounded-full bg-success-600 text-2xl text-white">
            ✓
          </div>
          <h1 className="mt-3 text-2xl font-bold">
            {data.status === 'cancelled' ? 'Order cancelled' : 'Thank you! Your order is placed.'}
          </h1>
          <p className="mt-1 text-sm text-ink-600">
            Order number <span className="font-mono font-semibold text-ink-900">{data.order_number}</span>
          </p>
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <OrderStatusBadge order={data} />
            <PaymentStatusBadge order={data} />
          </div>
          {data.delivery_message && <p className="mt-3 text-sm font-semibold text-ink-900">{data.delivery_message}</p>}
          <p className="mt-2 text-lg font-bold">
            Total {formatPrice(data.grand_total)}
            <span className="block text-xs font-normal text-ink-600">
              {data.payment_method === 'cod' ? 'Pay in cash or UPI on delivery' : 'Paid online'}
            </span>
          </p>
        </section>

        {data.status !== 'cancelled' && (
          <OrderDeliveryCard order={data} statusLabel={orderStatusLabel(data)} headingId="confirm-delivery" />
        )}

        <section aria-labelledby="confirm-items" className="rounded-lg bg-white px-5 py-4 ring-1 ring-steel-200">
          <h2 id="confirm-items" className="text-base font-bold">
            Items ({data.items.length})
          </h2>
          <OrderItemsList items={data.items} />
        </section>

        <section aria-labelledby="confirm-address" className="rounded-lg bg-white p-5 ring-1 ring-steel-200">
          <h2 id="confirm-address" className="mb-2 text-base font-bold">
            Delivering to
          </h2>
          <AddressText address={data.address_snapshot} />
        </section>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Link to={`/account/orders/${data.order_number}`} className="btn-primary flex-1 py-3">
            View order
          </Link>
          <Link to="/products" className="btn-secondary flex-1 py-3">
            Continue shopping
          </Link>
        </div>
      </div>
    </div>
  )
}
