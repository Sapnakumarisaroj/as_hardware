import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { ErrorState, PageSpinner, Spinner } from '@/components/feedback'
import { useAnalytics, useSummary } from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { Analytics, DeliveryGroup, GroupBy, SeriesRow } from '@/features/admin/types'
import { dateTime, FilterSelect, PageHeader, Panel, StatCard, useListParams } from '@/features/admin/ui'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

type Charts = typeof import('@/features/admin/charts')
let chartModule: Charts | null = null

/**
 * The chart library, fetched the first time a chart is shown. Loaded with a plain import and not
 * React.lazy: a suspended chart would hold back the filter change that caused it.
 */
function useCharts(): Charts | null {
  const [charts, setCharts] = useState(chartModule)
  useEffect(() => {
    if (charts) return
    let active = true
    void import('@/features/admin/charts').then((module) => {
      chartModule = module
      if (active) setCharts(module)
    })
    return () => {
      active = false
    }
  }, [charts])
  return charts
}

const number = (value: number) => value.toLocaleString('en-IN')
const percent = (value: number | null) => (value === null ? '—' : `${value}%`)
const minutes = (value: number | null) => (value === null ? '—' : `${Math.round(value)} min`)

function Chart({ children }: { children: (charts: Charts) => ReactNode }) {
  const charts = useCharts()
  if (!charts) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner label="Loading chart…" />
      </div>
    )
  }
  return <>{children(charts)}</>
}

function SeriesTable({ rows, caption }: { rows: SeriesRow[]; caption: string }) {
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer font-semibold text-ink-600 hover:text-ink-900">Show the numbers as a table</summary>
      <div className="mt-2 max-h-72 overflow-auto">
        <table className="w-full text-left">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 bg-white text-xs uppercase text-ink-600">
            <tr>
              <th scope="col" className="py-1.5 pr-3">
                Period
              </th>
              {['Orders', 'Delivered', 'Cancelled', 'Revenue', 'Refunded', 'Avg. order'].map((name) => (
                <th key={name} scope="col" className="py-1.5 pl-3 text-right">
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((row) => (
              <tr key={row.start} className="border-t border-steel-100">
                <th scope="row" className="py-1.5 pr-3 font-medium">
                  {row.label}
                </th>
                <td className="py-1.5 pl-3 text-right">{row.orders}</td>
                <td className="py-1.5 pl-3 text-right">{row.delivered}</td>
                <td className="py-1.5 pl-3 text-right">{row.cancelled}</td>
                <td className="py-1.5 pl-3 text-right">{formatPrice(row.revenue)}</td>
                <td className="py-1.5 pl-3 text-right">{formatPrice(row.refunded)}</td>
                <td className="py-1.5 pl-3 text-right">{formatPrice(row.average_order_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

function StoreFilter() {
  const session = useSession()
  const list = useListParams()
  if (session.stores.length < 2) return null
  return (
    <FilterSelect
      list={list}
      name="store"
      label="Store"
      all="All stores"
      options={session.stores.map((store) => [String(store.id), store.name])}
    />
  )
}

// --- Dashboard -----------------------------------------------------------------------------------

export function AdminDashboardPage() {
  usePageMeta('Dashboard')
  const session = useSession()
  const list = useListParams()
  const summary = useSummary(list.get('store'))

  if (summary.isPending) return <PageSpinner label="Loading today’s numbers…" />
  if (summary.isError) {
    return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} title="Couldn’t load the dashboard" />
  }
  const data = summary.data
  const hasOrders = data.orders.total > 0

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={
          <>
            {session.is_admin ? 'The whole shop' : session.stores.map((store) => store.name).join(', ') || 'No store assigned yet'}
            {' · '}live from the database, updated {dateTime(data.generated_at)}
          </>
        }
        actions={<StoreFilter />}
      />

      {data.attention.length > 0 && (
        <Panel title="Needs attention" className="mb-5">
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {data.attention.map((item) => (
              <li key={item.code}>
                <Link
                  to={item.link}
                  className="flex items-center justify-between gap-3 rounded-md bg-amber-100 px-3 py-2.5 text-sm font-medium hover:bg-amber-500/30"
                >
                  <span>{item.label}</span>
                  <span className="text-lg font-extrabold tabular-nums">{item.count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Orders today" value={number(data.orders.today)} hint={`${number(data.orders.total)} in total`} to="/admin/orders" />
        <StatCard label="Revenue today" value={formatPrice(data.revenue.today)} hint={`${formatPrice(data.revenue.this_month)} this month`} />
        <StatCard label="Total revenue" value={formatPrice(data.revenue.total)} hint={`${formatPrice(data.revenue.refunded_total)} refunded`} />
        <StatCard label="Waiting for payment" value={number(data.orders.pending)} to="/admin/orders?status=pending" />
        <StatCard label="Being prepared" value={number(data.orders.processing)} to="/admin/orders?status=preparing" />
        <StatCard label="On the way" value={number(data.orders.on_the_way)} to="/admin/orders?status=on_the_way" />
        <StatCard label="Delivered" value={number(data.orders.delivered)} to="/admin/orders?status=delivered" />
        <StatCard label="Cancelled" value={number(data.orders.cancelled)} to="/admin/orders?status=cancelled" />
        <StatCard label="Returns" value={number(data.returns.total)} hint={`${number(data.returns.open)} open`} to="/admin/returns" />
        <StatCard
          label="Refunds waiting"
          value={number(data.refunds.pending)}
          hint={`${formatPrice(data.refunds.pending_amount)} · ${number(data.refunds.failed)} failed`}
          tone={data.refunds.failed > 0 ? 'warn' : 'plain'}
          to="/admin/refunds"
        />
        <StatCard
          label="Low-stock items"
          value={number(data.inventory.low_stock)}
          hint={`${number(data.inventory.out_of_stock)} out of stock`}
          tone={data.inventory.out_of_stock > 0 ? 'warn' : 'plain'}
          to="/admin/inventory?stock=low"
        />
        <StatCard
          label="Delivery partners online"
          value={`${number(data.delivery.partners_online)} / ${number(data.delivery.partners)}`}
          hint={`${formatPrice(data.delivery.cash_with_riders)} cash with riders`}
          to="/admin/delivery"
        />
        <StatCard
          label="Active stores"
          value={number(data.stores.active)}
          hint={`${number(data.stores.accepting_orders)} accepting orders`}
          to="/admin/stores"
        />
        {data.customers && (
          <StatCard
            label="Customers"
            value={number(data.customers.total)}
            hint={`${number(data.customers.new_this_month)} new this month`}
            to="/admin/customers"
          />
        )}
        {data.products && (
          <StatCard
            label="Products"
            value={number(data.products.total)}
            hint={`${number(data.products.published)} on sale`}
            to="/admin/products"
          />
        )}
      </dl>

      <Panel
        title="Last 14 days"
        className="mt-5"
        action={
          <Link to="/admin/analytics" className="text-sm font-semibold text-amber-700 hover:underline">
            Open analytics
          </Link>
        }
      >
        {hasOrders ? (
          <>
            <Chart>{(charts) => <charts.RevenueChart rows={data.trend} />}</Chart>
            <SeriesTable rows={data.trend} caption="Orders and revenue of the last 14 days" />
          </>
        ) : (
          <p className="py-8 text-center text-sm text-ink-600">No orders yet. The chart appears with the first order.</p>
        )}
      </Panel>
    </>
  )
}

// --- Analytics -----------------------------------------------------------------------------------

const RANGES: [string, string][] = [
  ['7', 'Last 7 days'],
  ['30', 'Last 30 days'],
  ['90', 'Last 90 days'],
  ['365', 'Last 12 months'],
]

function isoDay(daysAgo: number): string {
  const day = new Date(Date.now() - daysAgo * 86_400_000)
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(day) // YYYY-MM-DD
}

function BarRows({ rows, empty }: { rows: { name: string; value: string; detail: string; share: number }[]; empty: string }) {
  if (rows.length === 0) return <p className="py-6 text-center text-sm text-ink-600">{empty}</p>
  return (
    <ol className="space-y-2.5 text-sm">
      {rows.map((row) => (
        <li key={row.name}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-medium">{row.name}</span>
            <span className="whitespace-nowrap tabular-nums">
              <span className="font-semibold">{row.value}</span> <span className="text-ink-600">· {row.detail}</span>
            </span>
          </div>
          <div aria-hidden className="mt-1 h-1.5 rounded-full bg-steel-100">
            <div className="h-full rounded-full bg-amber-500" style={{ width: `${Math.max(Math.min(row.share, 100), 1)}%` }} />
          </div>
        </li>
      ))}
    </ol>
  )
}

function DeliveryTable({ delivery }: { delivery: Analytics['delivery'] }) {
  const rows: [string, DeliveryGroup][] = [
    ['All deliveries', delivery.all],
    [`Fast delivery (within ${delivery.fast_window_minutes} min)`, delivery.fast],
    ['Standard delivery', delivery.standard],
  ]
  return (
    <table className="w-full text-left text-sm">
      <caption className="sr-only">Delivery performance</caption>
      <thead className="text-xs uppercase text-ink-600">
        <tr>
          <th scope="col" className="py-1.5 pr-3">
            Type
          </th>
          {['Delivered', 'On time', 'Promised', 'Actual'].map((name) => (
            <th key={name} scope="col" className="py-1.5 pl-3 text-right">
              {name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {rows.map(([name, group]) => (
          <tr key={name} className="border-t border-steel-100">
            <th scope="row" className="py-1.5 pr-3 font-medium">
              {name}
            </th>
            <td className="py-1.5 pl-3 text-right">{group.delivered}</td>
            <td className="py-1.5 pl-3 text-right">{percent(group.on_time_rate)}</td>
            <td className="py-1.5 pl-3 text-right">{minutes(group.average_promised_minutes)}</td>
            <td className="py-1.5 pl-3 text-right">{minutes(group.average_actual_minutes)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Reasons({ rows, empty }: { rows: { name: string; count: number }[]; empty: string }) {
  if (rows.length === 0) return <p className="text-sm text-ink-600">{empty}</p>
  return (
    <ul className="space-y-1 text-sm">
      {rows.map((row) => (
        <li key={row.name} className="flex justify-between gap-3">
          <span>{row.name}</span>
          <span className="font-semibold tabular-nums">{row.count}</span>
        </li>
      ))}
    </ul>
  )
}

export function AdminAnalyticsPage() {
  usePageMeta('Analytics')
  const list = useListParams()
  const range = list.get('range') || '30'
  const days = Number(range) || 30
  const analytics = useAnalytics({
    from: isoDay(days - 1),
    to: isoDay(0),
    group_by: list.get('group_by'),
    store: list.get('store'),
  })

  const filters = (
    <>
      <StoreFilter />
      <div>
        <label htmlFor="range" className="sr-only">
          Period
        </label>
        <select id="range" className="input w-auto" value={range} onChange={(e) => list.set({ range: e.target.value, group_by: '' })}>
          {RANGES.map(([value, name]) => (
            <option key={value} value={value}>
              {name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="group-by" className="sr-only">
          Group by
        </label>
        <select
          id="group-by"
          className="input w-auto"
          value={analytics.data?.period.group_by ?? list.get('group_by')}
          onChange={(e) => list.set({ group_by: e.target.value as GroupBy })}
        >
          <option value="day">By day</option>
          <option value="week">By week</option>
          <option value="month">By month</option>
        </select>
      </div>
    </>
  )

  if (analytics.isPending) {
    return (
      <>
        <PageHeader title="Analytics" actions={filters} />
        <PageSpinner label="Adding up the numbers…" />
      </>
    )
  }
  if (analytics.isError) {
    return (
      <>
        <PageHeader title="Analytics" actions={filters} />
        <ErrorState error={analytics.error} onRetry={() => void analytics.refetch()} title="Couldn’t load analytics" />
      </>
    )
  }
  const data = analytics.data
  const { totals } = data
  const topSales = Math.max(...data.top_products.map((p) => Number(p.sales)), 1)

  return (
    <div aria-busy={analytics.isFetching}>
      <PageHeader
        title="Analytics"
        description={`${data.period.from} to ${data.period.to}. Revenue counts paid orders by the day they were placed; refunds count on the day they were paid back.`}
        actions={filters}
      />

      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Revenue" value={formatPrice(totals.revenue)} hint={`${formatPrice(totals.net_revenue)} after refunds`} />
        <StatCard label="Orders" value={number(totals.orders)} hint={`${number(totals.paid_orders)} paid · ${number(totals.delivered)} delivered`} />
        <StatCard label="Average order value" value={formatPrice(totals.average_order_value)} />
        <StatCard label="Refunded" value={formatPrice(totals.refunded)} hint={`${number(data.refunds.processed)} refunds paid`} />
        <StatCard label="Cancellations" value={number(totals.cancelled)} hint={`${percent(totals.cancellation_rate)} of orders`} />
        <StatCard label="Returns" value={number(data.returns.count)} hint={`${percent(data.returns.rate)} of delivered orders`} />
        <StatCard label="Delivered on time" value={percent(data.delivery.all.on_time_rate)} hint={`${number(data.delivery.all.delivered)} deliveries`} />
        <StatCard
          label="Fast delivery on time"
          value={percent(data.delivery.fast.on_time_rate)}
          hint={`${number(data.delivery.fast.delivered)} fast deliveries`}
        />
      </dl>

      {totals.orders === 0 ? (
        <Panel className="mt-5">
          <p className="py-8 text-center text-sm text-ink-600">No orders in this period.</p>
        </Panel>
      ) : (
        <>
          <Panel title="Sales" className="mt-5">
            <Chart>{(charts) => <charts.RevenueChart rows={data.series} />}</Chart>
            <SeriesTable rows={data.series} caption="Sales by period" />
          </Panel>
          <Panel title="Orders over time" className="mt-5">
            <Chart>{(charts) => <charts.OrdersChart rows={data.series} />}</Chart>
          </Panel>
        </>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel title="Sales by category">
          {data.category_sales.length > 0 && (
            <Chart>{(charts) => <charts.ShareChart rows={data.category_sales.map((row) => ({ name: row.category, value: Number(row.sales) }))} />}</Chart>
          )}
          <BarRows
            empty="Nothing was sold in this period."
            rows={data.category_sales.map((row) => ({
              name: row.category,
              value: formatPrice(row.sales),
              detail: `${number(row.units)} units · ${percent(row.share)}`,
              share: row.share ?? 0,
            }))}
          />
        </Panel>

        <Panel title="Top products">
          <BarRows
            empty="Nothing was sold in this period."
            rows={data.top_products.map((row) => ({
              name: row.name,
              value: formatPrice(row.sales),
              detail: `${number(row.units)} units in ${number(row.orders)} orders`,
              share: (Number(row.sales) * 100) / topSales,
            }))}
          />
        </Panel>

        <Panel title="Slowest products">
          <p className="mb-2 text-xs text-ink-600">Products on sale with the fewest units sold in this period.</p>
          {data.low_performing_products.length === 0 ? (
            <p className="text-sm text-ink-600">No products are on sale.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {data.low_performing_products.map((row) => (
                <li key={row.product_id} className="flex justify-between gap-3">
                  <Link to={`/admin/products/${row.product_id}`} className="hover:underline">
                    {row.name}
                  </Link>
                  <span className="font-semibold tabular-nums">{number(row.units)} sold</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Delivery performance">
          <DeliveryTable delivery={data.delivery} />
          <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
            <div>
              <dt className="text-ink-600">Delivered first time</dt>
              <dd className="font-bold">{percent(data.delivery.first_attempt_rate)}</dd>
            </div>
            <div>
              <dt className="text-ink-600">Failed attempts</dt>
              <dd className="font-bold">{number(data.delivery.failed_attempts)}</dd>
            </div>
            <div>
              <dt className="text-ink-600">By delivery partners</dt>
              <dd className="font-bold">{number(data.delivery.delivered_by_partners)}</dd>
            </div>
          </dl>
          {data.delivery.failure_reasons.length > 0 && (
            <div className="mt-3">
              <h3 className="mb-1 text-sm font-semibold">Why deliveries failed</h3>
              <Reasons empty="" rows={data.delivery.failure_reasons.map((r) => ({ name: r.label, count: r.count }))} />
            </div>
          )}
        </Panel>

        <Panel title="Cancellations">
          <p className="mb-2 text-sm">
            <span className="font-bold">{number(data.cancellations.count)}</span> orders worth{' '}
            <span className="font-bold">{formatPrice(data.cancellations.value)}</span> ({percent(data.cancellations.rate)})
          </p>
          <Reasons
            empty="No cancellation reasons in this period."
            rows={data.cancellations.reasons.map((r) => ({ name: r.reason, count: r.count }))}
          />
        </Panel>

        <Panel title="Returns and refunds">
          <dl className="mb-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
            {(
              [
                ['Returns requested', number(data.returns.count)],
                ['Still open', number(data.returns.open)],
                ['Received', number(data.returns.received)],
                ['Rejected', number(data.returns.rejected)],
                ['Refunds requested', `${number(data.refunds.requested)} · ${formatPrice(data.refunds.requested_amount)}`],
                ['Refunds paid', `${number(data.refunds.processed)} · ${formatPrice(data.refunds.processed_amount)}`],
                ['Refunds waiting', number(data.refunds.pending)],
                ['Refunds failed', number(data.refunds.failed)],
              ] as const
            ).map(([name, value]) => (
              <div key={name}>
                <dt className="text-ink-600">{name}</dt>
                <dd className="font-bold">{value}</dd>
              </div>
            ))}
          </dl>
          <h3 className="mb-1 text-sm font-semibold">Why customers returned items</h3>
          <Reasons empty="No returns in this period." rows={data.returns.reasons.map((r) => ({ name: r.label, count: r.count }))} />
        </Panel>
      </div>
    </div>
  )
}
