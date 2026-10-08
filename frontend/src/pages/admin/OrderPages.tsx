import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { useToast } from '@/components/toast'
import { useOrder, useOrders, useTransitionOrder } from '@/features/admin/api'
import { AssignRiderDialog, ShipmentActions, UnassignDialog } from '@/features/admin/delivery'
import { useSession } from '@/features/admin/session'
import type { AdminOrderDetail, AdminOrderRow, StaffShipment } from '@/features/admin/types'
import {
  Badge,
  ConfirmDialog,
  dateTime,
  Facts,
  FilterBar,
  FilterSelect,
  ListView,
  PageHeader,
  Panel,
  SearchBox,
  StatusBadge,
  useListParams,
  type Column,
} from '@/features/admin/ui'
import { orderStatusLabel, paymentStatusLabel } from '@/features/orders/status'
import { isNotFound } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from '../NotFoundPage'

const STATUS_OPTIONS: [string, string][] = [
  ['open', 'All open orders'],
  ['pending', 'Waiting for payment'],
  ['preparing', 'Being prepared'],
  ['confirmed', 'Confirmed'],
  ['processing', 'Processing'],
  ['packed', 'Packed'],
  ['on_the_way', 'On the way'],
  ['delivery_failed', 'Delivery failed'],
  ['delivered', 'Delivered'],
  ['cancelled', 'Cancelled'],
  ['return_requested', 'Return requested'],
  ['returned', 'Returned'],
]

const COLUMNS: Column<AdminOrderRow>[] = [
  {
    header: 'Order',
    cell: (order) => (
      <>
        <Link to={`/admin/orders/${order.order_number}`} className="font-semibold text-ink-900 underline-offset-2 hover:underline">
          {order.order_number}
        </Link>
        <span className="block text-xs text-ink-600">{dateTime(order.created_at)}</span>
      </>
    ),
  },
  {
    header: 'Customer',
    cell: (order) => (
      <>
        {order.customer.name || order.customer.email}
        <span className="block text-xs text-ink-600">{order.customer.phone}</span>
      </>
    ),
  },
  {
    header: 'Items',
    cell: (order) => (
      <>
        {order.item_count} {order.item_count === 1 ? 'unit' : 'units'}
        <span className="block max-w-56 truncate text-xs text-ink-600">{order.item_names.join(', ')}</span>
      </>
    ),
  },
  { header: 'Total', numeric: true, cell: (order) => formatPrice(order.grand_total) },
  {
    header: 'Payment',
    cell: (order) => (
      <>
        {paymentStatusLabel(order)}
        <span className="block text-xs text-ink-600">{order.payment_method === 'cod' ? 'Cash on delivery' : 'Online'}</span>
      </>
    ),
  },
  {
    header: 'Status',
    cell: (order) => (
      <span className="flex flex-wrap justify-end gap-1 md:justify-start">
        <StatusBadge status={order.status} text={orderStatusLabel(order)} />
        {order.open_return && <Badge tone="warn">Return open</Badge>}
        {order.refund_status && order.refund_status !== 'processed' && (
          <Badge tone={order.refund_status === 'failed' ? 'bad' : 'warn'}>Refund {order.refund_status}</Badge>
        )}
      </span>
    ),
  },
  {
    header: 'Store and rider',
    cell: (order) => (
      <>
        {order.store_name ?? '—'}
        <span className="block text-xs text-ink-600">
          {order.shipments.map((s) => s.rider).filter(Boolean).join(', ') || 'No rider yet'}
        </span>
      </>
    ),
  },
]

export function AdminOrdersPage() {
  usePageMeta('Orders')
  const list = useListParams()
  const session = useSession()
  const orders = useOrders({
    page: list.page,
    q: list.get('q'),
    status: list.get('status'),
    payment_status: list.get('payment_status'),
    payment_method: list.get('payment_method'),
    delivery_type: list.get('delivery_type'),
    store: list.get('store'),
    customer: list.get('customer'),
    from: list.get('from'),
    to: list.get('to'),
  })

  return (
    <>
      <PageHeader title="Orders" description="Search by order number, customer name, email, phone, product or SKU." />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search orders" />
        <FilterSelect list={list} name="status" label="Status" options={STATUS_OPTIONS} />
        <FilterSelect
          list={list}
          name="payment_status"
          label="Payment"
          options={[
            ['pending', 'Pending'],
            ['paid', 'Paid'],
            ['failed', 'Failed'],
            ['refunded', 'Refunded'],
            ['partially_refunded', 'Partially refunded'],
          ]}
        />
        <FilterSelect list={list} name="payment_method" label="Method" options={[['cod', 'Cash on delivery'], ['online', 'Online']]} />
        <FilterSelect list={list} name="delivery_type" label="Delivery" options={[['fast', 'Fast'], ['standard', 'Standard']]} />
        {session.stores.length > 1 && (
          <FilterSelect
            list={list}
            name="store"
            label="Store"
            all="All stores"
            options={session.stores.map((store) => [String(store.id), store.name])}
          />
        )}
        <div className="flex items-center gap-1 text-sm">
          <label htmlFor="from" className="text-ink-600">
            From
          </label>
          <input id="from" type="date" className="input w-auto" value={list.get('from')} onChange={(e) => list.set({ from: e.target.value })} />
          <label htmlFor="to" className="text-ink-600">
            to
          </label>
          <input id="to" type="date" className="input w-auto" value={list.get('to')} onChange={(e) => list.set({ to: e.target.value })} />
        </div>
      </FilterBar>
      <ListView
        query={orders}
        list={list}
        caption="Orders"
        columns={COLUMNS}
        rowKey={(order) => order.order_number}
        empty="No orders yet"
        emptyHint="Orders appear here as soon as customers place them."
      />
    </>
  )
}

// --- Detail --------------------------------------------------------------------------------------

const ACTION_LABELS: Record<string, string> = {
  confirmed: 'Confirm order',
  processing: 'Start preparing',
  packed: 'Mark as packed',
  assigned: 'Hand to own rider',
  picked_up: 'Mark as picked up',
  out_for_delivery: 'Mark as out for delivery',
  delivered: 'Mark as delivered',
  delivery_failed: 'Delivery failed',
  cancelled: 'Cancel order',
}

function OrderActions({ order }: { order: AdminOrderDetail }) {
  const [target, setTarget] = useState<string | null>(null)
  const transition = useTransitionOrder(order.order_number)
  const toast = useToast()
  if (!order.can_manage) {
    return <p className="text-sm text-ink-600">This order belongs to a store you don’t manage, so you can’t change it.</p>
  }
  if (order.allowed_actions.length === 0) {
    return (
      <p className="text-sm text-ink-600">
        {order.staff_shipments.some((s) => s.rider && ['assigned', 'accepted', 'picked_up', 'out_for_delivery'].includes(s.rider.assignment_status))
          ? 'A delivery partner is handling this order; their steps move it forward.'
          : 'Nothing more to do for this order.'}
      </p>
    )
  }
  const cancelling = target === 'cancelled'
  const failing = target === 'delivery_failed'

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {order.allowed_actions.map((action) => (
          <button
            key={action.status}
            type="button"
            className={action.status === 'cancelled' || action.status === 'delivery_failed' ? 'btn-secondary text-danger-600' : 'btn-primary'}
            onClick={() => {
              transition.reset()
              setTarget(action.status)
            }}
          >
            {ACTION_LABELS[action.status] ?? action.label}
          </button>
        ))}
      </div>
      <ConfirmDialog
        open={target !== null}
        title={`${ACTION_LABELS[target ?? ''] ?? 'Change status'}?`}
        confirmLabel={ACTION_LABELS[target ?? ''] ?? 'Confirm'}
        danger={cancelling || failing}
        busy={transition.isPending}
        error={transition.error}
        note={{
          label: cancelling ? 'Reason for cancelling' : failing ? 'What happened' : 'Note (optional)',
          required: cancelling || failing,
        }}
        onClose={() => setTarget(null)}
        onConfirm={(note) => {
          if (!target) return
          transition.mutate(
            { status: target, note },
            {
              onSuccess: () => {
                toast.show(`Order ${order.order_number} updated.`)
                setTarget(null)
              },
            },
          )
        }}
      >
        <p>
          Order {order.order_number} for {order.customer.name || order.customer.email}, {formatPrice(order.grand_total)}.
        </p>
        {cancelling && (
          <p>
            Reserved stock goes back on sale.{' '}
            {order.payment_status === 'paid' ? 'The amount paid is refunded by the usual refund process.' : ''}
          </p>
        )}
      </ConfirmDialog>
    </>
  )
}

function Shipments({ order }: { order: AdminOrderDetail }) {
  const [assigning, setAssigning] = useState<StaffShipment | null>(null)
  const [unassigning, setUnassigning] = useState<StaffShipment | null>(null)
  return (
    <Panel title={order.staff_shipments.length > 1 ? `Shipments (${order.staff_shipments.length})` : 'Shipment'}>
      {order.staff_shipments.length === 0 && <p className="text-sm text-ink-600">This order has no shipment record.</p>}
      <ul className="space-y-4">
        {order.staff_shipments.map((shipment) => (
          <li key={shipment.id} className="rounded-md bg-steel-50 p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="font-semibold">
                {order.staff_shipments.length > 1 && `${shipment.sequence}. `}
                {shipment.store_name}
              </p>
              <StatusBadge status={shipment.status} text={shipment.status_label} />
            </div>
            <Facts
              items={[
                ['Delivery', shipment.delivery_type === 'fast' ? 'Fast' : 'Standard'],
                ['Distance', shipment.distance_km ? `${shipment.distance_km} km` : '—'],
                ['Ready by', dateTime(shipment.estimated_ready_at)],
                ['Promised', dateTime(shipment.estimated_delivery_at)],
                ['Rider', shipment.rider ? `${shipment.rider.full_name} · ${shipment.rider.phone}` : 'Not assigned'],
                ['Attempts', shipment.delivery_attempts],
                ...(shipment.delivered_at ? ([['Delivered', dateTime(shipment.delivered_at)]] as [string, string][]) : []),
                ...(shipment.failed_at
                  ? ([['Failed', `${dateTime(shipment.failed_at)} · ${shipment.failure_note || shipment.failure_reason}`]] as [string, string][])
                  : []),
                ...(shipment.cod
                  ? ([
                      [
                        'Cash on delivery',
                        `${formatPrice(shipment.cod.amount_due)} · ${
                          shipment.cod.collected
                            ? shipment.cod.handed_over
                              ? 'collected and handed over'
                              : `collected (${shipment.cod.method ?? 'cash'}), not handed over yet`
                            : 'not collected yet'
                        }`,
                      ],
                    ] as [string, string][])
                  : []),
                ...(shipment.rider?.completed_without_otp
                  ? ([['Delivery code', 'Closed by staff without the code']] as [string, string][])
                  : []),
              ]}
            />
            {order.can_manage && (
              <div className="mt-3">
                <ShipmentActions shipment={shipment} onAssign={setAssigning} onUnassign={setUnassigning} />
              </div>
            )}
          </li>
        ))}
      </ul>
      <AssignRiderDialog shipment={assigning} onClose={() => setAssigning(null)} />
      <UnassignDialog shipment={unassigning} onClose={() => setUnassigning(null)} />
    </Panel>
  )
}

export function AdminOrderDetailPage() {
  const { number } = useParams()
  usePageMeta(`Order ${number ?? ''}`)
  const session = useSession()
  const query = useOrder(number)

  if (query.isPending) return <PageSpinner label="Loading the order…" />
  if (isNotFound(query.error)) return <NotFoundPage />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn’t load the order" />
  const order = query.data
  const address = order.address_snapshot

  return (
    <>
      <PageHeader
        title={`Order ${order.order_number}`}
        crumbs={[{ label: 'Orders', to: '/admin/orders' }]}
        description={`Placed ${dateTime(order.created_at)}`}
        actions={
          <>
            <StatusBadge status={order.status} text={orderStatusLabel(order)} />
            <Badge tone={order.payment_status === 'paid' ? 'good' : 'neutral'}>{paymentStatusLabel(order)}</Badge>
          </>
        }
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Panel title="What to do next">
            <OrderActions order={order} />
          </Panel>

          <Panel title="Items">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Items of this order</caption>
              <thead className="text-xs uppercase text-ink-600">
                <tr>
                  <th scope="col" className="py-1.5 pr-3">
                    Product
                  </th>
                  <th scope="col" className="py-1.5 pl-3 text-right">
                    Price
                  </th>
                  <th scope="col" className="py-1.5 pl-3 text-right">
                    Qty
                  </th>
                  <th scope="col" className="py-1.5 pl-3 text-right">
                    Total
                  </th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {order.items.map((item) => (
                  <tr key={item.id} className="border-t border-steel-100 align-top">
                    <th scope="row" className="py-2 pr-3 font-medium">
                      {item.product_name}
                      <span className="block text-xs font-normal text-ink-600">
                        {[item.variant_name, `SKU ${item.sku}`].filter(Boolean).join(' · ')}
                        {item.returned_quantity > 0 && ` · ${item.returned_quantity} returned`}
                      </span>
                    </th>
                    <td className="py-2 pl-3 text-right">{formatPrice(item.unit_price)}</td>
                    <td className="py-2 pl-3 text-right">{item.quantity}</td>
                    <td className="py-2 pl-3 text-right">{formatPrice(item.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <dl className="mt-3 ml-auto max-w-xs space-y-1 border-t border-steel-200 pt-3 text-sm tabular-nums">
              {(
                [
                  ['Subtotal', order.subtotal],
                  ['Offers', Number(order.offer_discount) > 0 ? `-${order.offer_discount}` : null],
                  [`Coupon ${order.coupon_code}`.trim(), Number(order.coupon_discount) > 0 ? `-${order.coupon_discount}` : null],
                  ['Delivery', order.delivery_fee],
                ] as [string, string | null][]
              )
                .filter(([, value]) => value !== null)
                .map(([name, value]) => (
                  <div key={name} className="flex justify-between gap-3">
                    <dt className="text-ink-600">{name}</dt>
                    <dd>{value!.startsWith('-') ? `− ${formatPrice(value!.slice(1))}` : formatPrice(value)}</dd>
                  </div>
                ))}
              <div className="flex justify-between gap-3 text-base font-bold">
                <dt>Total</dt>
                <dd>{formatPrice(order.grand_total)}</dd>
              </div>
              <div className="flex justify-between gap-3 text-xs text-ink-600">
                <dt>Includes GST</dt>
                <dd>{formatPrice(order.tax_total)}</dd>
              </div>
            </dl>
          </Panel>

          <Shipments order={order} />

          {order.returns.length > 0 && (
            <Panel
              title="Returns"
              action={
                <Link to={`/admin/returns?q=${order.order_number}`} className="text-sm font-semibold text-amber-700 hover:underline">
                  Handle returns
                </Link>
              }
            >
              <ul className="space-y-2 text-sm">
                {order.returns.map((ret) => (
                  <li key={ret.return_number} className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <span className="font-semibold">{ret.return_number}</span> · {ret.reason_label} ·{' '}
                      {ret.items.map((item) => `${item.quantity} × ${item.product_name}`).join(', ')}
                    </span>
                    <span className="flex items-center gap-2">
                      {formatPrice(ret.refund_amount)} <StatusBadge status={ret.status} text={ret.status_label} />
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {(order.payments.length > 0 || order.refunds.length > 0) && (
            <Panel
              title="Payments and refunds"
              action={
                order.refunds.length > 0 ? (
                  <Link to={`/admin/refunds?q=${order.order_number}`} className="text-sm font-semibold text-amber-700 hover:underline">
                    Handle refunds
                  </Link>
                ) : undefined
              }
            >
              <ul className="space-y-2 text-sm">
                {order.payments.map((payment) => (
                  <li key={payment.public_id} className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      Payment · {payment.provider === 'cod' ? 'cash on delivery' : payment.provider} · {dateTime(payment.created_at)}
                      {payment.failure_reason && <span className="block text-xs text-danger-600">{payment.failure_reason}</span>}
                    </span>
                    <span className="flex items-center gap-2">
                      {formatPrice(payment.amount)} <StatusBadge status={payment.status} />
                    </span>
                  </li>
                ))}
                {order.refunds.map((refund) => (
                  <li key={refund.public_id} className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      Refund · {refund.reason || (refund.manual ? 'paid by the store' : 'to the original payment')} ·{' '}
                      {dateTime(refund.processed_at ?? refund.created_at)}
                    </span>
                    <span className="flex items-center gap-2">
                      {formatPrice(refund.amount)} <StatusBadge status={refund.status} />
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>

        <div className="space-y-5">
          <Panel title="Customer">
            <Facts
              items={[
                ['Name', order.customer.name],
                ['Email', <a href={`mailto:${order.customer.email}`}>{order.customer.email}</a>],
                ['Phone', order.customer.phone ? <a href={`tel:${order.customer.phone}`}>{order.customer.phone}</a> : '—'],
                ['Account', order.customer.is_active ? 'Active' : 'Deactivated'],
              ]}
            />
            {session.is_admin && (
              <Link to={`/admin/customers/${order.customer.id}`} className="mt-3 inline-block text-sm font-semibold text-amber-700 hover:underline">
                Open customer
              </Link>
            )}
          </Panel>

          <Panel title="Delivery">
            <Facts
              items={[
                ['To', `${address.name} · ${address.phone}`],
                [
                  'Address',
                  [address.address_line1, address.address_line2, address.landmark, address.area, address.city, address.postal_code]
                    .filter(Boolean)
                    .join(', '),
                ],
                ['Store', order.store_name ?? '—'],
                ['Type', order.delivery.type_label ?? '—'],
                ['Promised', order.delivery.label || dateTime(order.estimated_delivery_at)],
                ...(order.customer_note ? ([['Customer note', order.customer_note]] as [string, string][]) : []),
                ...(order.cancellation_reason
                  ? ([['Cancelled', `${dateTime(order.cancelled_at)} · ${order.cancellation_reason}`]] as [string, string][])
                  : []),
              ]}
            />
          </Panel>

          <Panel title="History">
            <ol className="space-y-2 text-sm">
              {order.status_history.map((entry, index) => (
                <li key={`${entry.to_status}-${index}`}>
                  <span className="font-semibold">{orderStatusLabel({ status: entry.to_status, payment_method: order.payment_method })}</span>
                  <span className="block text-xs text-ink-600">
                    {dateTime(entry.created_at)}
                    {entry.note && ` · ${entry.note}`}
                  </span>
                </li>
              ))}
            </ol>
          </Panel>
        </div>
      </div>
    </>
  )
}
