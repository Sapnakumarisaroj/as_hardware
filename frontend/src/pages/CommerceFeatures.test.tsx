import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { PriceQuote, PriceTier, ProductVariant } from '@/features/catalog/types'
import {
  cart,
  cartLine,
  checkoutPreview,
  customer,
  productPage,
  productSummary,
  TOTALS_800,
  variant,
  wireDetail,
} from '@/test/fixtures'
import { mockApi, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

/* Phase 15 on the customer side: bulk prices, structured options, offer conditions, free-delivery
   messages, cash-on-delivery rules and three-level categories. Every number comes from the server. */

const TIERS: PriceTier[] = [
  { min_quantity: 1, max_quantity: 9, unit_price: '450.00', saving_percent: '0.00', is_base: true },
  { min_quantity: 10, max_quantity: 29, unit_price: '415.00', saving_percent: '7.78', is_base: false },
  { min_quantity: 30, max_quantity: null, unit_price: '405.00', saving_percent: '10.00', is_base: false },
]

function cementVariants(): ProductVariant[] {
  return [
    variant({
      id: 301,
      sku: 'CEM-53-50',
      name: '',
      attributes: { Grade: '53 Grade', 'Bag size': '50 kg' },
      mrp: '480.00',
      price: '450.00',
      discount_percent: '6.25',
      discount_amount: '30.00',
      is_default: true,
      price_tiers: TIERS,
      options: { grade: '53-grade', 'bag-size': '50-kg' },
    }),
    variant({
      id: 302,
      sku: 'CEM-43-50',
      name: '',
      attributes: { Grade: '43 Grade', 'Bag size': '50 kg' },
      mrp: '460.00',
      price: '430.00',
      discount_percent: '6.52',
      discount_amount: '30.00',
      price_tiers: [],
      options: { grade: '43-grade', 'bag-size': '50-kg' },
    }),
    variant({
      id: 303,
      sku: 'CEM-53-25',
      name: '',
      attributes: { Grade: '53 Grade', 'Bag size': '25 kg' },
      mrp: '250.00',
      price: '235.00',
      discount_percent: '6.00',
      discount_amount: '15.00',
      price_tiers: [],
      options: { grade: '53-grade', 'bag-size': '25-kg' },
    }),
  ]
}

const cement = wireDetail({
  id: 9,
  name: 'OPC Cement',
  slug: 'opc-cement',
  category: { id: 41, name: 'Cement', slug: 'cement' },
  subcategory: { id: 42, name: 'Grey Cement', slug: 'grey-cement' },
  breadcrumb: [
    { id: 40, name: 'Civil & Interiors', slug: 'civil-interiors' },
    { id: 41, name: 'Cement', slug: 'cement' },
    { id: 42, name: 'Grey Cement', slug: 'grey-cement' },
  ],
  max_order_quantity: 50,
  variants: cementVariants(),
  options: [
    { slug: 'grade', name: 'Grade', unit: '', values: [{ slug: '53-grade', value: '53 Grade' }, { slug: '43-grade', value: '43 Grade' }] },
    { slug: 'bag-size', name: 'Bag size', unit: 'kg', values: [{ slug: '50-kg', value: '50 kg' }, { slug: '25-kg', value: '25 kg' }] },
  ],
  bulk_pricing: { from_quantity: 10, lowest_unit_price: '405.00' },
})

function quote(quantity: number): PriceQuote {
  const tier = (quantity >= 30 ? TIERS[2] : quantity >= 10 ? TIERS[1] : TIERS[0]) as PriceTier
  const unit = Number(tier.unit_price)
  const next = quantity < 10 ? TIERS[1] : quantity < 30 ? TIERS[2] : null
  return {
    product_id: 9,
    variant_id: 301,
    sku: 'CEM-53-50',
    options: {},
    quantity,
    mrp: '480.00',
    base_unit_price: '450.00',
    unit_price: tier.unit_price,
    applied_tier: tier.is_base ? null : { min_quantity: tier.min_quantity },
    next_tier: next ? { min_quantity: next.min_quantity, unit_price: next.unit_price, units_more: next.min_quantity - quantity, reachable: true } : null,
    price_tiers: TIERS,
    line_total: (unit * quantity).toFixed(2),
    bulk_saving: ((450 - unit) * quantity).toFixed(2),
    offer_discount: '0.00',
    offers: [],
    total: (unit * quantity).toFixed(2),
    savings_vs_mrp: '0.00',
    stock_status: 'in_stock',
    within_stock: true,
    max_order_quantity: 50,
    note: 'Preview.',
  }
}

function cementRoutes() {
  return {
    '/categories/': [],
    '/products/opc-cement/': cement,
    '/products/opc-cement/reviews/': { count: 0, next: null, previous: null, results: [] },
    '/products/opc-cement/quote/': ({ params }: RequestInfo) => quote(Number(params.quantity)),
    '/products/': productPage([]),
  }
}

describe('bulk prices and options on the product page', () => {
  it('shows the bulk price table and the server’s price for the chosen quantity', async () => {
    const api = mockApi({ get: cementRoutes() })
    const { user } = renderRoute('/p/opc-cement')
    const table = await screen.findByRole('table', { name: 'Bulk prices' })
    const rows = within(table).getAllByRole('row').slice(1)
    const cells = rows.map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent))
    expect(cells).toEqual([
      ['1–9 units', '₹450', '— (your quantity)'],
      ['10–29 units', '₹415', '7.8%'],
      ['30+ units', '₹405', '10%'],
    ])
    expect(rows[0]).toHaveAttribute('aria-current', 'true')
    expect(await screen.findByTestId('price-quote')).toHaveTextContent('Quantity 1 → ₹450/unit')
    expect(screen.getByTestId('price-quote')).toHaveTextContent('1 × ₹450 = ₹450')
    expect(screen.getByTestId('next-tier')).toHaveTextContent('Add 9 more to unlock ₹415/unit')

    const more = screen.getByRole('button', { name: 'Increase quantity' })
    for (let i = 0; i < 9; i += 1) await user.click(more)
    await waitFor(() => expect(screen.getByTestId('price-quote')).toHaveTextContent('Quantity 10 → ₹415/unit'))
    expect(screen.getByTestId('price-quote')).toHaveTextContent('10 × ₹415 = ₹4,150')
    expect(screen.getByTestId('price-quote')).toHaveTextContent('Bulk price applied')
    expect(screen.getByTestId('price-quote')).toHaveTextContent('You save ₹350 with the 10+ price')
    expect(within(table).getAllByRole('row')[2]).toHaveAttribute('aria-current', 'true')
    // The page asked the server; it never multiplied prices itself.
    expect(api.get.mock.calls.some(([url, config]) => url === '/products/opc-cement/quote/' && (config as { params: { quantity: number } }).params.quantity === 10)).toBe(true)
    expect(screen.getAllByRole('link', { name: 'Civil & Interiors' })[0]).toHaveAttribute('href', '/c/civil-interiors')
  })

  it('chooses the variant by its options', async () => {
    mockApi({ get: cementRoutes() })
    const { user, router } = renderRoute('/p/opc-cement')
    const grade = await screen.findByRole('radiogroup', { name: 'Grade' })
    const bag = screen.getByRole('radiogroup', { name: 'Bag size' })
    expect(within(grade).getByRole('radio', { name: '53 Grade' })).toHaveAttribute('aria-checked', 'true')
    await user.click(within(bag).getByRole('radio', { name: '25 kg' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/p/opc-cement?variant=303'))
    expect(screen.getByText('SKU:').parentElement).toHaveTextContent('CEM-53-25')
    // 43 Grade only exists in 50 kg: choosing it moves the bag size to a combination that is sold.
    await user.click(within(screen.getByRole('radiogroup', { name: 'Grade' })).getByRole('radio', { name: '43 Grade' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/p/opc-cement?variant=302'))
    expect(within(screen.getByRole('radiogroup', { name: 'Bag size' })).getByRole('radio', { name: '50 kg' })).toHaveAttribute('aria-checked', 'true')
    // No bulk prices for this variant: no table.
    expect(screen.queryByRole('table', { name: 'Bulk prices' })).not.toBeInTheDocument()
  })

  it('product cards say when bulk prices and offers with conditions exist', async () => {
    const card = productSummary({
      name: 'OPC Cement',
      slug: 'opc-cement',
      bulk_pricing: { from_quantity: 10, lowest_unit_price: '405.00' },
      offer: { id: 3, name: 'Monsoon', badge: '5% off', min_order_value: '0.00', min_quantity: 10, campaign: 'Monsoon', conditions: ['Buy 10 or more of an item'] },
    })
    mockApi({ get: { '/categories/': [], '/products/': productPage([card]), '/products/facets/': { total: 1, categories: [], brands: [], price: { min: null, max: null }, ratings: [], discounts: [], availability: { in_stock: 1, fast_delivery: 0 }, specifications: [] } } })
    renderRoute('/products')
    expect(await screen.findByTestId('bulk-indicator')).toHaveTextContent('Bulk price from ₹405/unit (10+)')
    expect(screen.getByText(/Monsoon · 5% off on 10\+/)).toBeInTheDocument()
  })
})

describe('cart and checkout', () => {
  const bulkLine = cartLine({
    quantity: 12,
    unit_price: '415.00',
    base_unit_price: '450.00',
    line_total: '4980.00',
    line_mrp_total: '5760.00',
    bulk: { applied_min_quantity: 10, saving: '420.00', next_tier: { min_quantity: 30, unit_price: '405.00', units_more: 18, reachable: true } },
    max_order_quantity: 50,
  })

  it('shows the bulk price applied, the next tier and how much more for free delivery', async () => {
    signIn()
    const totals = { ...TOTALS_800, subtotal: '4980.00', grand_total: '5020.00', delivery_fee: '40.00', bulk_savings: '420.00', savings_vs_mrp: '780.00', free_delivery: false, free_delivery_reason: '', amount_to_free_delivery: '20.00', free_delivery_threshold: '5000.00', free_delivery_hint: '' }
    mockApi({ get: { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/addresses/': [], '/cart/': cart({ items: [bulkLine], totals, can_checkout: true }) } })
    renderRoute('/cart')
    expect(await screen.findByText(/Bulk price for 10\+ applied/)).toHaveTextContent('normal ₹450 each')
    expect(screen.getByText('Add 18 more to pay ₹405 each.')).toBeInTheDocument()
    expect(screen.getByText('₹415 each')).toBeInTheDocument()
    expect(screen.getByText('Add ₹20 more for free delivery (orders from ₹5,000).')).toBeInTheDocument()
    expect(screen.getByText('including ₹420 from bulk prices')).toBeInTheDocument()
  })

  it('says when free delivery is unlocked and why', async () => {
    signIn()
    const totals = { ...TOTALS_800, free_delivery: true, free_delivery_reason: 'Demo: Free delivery on cement from ₹2,000', amount_to_free_delivery: '0.00', free_delivery_threshold: null, free_delivery_hint: '' }
    mockApi({ get: { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/addresses/': [], '/cart/': cart({ items: [cartLine()], totals, can_checkout: true }) } })
    renderRoute('/cart')
    expect(await screen.findByText('Free delivery unlocked')).toHaveTextContent('Free delivery unlocked · Demo: Free delivery on cement from ₹2,000')
  })

  it('cash on delivery above the limit is shown as unavailable, with the reason, and never sent', async () => {
    signIn()
    const preview = checkoutPreview({
      payment_methods: [
        { value: 'online', label: 'Pay online', test_mode: false, available: true },
        {
          value: 'cod',
          label: 'Cash on delivery',
          test_mode: false,
          available: false,
          reason_code: 'cod_limit',
          message: 'Cash on Delivery isn’t available for orders above ₹10,000.',
          max_order_value: '10000.00',
        },
      ],
    })
    const api = mockApi({
      get: { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/cart/': preview.cart, '/addresses/': [] },
      post: { '/checkout/preview/': preview },
    })
    renderRoute('/checkout')
    const cod = await screen.findByRole('radio', { name: /Cash on delivery/ })
    expect(cod).toBeDisabled()
    expect(screen.getByText('Cash on Delivery isn’t available for orders above ₹10,000.')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Pay online/ })).toBeChecked()
    expect(api.post.mock.calls.every(([url]) => url === '/checkout/preview/')).toBe(true) // no order sent
  })
})

describe('three-level categories', () => {
  it('a department page lists its categories and a subcategory page shows the whole path', async () => {
    const department = {
      id: 40,
      name: 'Civil & Interiors',
      slug: 'civil-interiors',
      description: '',
      image: null,
      sort_order: 0,
      product_count: 3,
      parent: null,
      parent_detail: null,
      is_active: true,
      level: 1,
      breadcrumb: [{ id: 40, name: 'Civil & Interiors', slug: 'civil-interiors' }],
      children: [
        { id: 41, name: 'Cement', slug: 'cement', description: '', image: null, sort_order: 0, product_count: 2, children: [{ id: 42, name: 'Grey Cement', slug: 'grey-cement', description: '', image: null, sort_order: 0, product_count: 2, children: [] }] },
        { id: 43, name: 'Adhesives', slug: 'adhesives', description: '', image: null, sort_order: 1, product_count: 1, children: [] },
      ],
    }
    const grey = {
      ...department,
      id: 42,
      name: 'Grey Cement',
      slug: 'grey-cement',
      parent: 41,
      parent_detail: { id: 41, name: 'Cement', slug: 'cement' },
      level: 3,
      breadcrumb: [
        { id: 40, name: 'Civil & Interiors', slug: 'civil-interiors' },
        { id: 41, name: 'Cement', slug: 'cement' },
        { id: 42, name: 'Grey Cement', slug: 'grey-cement' },
      ],
      children: [],
    }
    const facets = { total: 0, categories: [], brands: [], price: { min: null, max: null }, ratings: [], discounts: [], availability: { in_stock: 0, fast_delivery: 0 }, specifications: [] }
    mockApi({
      get: {
        '/categories/': [department],
        '/categories/civil-interiors/': department,
        '/categories/grey-cement/': grey,
        '/products/': productPage([]),
        '/products/facets/': facets,
      },
    })
    renderRoute('/c/grey-cement')
    const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' })
    expect(within(crumbs).getByRole('link', { name: 'Civil & Interiors' })).toHaveAttribute('href', '/c/civil-interiors')
    expect(within(crumbs).getByRole('link', { name: 'Cement' })).toHaveAttribute('href', '/c/cement')
    expect(await screen.findByRole('link', { name: 'All Cement' })).toBeInTheDocument()
  })
})
