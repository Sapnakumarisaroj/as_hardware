import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { seriesRow } from '@/test/adminFixtures'

import { OrdersChart, RevenueChart, ShareChart } from './charts'

/** jsdom has no layout, so nothing is drawn; this checks the charts accept API data as it comes. */
describe('charts', () => {
  const rows = [seriesRow({ start: '2026-09-28', label: '28 Sep' }), seriesRow({ average_order_value: null, revenue: '0.00' })]

  it.each([
    ['revenue', <RevenueChart rows={rows} />],
    ['orders', <OrdersChart rows={rows} />],
    ['category share', <ShareChart rows={[{ name: 'Tools', value: 52000 }, { name: 'Paint', value: 29200.5 }]} />],
    ['empty', <RevenueChart rows={[]} />],
  ])('%s chart renders, hidden from screen readers (the table carries the numbers)', (_name, chart) => {
    const { container } = render(chart)
    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true')
  })
})
