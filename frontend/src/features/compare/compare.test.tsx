import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { productPage, productSummary, wireDetail } from '@/test/fixtures'
import { mockApi, paramsSent } from '@/test/mockApi'
import { currentUrl, renderRoute } from '@/test/utils'

import type { CompareProduct, CompareResult } from './api'
import { addToCompare, COMPARE_MAX, getCompareItems } from './store'

const facets = {
  total: 0,
  categories: [],
  brands: [],
  price: { min: null, max: null },
  ratings: [],
  discounts: [],
  availability: { in_stock: 0, fast_delivery: 0 },
  specifications: [],
}

function column(overrides: Partial<CompareProduct> = {}): CompareProduct {
  return {
    id: 1,
    name: 'Impact Drill 650W',
    slug: 'impact-drill-650w',
    brand: { name: 'DrillCo', slug: 'drillco' },
    category: { name: 'Power Tools', slug: 'power-tools' },
    department: { id: 10, name: 'Tools', slug: 'tools' },
    image: null,
    image_alt: 'Impact Drill 650W',
    unit: 'piece',
    unit_label: 'Piece',
    default_variant_id: 101,
    variant_name: '',
    price: '3200.00',
    mrp: '4000.00',
    discount_percent: '20.00',
    stock_status: 'in_stock',
    rating_avg: '4.50',
    rating_count: 12,
    ...overrides,
  }
}

const drill = column()
const driver = column({
  id: 2,
  name: 'Cordless Driver',
  slug: 'cordless-driver',
  default_variant_id: 202,
  price: '2500.00',
  mrp: '2500.00',
  discount_percent: '0.00',
  rating_avg: null,
  rating_count: 0,
  stock_status: 'out_of_stock',
})

function result(overrides: Partial<CompareResult> = {}): CompareResult {
  return {
    products: [drill, driver],
    specifications: [
      { key: 'power', name: 'Power', values: ['650 W', '650 W'], differs: false },
      { key: 'chuck', name: 'Chuck size', values: ['13 mm', '10 mm'], differs: true },
      { key: 'warranty', name: 'Warranty', values: ['—', '2 years'], differs: true },
    ],
    missing: [],
    mixed_departments: false,
    max_products: 4,
    ...overrides,
  }
}

const pick = (slug: string, name: string) => addToCompare({ slug, name, image: null })

describe('compare store', () => {
  it('keeps up to four products in order, without duplicates', () => {
    for (let i = 1; i <= COMPARE_MAX; i++) expect(pick(`p-${i}`, `P${i}`)).toBe(true)
    expect(pick('p-1', 'P1')).toBe(true) // already there: unchanged
    expect(pick('p-5', 'P5')).toBe(false) // full
    expect(getCompareItems().map((i) => i.slug)).toEqual(['p-1', 'p-2', 'p-3', 'p-4'])
  })

  it('ignores corrupted storage', () => {
    window.localStorage.setItem('boltrun.compare', '{not json')
    expect(getCompareItems()).toEqual([])
    window.localStorage.setItem('boltrun.compare', JSON.stringify([{ slug: 1 }, { slug: 'ok', name: 'OK', image: null }]))
    expect(getCompareItems().map((i) => i.slug)).toEqual(['ok'])
  })
})

describe('compare toggle and tray', () => {
  it('adds from a product card, shows the tray, and opens the compare page', async () => {
    const cards = [
      productSummary(),
      productSummary({ id: 2, name: 'Cordless Driver', slug: 'cordless-driver', default_variant_id: 202 }),
    ]
    mockApi({
      get: { '/categories/': [], '/products/': productPage(cards), '/products/facets/': facets, '/products/compare/': result() },
    })
    const { user, router } = renderRoute('/products')
    await screen.findAllByRole('article')
    expect(screen.queryByTestId('compare-tray')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add Impact Drill 650W to compare' }))
    const tray = await screen.findByTestId('compare-tray')
    expect(tray).toHaveTextContent('Compare 1/4')
    expect(tray).toHaveTextContent('Add one more product')
    const card = screen.getAllByRole('article')[0]!
    expect(within(card).getByRole('button', { name: 'Remove Impact Drill 650W from compare' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: 'Add Cordless Driver to compare' }))
    expect(tray).toHaveTextContent('Compare 2/4')
    await user.click(within(tray).getByRole('link', { name: 'Compare now' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/compare'))
    expect(await screen.findByRole('heading', { level: 1, name: /Compare products/ })).toBeInTheDocument()
    // The tray stays out of the way on the compare page itself.
    expect(screen.queryByTestId('compare-tray')).not.toBeInTheDocument()
  })

  it('a fifth product is refused with a message', async () => {
    for (let i = 1; i <= 4; i++) pick(`p-${i}`, `P${i}`)
    mockApi({ get: { '/categories/': [], '/products/': productPage([productSummary()]), '/products/facets/': facets } })
    const { user } = renderRoute('/products')
    await screen.findByRole('article')
    await user.click(screen.getByRole('button', { name: 'Add Impact Drill 650W to compare' }))
    expect(await screen.findByText(/You can compare up to 4 products/)).toBeInTheDocument()
    expect(getCompareItems()).toHaveLength(4)
  })

  it('clear empties the list and hides the tray', async () => {
    pick('impact-drill-650w', 'Impact Drill 650W')
    mockApi({ get: { '/categories/': [], '/products/': productPage([productSummary()]), '/products/facets/': facets } })
    const { user } = renderRoute('/products')
    const tray = await screen.findByTestId('compare-tray')
    await user.click(within(tray).getByRole('button', { name: 'Clear' }))
    expect(screen.queryByTestId('compare-tray')).not.toBeInTheDocument()
    expect(getCompareItems()).toEqual([])
  })
})

describe('compare page', () => {
  it('shows the products side by side with merged specifications', async () => {
    pick('impact-drill-650w', 'Impact Drill 650W')
    pick('cordless-driver', 'Cordless Driver')
    const api = mockApi({ get: { '/categories/': [], '/products/compare/': result() } })
    const { user } = renderRoute('/compare')
    const table = await screen.findByRole('table', { name: 'Product comparison' })
    expect(paramsSent(api.get, '/products/compare/')).toContainEqual({ slugs: 'impact-drill-650w,cordless-driver' })
    const headers = within(table).getAllByRole('columnheader')
    expect(headers[0]).toHaveTextContent('Impact Drill 650W')
    expect(headers[0]).toHaveTextContent('₹3,200')
    expect(headers[0]).toHaveTextContent('₹4,000')
    expect(headers[1]).toHaveTextContent('Out of stock')
    expect(within(headers[0]!).getByRole('button', { name: /Add to cart/ })).toBeEnabled()
    expect(within(headers[1]!).getByRole('button', { name: 'Out of stock' })).toBeDisabled()

    const row = (name: string) => within(table).getByRole('rowheader', { name }).closest('tr') as HTMLElement
    expect(row('Warranty')).toHaveTextContent('—2 years')
    expect(row('Rating')).toHaveTextContent('4.5 (12)No reviews yet')
    expect(screen.queryByTestId('mixed-departments')).not.toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Show only differences' }))
    expect(within(table).queryByRole('rowheader', { name: 'Power' })).not.toBeInTheDocument() // same for both
    expect(within(table).queryByRole('rowheader', { name: 'Brand' })).not.toBeInTheDocument()
    expect(within(table).getByRole('rowheader', { name: 'Chuck size' })).toBeInTheDocument()
    expect(within(table).getByRole('rowheader', { name: 'Warranty' })).toBeInTheDocument()
    expect(screen.getByText(/matching rows are hidden/)).toBeInTheDocument()
  })

  it('notes mixed departments and drops products no longer on sale', async () => {
    pick('impact-drill-650w', 'Impact Drill 650W')
    pick('gone', 'Old Hinge')
    pick('cordless-driver', 'Cordless Driver')
    mockApi({
      get: {
        '/categories/': [],
        '/products/compare/': result({ missing: ['gone'], mixed_departments: true }),
      },
    })
    renderRoute('/compare')
    expect(await screen.findByTestId('mixed-departments')).toHaveTextContent('different departments')
    expect(await screen.findByText(/No longer available, removed from compare: Old Hinge/)).toBeInTheDocument()
    await waitFor(() => expect(getCompareItems().map((i) => i.slug)).toEqual(['impact-drill-650w', 'cordless-driver']))
  })

  it('removing a column updates the list; with nothing left it says how to start', async () => {
    pick('impact-drill-650w', 'Impact Drill 650W')
    mockApi({ get: { '/categories/': [], '/products/compare/': result({ products: [drill], specifications: [] }) } })
    const { user } = renderRoute('/compare')
    expect(await screen.findByText('Add at least one more product to compare.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove Impact Drill 650W from compare' }))
    expect(await screen.findByText('Nothing to compare yet')).toBeInTheDocument()
  })
})

describe('product page compare button', () => {
  it('toggles the product in the compare list', async () => {
    const detail = wireDetail()
    mockApi({
      get: {
        '/categories/': [],
        [`/products/${detail.slug}/`]: detail,
        [`/products/${detail.slug}/reviews/`]: { count: 0, next: null, previous: null, results: [] },
        '/products/': productPage([]),
      },
    })
    const { user } = renderRoute(`/p/${detail.slug}`)
    await user.click(await screen.findByRole('button', { name: 'Compare' }))
    expect(screen.getByRole('button', { name: 'Added to compare' })).toHaveAttribute('aria-pressed', 'true')
    expect(getCompareItems().map((i) => i.slug)).toEqual([detail.slug])
    expect(await screen.findByTestId('compare-tray')).toBeInTheDocument()
  })
})
