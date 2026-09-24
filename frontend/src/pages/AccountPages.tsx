import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { useAuth } from '@/features/auth/context'
import type { Paginated } from '@/features/catalog/types'
import { api } from '@/lib/api/client'
import { formatDate, formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

interface OrderSummary {
  order_number: string
  status: string
  payment_method: string
  grand_total: string
  item_count: number
  created_at: string
}

export function AccountPage() {
  usePageMeta('My account')
  const { status, user, logout } = useAuth()
  if (status === 'loading') return <PageSpinner />
  if (!user) {
    return (
      <div className="container-page py-10">
        <SignInPrompt message="Sign in to view your account." next="/account" />
      </div>
    )
  }
  const tile = 'rounded-lg bg-white p-4 ring-1 ring-steel-200 hover:ring-amber-500'
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
      <ul className="mt-6 grid gap-3 sm:grid-cols-3">
        <li>
          <Link to="/account/orders" className={`block ${tile}`}>
            <span className="font-semibold">Orders</span>
            <span className="block text-xs text-ink-600">Track and view past orders</span>
          </Link>
        </li>
        <li>
          <Link to="/wishlist" className={`block ${tile}`}>
            <span className="font-semibold">Wishlist</span>
            <span className="block text-xs text-ink-600">Items you saved</span>
          </Link>
        </li>
        <li>
          <Link to="/cart" className={`block ${tile}`}>
            <span className="font-semibold">Cart</span>
            <span className="block text-xs text-ink-600">Ready to check out</span>
          </Link>
        </li>
      </ul>
      <button type="button" onClick={() => void logout()} className="btn-secondary mt-6">
        Logout
      </button>
    </div>
  )
}

export function OrdersPage() {
  usePageMeta('Your orders')
  const { status } = useAuth()
  const orders = useQuery({
    queryKey: ['orders', 'list'],
    queryFn: async () => (await api.get<Paginated<OrderSummary>>('/orders/')).data,
    enabled: status === 'authenticated',
  })

  let body
  if (status === 'loading') body = <PageSpinner />
  else if (status === 'anonymous') body = <SignInPrompt message="Sign in to see your orders." next="/account/orders" />
  else if (orders.isPending) body = <PageSpinner label="Loading orders…" />
  else if (orders.isError)
    body = <ErrorState error={orders.error} onRetry={() => orders.refetch()} title="Couldn’t load your orders" />
  else if (!orders.data.results.length)
    body = (
      <EmptyState
        title="No orders yet"
        action={
          <Link to="/products" className="btn-primary">
            Start shopping
          </Link>
        }
      />
    )
  else
    body = (
      <ul className="divide-y divide-steel-100 rounded-lg bg-white px-5 ring-1 ring-steel-200">
        {orders.data.results.map((order) => (
          <li key={order.order_number} className="flex flex-wrap items-center justify-between gap-2 py-4 text-sm">
            <div>
              <p className="font-semibold">{order.order_number}</p>
              <p className="text-ink-600">
                {formatDate(order.created_at)} · {order.item_count} {order.item_count === 1 ? 'item' : 'items'}
              </p>
            </div>
            <span className="rounded-full bg-steel-100 px-2.5 py-1 text-xs font-semibold capitalize">
              {order.status.replace(/_/g, ' ')}
            </span>
            <p className="font-semibold">{formatPrice(order.grand_total)}</p>
          </li>
        ))}
      </ul>
    )

  return (
    <div className="container-page max-w-3xl py-8">
      <h1 className="mb-4 text-2xl font-bold">Your orders</h1>
      {body}
    </div>
  )
}
