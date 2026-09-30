import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { analytics, staffGet, summary } from '@/test/adminFixtures'
import { httpError, mockApi, paramsSent } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

// The chart library is large and draws nothing in jsdom (no layout). The pages are tested with
// stand-ins that show how many rows they were given; the real charts are tested in charts.test.tsx.
vi.mock('@/features/admin/charts', () => {
  const stub = (name: string) => (props: { rows: unknown[] }) => <div data-testid={name}>{props.rows.length} rows</div>
  return { RevenueChart: stub('revenue-chart'), OrdersChart: stub('orders-chart'), ShareChart: stub('share-chart') }
})

/** The card (term + value) with this label. */
function card(label: string) {
  const term = screen.getByText(label, { selector: 'dt' })
  return within(term.parentElement!)
}

describe('dashboard home', () => {
  it('shows the numbers the server sent, and nothing else', async () => {
    signIn()
    mockApi({ get: staffGet() })
    renderRoute('/admin')
    expect(await screen.findByRole('heading', { name: 'Dashboard', level: 1 })).toBeInTheDocument()

    expect(card('Orders today').getByText('7')).toBeInTheDocument()
    expect(card('Orders today').getByText('128 in total')).toBeInTheDocument()
    expect(card('Revenue today').getByText('₹9,850')).toBeInTheDocument()
    expect(card('Revenue today').getByText('₹81,200.50 this month')).toBeInTheDocument()
    expect(card('Total revenue').getByText('₹2,45,300')).toBeInTheDocument()
    expect(card('Waiting for payment').getByText('2')).toBeInTheDocument()
    expect(card('Being prepared').getByText('5')).toBeInTheDocument()
    expect(card('On the way').getByText('3')).toBeInTheDocument()
    expect(card('Delivered').getByText('104')).toBeInTheDocument()
    expect(card('Cancelled').getByText('11')).toBeInTheDocument()
    expect(card('Returns').getByText('2 open')).toBeInTheDocument()
    expect(card('Refunds waiting').getByText('₹900 · 1 failed')).toBeInTheDocument()
    expect(card('Low-stock items').getByText('1 out of stock')).toBeInTheDocument()
    expect(card('Delivery partners online').getByText('3 / 5')).toBeInTheDocument()
    expect(card('Delivery partners online').getByText('₹3,400 cash with riders')).toBeInTheDocument()
    expect(card('Active stores').getByText('2')).toBeInTheDocument()
    expect(card('Customers').getByText('86')).toBeInTheDocument()
    expect(card('Products').getByText('221 on sale')).toBeInTheDocument()

    expect(screen.getByRole('link', { name: 'Low-stock items: open' })).toHaveAttribute('href', '/admin/inventory?stock=low')
  })

  it('lists what needs attention with links to the work', async () => {
    signIn()
    mockApi({ get: staffGet() })
    renderRoute('/admin')
    // By text: a role query over the whole dashboard is slow when every test file runs at once.
    const panel = within((await screen.findByText('Needs attention')).closest('section')!)
    expect(panel.getByRole('link', { name: /Orders to prepare\s*5/ })).toHaveAttribute(
      'href',
      '/admin/orders?status=confirmed,processing',
    )
    expect(panel.getAllByRole('link')).toHaveLength(3)
  })

  it('gives the trend as a table too', async () => {
    signIn()
    mockApi({ get: staffGet() })
    renderRoute('/admin')
    expect(await screen.findByTestId('revenue-chart')).toHaveTextContent('2 rows')
    const table = await screen.findByRole('table', { name: 'Orders and revenue of the last 14 days', hidden: true })
    const row = within(table).getByRole('row', { name: /28 Sep/, hidden: true })
    expect(within(row).getByText('4')).toBeInTheDocument()
    expect(within(row).getByText('₹5,100')).toBeInTheDocument()
  })

  it('a store manager sees their store, without shop-wide customers and products', async () => {
    signIn()
    mockApi({ get: staffGet('manager') })
    renderRoute('/admin')
    expect(await screen.findByText(/^Kothrud Store · live from the database/)).toBeInTheDocument()
    expect(screen.getByText('Orders today', { selector: 'dt' })).toBeInTheDocument()
    expect(screen.queryByText('Customers', { selector: 'dt' })).not.toBeInTheDocument()
    expect(screen.queryByText('Products', { selector: 'dt' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Store')).not.toBeInTheDocument() // one store: nothing to choose
  })

  it('a new shop shows zeros and no chart', async () => {
    signIn()
    const empty = summary({
      orders: { ...summary().orders, total: 0, today: 0, pending: 0, processing: 0, on_the_way: 0, delivered: 0, cancelled: 0, delivery_failed: 0 },
      revenue: { total: '0.00', today: '0.00', this_month: '0.00', refunded_total: '0.00' },
      attention: [],
      trend: [],
    })
    mockApi({ get: staffGet('admin', { '/admin/summary/': empty }) })
    renderRoute('/admin')
    expect(await screen.findByText('No orders yet. The chart appears with the first order.')).toBeInTheDocument()
    expect(card('Total revenue').getByText('₹0')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Needs attention' })).not.toBeInTheDocument()
  })

  it('narrows the numbers to one store', async () => {
    signIn()
    const api = mockApi({ get: staffGet() })
    const { user, router } = renderRoute('/admin')
    await user.selectOptions(await screen.findByLabelText('Store'), 'Hadapsar Store')
    await waitFor(() => expect(currentUrl(router)).toBe('/admin?store=2'))
    await waitFor(() => expect(paramsSent(api.get, '/admin/summary/')).toContainEqual({ store: '2' }))
  })

  it('shows an error with a retry when the numbers can’t be loaded', async () => {
    signIn()
    let attempts = 0
    mockApi({
      get: staffGet('admin', {
        '/admin/summary/': () => (++attempts < 2 ? httpError(500, 'Server error.') : summary()),
      }),
    })
    const { user } = renderRoute('/admin')
    expect(await screen.findByText('Couldn’t load the dashboard')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Orders today', { selector: 'dt' })).toBeInTheDocument()
  })
})

describe('analytics', () => {
  it('shows sales, products, delivery, cancellations, returns and refunds from the server', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/analytics/': analytics() }) })
    renderRoute('/admin/analytics')
    expect(await screen.findByText('Revenue', { selector: 'dt' })).toBeInTheDocument()

    expect(card('Revenue').getByText('₹81,200.50')).toBeInTheDocument()
    expect(card('Revenue').getByText('₹79,400.50 after refunds')).toBeInTheDocument()
    expect(card('Orders').getByText('36 paid · 33 delivered')).toBeInTheDocument()
    expect(card('Average order value').getByText('₹2,255.57')).toBeInTheDocument()
    expect(card('Cancellations').getByText('9.5% of orders')).toBeInTheDocument()
    expect(card('Delivered on time').getByText('93.9%')).toBeInTheDocument()
    expect(card('Fast delivery on time').getByText('21 fast deliveries')).toBeInTheDocument()

    const categories = within(screen.getByRole('region', { name: 'Sales by category' }))
    expect(categories.getByText('Tools')).toBeInTheDocument()
    expect(categories.getByText('₹52,000')).toBeInTheDocument()
    expect(categories.getByText('· 60 units · 64%')).toBeInTheDocument()

    const top = within(screen.getByRole('region', { name: 'Top products' }))
    expect(top.getByText('Impact Drill 650W')).toBeInTheDocument()
    expect(top.getByText('· 14 units in 12 orders')).toBeInTheDocument()

    const slow = within(screen.getByRole('region', { name: 'Slowest products' }))
    expect(slow.getByRole('link', { name: 'Dusty Shelf Bracket' })).toHaveAttribute('href', '/admin/products/9')
    expect(slow.getByText('0 sold')).toBeInTheDocument()

    const delivery = within(screen.getByRole('table', { name: 'Delivery performance' }))
    const fast = within(delivery.getByRole('row', { name: /Fast delivery \(within 60 min\)/ }))
    expect(fast.getByText('95.2%')).toBeInTheDocument()
    expect(fast.getByText('42 min')).toBeInTheDocument()
    expect(fast.getByText('38 min')).toBeInTheDocument()
    expect(screen.getByText('Customer not available')).toBeInTheDocument()

    const cancellations = within(screen.getByRole('region', { name: 'Cancellations' }))
    expect(cancellations.getByText('₹6,100')).toBeInTheDocument()
    expect(cancellations.getByText('Ordered by mistake')).toBeInTheDocument()

    const returns = within(screen.getByRole('region', { name: 'Returns and refunds' }))
    expect(returns.getByText('3 · ₹1,800')).toBeInTheDocument()
    expect(returns.getByText('Arrived damaged')).toBeInTheDocument()

    expect(await screen.findByTestId('revenue-chart')).toHaveTextContent('2 rows')
    expect(screen.getByTestId('orders-chart')).toHaveTextContent('2 rows')
    expect(screen.getByTestId('share-chart')).toHaveTextContent('2 rows')
    const table = within(screen.getByRole('table', { name: 'Sales by period', hidden: true }))
    expect(table.getAllByRole('row', { hidden: true })).toHaveLength(3)
  })

  it('asks the server for the chosen period, grouping and store', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/admin/analytics/': analytics() }) })
    const { user, router } = renderRoute('/admin/analytics')
    await screen.findByText('Revenue', { selector: 'dt' })
    const first = paramsSent(api.get, '/admin/analytics/')[0]!
    expect(Object.keys(first).sort()).toEqual(['from', 'to'])
    const days = (Date.parse(first.to!) - Date.parse(first.from!)) / 86_400_000
    expect(days).toBe(29) // 30 days including today

    await user.selectOptions(screen.getByLabelText('Period'), 'Last 90 days')
    await user.selectOptions(screen.getByLabelText('Group by'), 'By week')
    await user.selectOptions(screen.getByLabelText('Store'), 'Kothrud Store')
    await waitFor(() => expect(currentUrl(router)).toBe('/admin/analytics?range=90&group_by=week&store=1'))
    await waitFor(() => {
      const last = paramsSent(api.get, '/admin/analytics/').at(-1)!
      expect(last).toMatchObject({ group_by: 'week', store: '1' })
      expect((Date.parse(last.to!) - Date.parse(last.from!)) / 86_400_000).toBe(89)
    })
  })

  it('says so when there were no orders in the period', async () => {
    signIn()
    const none = analytics({
      totals: { ...analytics().totals, orders: 0, paid_orders: 0, revenue: '0.00', average_order_value: null, cancellation_rate: null },
      series: [],
      category_sales: [],
      top_products: [],
    })
    mockApi({ get: staffGet('admin', { '/admin/analytics/': none }) })
    renderRoute('/admin/analytics')
    expect(await screen.findByText('No orders in this period.')).toBeInTheDocument()
    expect(card('Average order value').getByText('—')).toBeInTheDocument()
    expect(screen.getAllByText('Nothing was sold in this period.')).toHaveLength(2)
  })

  it('shows the server’s message for a period it refuses', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', { '/admin/analytics/': httpError(400, 'Choose a period of at most 366 days.', 'range_too_long') }),
    })
    renderRoute('/admin/analytics')
    expect(await screen.findByText('Couldn’t load analytics')).toBeInTheDocument()
    expect(screen.getByText('Choose a period of at most 366 days.')).toBeInTheDocument()
  })
})
