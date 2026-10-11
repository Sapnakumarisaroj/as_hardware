import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { savePincode } from '@/features/delivery/location'
import type { PriceQuote, ProductFacets } from '@/features/catalog/types'
import { cart, cartLine, customer, facets, productPage, productSummary, wireDetail } from '@/test/fixtures'
import { httpError, mockApi, paramsSent, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

/* Phase 16 storefront: product-page trust information and content, PIN-aware delivery flags, payment
   options, Buy Now, recently viewed, brand pages, search words understood as filters, option filters. */

const reviews = { count: 0, next: null, previous: null, results: [] }
const bits = productSummary({ id: 9, name: 'Masonry Drill Bits', slug: 'masonry-bits', default_variant_id: 909 })

function quote(overrides: Partial<PriceQuote> = {}): PriceQuote {
  return {
    product_id: 1,
    variant_id: 201,
    sku: 'DEMO-WIRE-15-10',
    options: {},
    quantity: 1,
    mrp: '500.00',
    base_unit_price: '400.00',
    unit_price: '400.00',
    applied_tier: null,
    next_tier: null,
    price_tiers: [],
    line_total: '400.00',
    bulk_saving: '0.00',
    offer_discount: '0.00',
    offers: [],
    total: '400.00',
    savings_vs_mrp: '100.00',
    stock_status: 'in_stock',
    within_stock: true,
    max_order_quantity: 50,
    payment_options: { online: true, cod: { available: true, reason_code: '', message: '', max_order_value: '10000.00' } },
    note: 'Preview.',
    ...overrides,
  }
}

const richDetail = wireDetail({
  quick_answer: 'For house wiring: lights and fans.',
  uses: ['Lights and fans', 'Switch boards'],
  installation_steps: ['Switch off the mains', 'Strip 10 mm of insulation'],
  faqs: [{ question: 'Is it fire retardant?', answer: 'Yes, FR PVC insulation.' }],
  return_policy: { returnable: true, window_days: 7, text: 'Returnable within 7 days of delivery.' },
  accessories: [{ ...bits, relation_note: 'To fix the clamps' }],
  free_delivery: { name: 'Wires from ₹2,000', threshold: '2000.00' },
})

function detailRoutes(extra: Record<string, unknown> = {}) {
  return {
    '/categories/': [],
    '/products/fr-pvc-copper-wire/': richDetail,
    '/products/fr-pvc-copper-wire/reviews/': reviews,
    '/products/fr-pvc-copper-wire/quote/': quote(),
    '/products/': productPage([]),
    ...extra,
  }
}

describe('product page (Phase 16)', () => {
  it('shows the shop’s quick answer, uses, steps, FAQ, returns, accessories and structured data', async () => {
    mockApi({ get: detailRoutes() })
    renderRoute('/p/fr-pvc-copper-wire')
    expect(await screen.findByTestId('quick-answer')).toHaveTextContent('For house wiring: lights and fans.')
    expect(screen.getByRole('region', { name: 'Recommended uses' })).toHaveTextContent('Switch boards')
    const steps = within(screen.getByRole('region', { name: 'How to install / use' })).getAllByRole('listitem')
    expect(steps.map((li) => li.textContent)).toEqual(['Switch off the mains', 'Strip 10 mm of insulation'])
    expect(screen.getByText('Is it fire retardant?')).toBeInTheDocument()
    expect(screen.getByTestId('return-policy')).toHaveTextContent('Returnable within 7 days of delivery.')
    const accessories = await screen.findByRole('region', { name: 'Goes well with' })
    expect(within(accessories).getByRole('link', { name: 'Masonry Drill Bits' })).toHaveAttribute('href', '/p/masonry-bits')
    expect(accessories).toHaveTextContent('To fix the clamps')
    expect(screen.getByTestId('free-delivery-rule')).toHaveTextContent('Wires from ₹2,000')
    expect(screen.getByText(/Price includes 18% GST/)).toBeInTheDocument()
    // Payment options come from the quote (same COD rules as checkout).
    expect(await screen.findByTestId('payment-options')).toHaveTextContent('Cash on delivery · for orders up to ₹10,000')
    // SEO: product structured data and a canonical URL without query parameters.
    const ld = document.head.querySelector('script[type="application/ld+json"]')
    expect(JSON.parse(ld?.textContent ?? '{}')).toMatchObject({ '@type': 'Product', name: 'FR PVC Insulated Copper Wire' })
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')).toMatch(/\/p\/fr-pvc-copper-wire$/)
    // Remembered for "Recently viewed".
    expect(JSON.parse(window.localStorage.getItem('boltrun.recently-viewed') ?? '[]')).toEqual(['fr-pvc-copper-wire'])
  })

  it('shows highlights, description, FAQ and returns as expandable sections', async () => {
    const detail = {
      ...richDetail,
      highlights: ['Heat and water resistant', 'High coverage'],
      description: 'Synthetic resin adhesive for woodworking.',
    }
    mockApi({ get: detailRoutes({ '/products/fr-pvc-copper-wire/': detail }) })
    const { user } = renderRoute('/p/fr-pvc-copper-wire')
    const info = await screen.findByTestId('product-info')
    const highlights = within(info).getByRole('list', { name: 'Product highlights' })
    expect(within(highlights).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Heat and water resistant',
      'High coverage',
    ])
    const sections = Array.from(info.querySelectorAll(':scope > details'))
    expect(sections.map((s) => s.querySelector('summary')?.textContent)).toEqual([
      'Product highlights',
      'Product description',
      'FAQs',
      'Returns policy',
    ])
    expect(sections[0]).toHaveAttribute('open') // highlights start open; the rest are collapsed
    expect(sections[1]).not.toHaveAttribute('open')
    await user.click(within(info).getByText('Product description'))
    expect(sections[1]).toHaveAttribute('open')
    expect(sections[1]).toHaveTextContent('Synthetic resin adhesive for woodworking.')
  })

  it('hides content sections the shop has not written', async () => {
    mockApi({ get: detailRoutes({ '/products/fr-pvc-copper-wire/': wireDetail() }) })
    renderRoute('/p/fr-pvc-copper-wire')
    await screen.findByRole('heading', { level: 1 })
    for (const name of ['Recommended uses', 'How to install / use', 'Questions & answers', 'Goes well with']) {
      expect(screen.queryByRole('region', { name })).not.toBeInTheDocument()
    }
    expect(screen.queryByTestId('quick-answer')).not.toBeInTheDocument()
    // Only the returns policy is always there: no empty highlights or FAQ sections.
    const info = screen.getByTestId('product-info')
    expect(within(info).queryByText('Product highlights')).not.toBeInTheDocument()
    expect(within(info).queryByText('FAQs')).not.toBeInTheDocument()
    expect(within(info).getByText('Returns policy')).toBeInTheDocument()
  })

  it('says why cash on delivery isn’t available for this amount', async () => {
    const cod = { available: false, reason_code: 'cod_limit', message: 'Cash on Delivery isn’t available for orders above ₹10,000.', max_order_value: '10000.00' }
    mockApi({ get: detailRoutes({ '/products/fr-pvc-copper-wire/quote/': quote({ payment_options: { online: true, cod } }) }) })
    renderRoute('/p/fr-pvc-copper-wire')
    expect(await screen.findByTestId('payment-options')).toHaveTextContent('Cash on Delivery isn’t available for orders above ₹10,000.')
  })

  it('sends the chosen PIN and shows the fast badge only when the server says fast to that PIN', async () => {
    savePincode('411038')
    const api = mockApi({
      get: detailRoutes({
        '/products/fr-pvc-copper-wire/': { ...richDetail, delivery: { postal_code: '411038', deliverable: true, fast: true } },
        '/delivery/estimate/': httpError(500, 'Server error.'),
      }),
    })
    renderRoute('/p/fr-pvc-copper-wire')
    expect(await screen.findByTestId('fast-badge')).toHaveTextContent('Fast delivery to 411038')
    expect(paramsSent(api.get, '/products/fr-pvc-copper-wire/')).toContainEqual({ postal_code: '411038' })
    await waitFor(() =>
      expect(paramsSent(api.get, '/products/fr-pvc-copper-wire/quote/')).toContainEqual(
        expect.objectContaining({ quantity: 1, postal_code: '411038' }),
      ),
    )
  })

  it('Buy now adds the chosen quantity and goes to checkout', async () => {
    signIn()
    const api = mockApi({
      get: { ...detailRoutes(), '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/cart/': cart() },
      post: { '/cart/items/': cart({ items: [cartLine()] }) },
    })
    const { user, router } = renderRoute('/p/fr-pvc-copper-wire')
    await screen.findByRole('heading', { level: 1 })
    await user.click(screen.getAllByRole('button', { name: 'Increase quantity' })[0]!)
    await user.click(screen.getAllByRole('button', { name: 'Buy now' })[0]!)
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/', { variant_id: 201, quantity: 2 }))
    await waitFor(() => expect(currentUrl(router)).toBe('/checkout'))
  })

  it('Buy now when signed out asks to sign in and continues to checkout', async () => {
    mockApi({ get: detailRoutes() })
    const { user, router } = renderRoute('/p/fr-pvc-copper-wire')
    await screen.findByRole('heading', { level: 1 })
    await user.click(screen.getAllByRole('button', { name: 'Buy now' })[0]!)
    await waitFor(() => expect(currentUrl(router)).toBe('/login?next=%2Fcheckout'))
  })
})

const brands = [
  { id: 1, name: 'VoltLine', slug: 'voltline', logo: null, description: 'Wires and switches.', product_count: 4 },
  { id: 2, name: 'Empty Co', slug: 'empty-co', logo: null, description: '', product_count: 0 },
  { id: 3, name: 'AquaFlow', slug: 'aquaflow', logo: null, description: '', product_count: 2 },
]

describe('brand pages', () => {
  it('/brands lists brands with products, A–Z groups and counts', async () => {
    mockApi({ get: { '/categories/': [], '/brands/': brands } })
    renderRoute('/brands')
    expect(await screen.findByRole('link', { name: /VoltLine\s*4 products/ })).toHaveAttribute('href', '/brand/voltline')
    expect(screen.getByRole('link', { name: /AquaFlow\s*2 products/ })).toBeInTheDocument()
    expect(screen.queryByText('Empty Co')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'V' })).toBeInTheDocument()
  })

  it('/brand/:slug shows the brand and its products through the listing API', async () => {
    const api = mockApi({
      get: {
        '/categories/': [],
        '/brands/voltline/': brands[0],
        '/products/': productPage([productSummary()]),
        '/products/facets/': facets(),
      },
    })
    renderRoute('/brand/voltline')
    expect(await screen.findByRole('heading', { level: 1, name: 'VoltLine' })).toBeInTheDocument()
    expect(screen.getByText('Wires and switches.')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Impact Drill 650W' })).toBeInTheDocument()
    expect(paramsSent(api.get, '/products/').at(-1)).toMatchObject({ brand: 'voltline' })
    expect(document.title).toContain('VoltLine')
  })

  it('unknown brand renders not found', async () => {
    mockApi({ get: { '/categories/': [], '/brands/nope/': httpError(404, 'Not found.') } })
    renderRoute('/brand/nope')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})

const optionFacets: ProductFacets = facets({
  options: [
    { slug: 'grade', name: 'Grade', values: [{ slug: '53-grade', value: '53 Grade', count: 1 }, { slug: 'ppc', value: 'PPC', count: 1 }] },
  ],
})

describe('search and filters (Phase 16)', () => {
  it('shows filters understood from the search words and can search everything instead', async () => {
    const api = mockApi({
      get: {
        '/categories/': [],
        '/products/facets/': optionFacets,
        '/products/': ({ params }: RequestInfo) => ({
          ...productPage([productSummary({ name: 'OPC 53 Grade Cement', slug: 'opc' })]),
          search: {
            query: '53 grade cement',
            matched: 'all_terms',
            ...(params.interpret === '0'
              ? {}
              : { interpreted: [{ param: 'opt_grade', value: '53-grade', label: 'Grade: 53 Grade' }, { param: 'category', value: 'cement', label: 'Cement' }] }),
          },
        }),
      },
    })
    const { user } = renderRoute('/search?q=53+grade+cement')
    const note = await screen.findByTestId('interpreted')
    expect(note).toHaveTextContent('Showing Grade: 53 Grade · Cement for “53 grade cement”.')
    await user.click(within(note).getByRole('button', { name: 'Search all products instead' }))
    await waitFor(() => expect(paramsSent(api.get, '/products/').at(-1)).toMatchObject({ q: '53 grade cement', interpret: '0' }))
    await waitFor(() => expect(screen.queryByTestId('interpreted')).not.toBeInTheDocument())
  })

  it('offers product options from the facets as filters and removable chips', async () => {
    const api = mockApi({ get: { '/categories/': [], '/products/': productPage([productSummary()]), '/products/facets/': optionFacets } })
    const { user } = renderRoute('/products')
    const filters = await screen.findByRole('complementary', { name: 'Filters' })
    const grade = await within(filters).findByRole('group', { name: 'Grade' })
    await user.click(within(grade).getByRole('checkbox', { name: /53 Grade/ }))
    await waitFor(() => expect(paramsSent(api.get, '/products/').at(-1)).toMatchObject({ opt_grade: '53-grade' }))
    await user.click(screen.getByRole('button', { name: 'Remove filter Grade: 53 Grade' }))
    await waitFor(() => expect(paramsSent(api.get, '/products/').at(-1)?.opt_grade).toBeUndefined())
  })

  it('offers the fast-delivery filter only for a chosen PIN', async () => {
    const withFast = facets({ availability: { in_stock: 2, fast_delivery: 1 } })
    mockApi({ get: { '/categories/': [], '/products/': productPage([productSummary()]), '/products/facets/': withFast } })
    const first = renderRoute('/products')
    const filters = await screen.findByRole('complementary', { name: 'Filters' })
    await within(filters).findByRole('checkbox', { name: /In stock only/ })
    expect(within(filters).queryByRole('checkbox', { name: /Fast delivery/ })).not.toBeInTheDocument()
    first.unmount()

    savePincode('411038')
    const api = mockApi({ get: { '/categories/': [], '/products/': productPage([productSummary()]), '/products/facets/': withFast } })
    renderRoute('/products')
    const again = await screen.findByRole('complementary', { name: 'Filters' })
    expect(await within(again).findByRole('checkbox', { name: /Fast delivery to 411038/ })).toBeInTheDocument()
    expect(paramsSent(api.get, '/products/facets/').at(-1)).toMatchObject({ postal_code: '411038' })
  })
})
