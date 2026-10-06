import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { BundleRow } from '@/features/admin/types'
import type { KitItem, ProjectKit } from '@/features/projects/types'
import type { BudgetPlan, BundleDetail, Recommendations, SmartCart } from '@/features/shopping/types'
import { adminCategories, page, staffGet } from '@/test/adminFixtures'
import { cart, cartLine, customer, productSummary, wireDetail } from '@/test/fixtures'
import { mockApi, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

/* Phase 22: smart cart, recommendations, budget mode and bundles. The server picks and prices
   every product; these screens show its reasons and never change the cart without a click. */

type Api = ReturnType<typeof mockApi>
const lastBody = (spy: Api['post'] | Api['patch'], url: string) => spy.mock.calls.filter(([called]) => called === url).at(-1)?.[1]

const shopGet = { '/categories/': [], '/wishlist/': [], '/cart/': cart(), '/search/recent/': [] }
const bits = productSummary({ id: 21, name: 'Masonry Drill Bits', slug: 'masonry-bits', default_variant_id: 210 })
const plugs = productSummary({ id: 22, name: 'Wall Plugs 6mm', slug: 'wall-plugs', default_variant_id: 220 })
const hammer = productSummary({ id: 23, name: 'Claw Hammer', slug: 'claw-hammer', default_variant_id: 230 })
const row = (product: typeof bits, reason: string) => ({ product_id: product.id, reason, variant_id: product.default_variant_id, verdict: null, product })

function item(overrides: Partial<KitItem> = {}): KitItem {
  return {
    id: 1,
    material_key: 'bits',
    base_key: 'bits',
    steps: [],
    pack_explanation: '',
    stock_status: 'available',
    label: 'Masonry Drill Bits',
    rationale: '',
    note: '',
    status: 'found',
    need: null,
    pack_amount: 1,
    size_known: true,
    suggested: null,
    alternatives: [],
    added_by_customer: false,
    is_optional: false,
    is_estimate: false,
    included: true,
    customer_set: false,
    quantity: 1,
    unit: 'set',
    product_id: 21,
    product: { ...bits, variant_id: 210, reason: '' },
    variant: { id: 210, sku: 'BIT-6', name: '6 mm', options: [], price: '250.00', mrp: '300.00' },
    problem: '',
    stock_available: null,
    price: { unit_price: '250.00', base_unit_price: '250.00', applied_tier: null, next_tier: null, line_total: '250.00', bulk_saving: '0.00', offer_discount: '0.00' },
    ...overrides,
  } as KitItem
}

function kit(items: KitItem[], overrides: Partial<ProjectKit> = {}): ProjectKit {
  return {
    items,
    postal_code: '',
    totals: {
      item_count: items.length,
      mrp_total: '600.00',
      subtotal: '500.00',
      bulk_savings: '0.00',
      offer_discount: '0.00',
      coupon_discount: '0.00',
      delivery_fee: '0.00',
      tax_included: '76.27',
      grand_total: '500.00',
      savings_vs_mrp: '100.00',
    },
    offers: [],
    offers_in_reach: [],
    coupon: null,
    delivery: { checked: false, available: false, message: '', label: '', delivery_type: null, eta_minutes: null, fee: '0', free_delivery_reason: '', amount_to_free_delivery: '0', free_delivery_hint: '', shipments: [] },
    issues: [],
    can_add_to_cart: true,
    not_found_count: 0,
    included_count: items.filter((i) => i.included).length,
    ...overrides,
  } as ProjectKit
}

describe('smart cart', () => {
  const smart: SmartCart = {
    empty: false,
    summary: null,
    titles: {},
    top_actions: [],
    sections: [
      { key: 'needed_with', title: 'Needed with it', items: [{ type: 'needed', message: 'A drill needs drill bits.', action: 'add', priority: 80, product_id: 21, variant_id: 210, quantity: 1, product: bits }] },
      { key: 'bulk', title: 'Save with bulk pricing', items: [{ type: 'bulk', message: 'Buy 10 and pay ₹22 each.', action: 'set_quantity', priority: 60, cart_item_id: 1, quantity: 10, saving: '30.00' }] },
      { key: 'duplicates', title: 'Cart warnings', items: [{ type: 'duplicate', message: 'You have two hammers.', action: 'remove', priority: 90, cart_item_id: 2 }] },
      { key: 'works_with', title: 'Works with it', items: [{ type: 'works', message: 'Fits your drill.', action: 'add', priority: 20, product_id: 23, variant_id: 230, product: hammer }] },
    ],
  }
  const lines = [cartLine({ id: 1, variant_id: 11 }), cartLine({ id: 2, variant_id: 12 })]

  it('shows the top sections, adds a needed item and updates a quantity for the bulk price', async () => {
    signIn()
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/cart/': cart({ items: lines }), '/shopping/cart/': smart, '/addresses/': [] },
      post: { '/cart/items/': cart({ items: lines }) },
      patch: { '/cart/items/1/': cart({ items: lines }) },
    })
    const { user } = renderRoute('/cart')
    const needed = await screen.findByRole('list', { name: 'Needed with it' })
    expect(needed).toHaveTextContent('A drill needs drill bits.')
    expect(screen.queryByRole('list', { name: 'Works with it' })).not.toBeInTheDocument()
    await user.click(within(needed).getByRole('button', { name: 'Add to cart' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/', { variant_id: 210, quantity: 1 }))
    await user.click(screen.getByRole('button', { name: 'Make it 10' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/cart/items/1/', { quantity: 10 }))
    await user.click(screen.getByRole('button', { name: 'Show 1 more' }))
    expect(screen.getByRole('list', { name: 'Works with it' })).toHaveTextContent('Fits your drill.')
  })

  it('asks before removing a line and does nothing when cancelled', async () => {
    signIn()
    const api = mockApi({ get: { ...shopGet, '/auth/me/': customer, '/cart/': cart({ items: lines }), '/shopping/cart/': smart, '/addresses/': [] } })
    const { user } = renderRoute('/cart')
    await user.click(await screen.findByRole('button', { name: 'Remove' }))
    expect(screen.getByText('Remove this line?')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.delete).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  })

  it('sends the customer’s budget to the smart cart', async () => {
    signIn()
    const api = mockApi({ get: { ...shopGet, '/auth/me/': customer, '/cart/': cart({ items: lines }), '/shopping/cart/': smart, '/addresses/': [] } })
    const { user } = renderRoute('/cart')
    const field = await screen.findByLabelText('My budget (₹)')
    await user.type(field, '2000')
    await user.click(within(field.closest('form')!).getByRole('button', { name: 'Check' }))
    await waitFor(() =>
      expect(api.get.mock.calls.some(([url, config]) => url === '/shopping/cart/' && (config as { params?: { budget?: string } })?.params?.budget === '2000')).toBe(true),
    )
  })
})

describe('recommendations', () => {
  it('shows product-page groups with reasons and kits that use the product', async () => {
    const recs: Recommendations = {
      product_id: 5,
      groups: { needed_with: [row(bits, 'Needed to drill into concrete.')], frequently_bought_together: [row(plugs, 'Bought together in 12 orders.')], works_with: [], better_alternatives: [] },
      titles: { needed_with: 'Needed with this', frequently_bought_together: 'Frequently bought together' },
      bundles: [
        {
          id: 1,
          slug: 'wall-drilling-kit',
          name: 'Wall drilling kit',
          kind: 'drilling',
          kind_label: 'Drilling kit',
          description: 'Everything to hang a shelf.',
          promo_label: 'Popular',
          savings: { vs_mrp: '120.00', bulk: '0', offers: '0' },
          valid: true,
          item_count: 4,
          total: '1499.00',
          subtotal: '1499.00',
          product_ids: [5, 21],
        },
      ],
    }
    mockApi({ get: { ...shopGet, '/products/fr-pvc-copper-wire/': wireDetail(), '/shopping/recommendations/': recs } })
    renderRoute('/p/fr-pvc-copper-wire')
    const needed = await screen.findByRole('list', { name: 'Needed with this' })
    expect(needed).toHaveTextContent('Needed to drill into concrete.')
    expect(within(needed).getByRole('link', { name: /Masonry Drill Bits/ })).toHaveAttribute('href', '/p/masonry-bits')
    expect(screen.getByRole('list', { name: 'Buy together' })).toHaveTextContent('Bought together in 12 orders.')
    expect(screen.queryByRole('list', { name: 'Compatible products' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Wall drilling kit' })).toHaveAttribute('href', '/bundles/wall-drilling-kit')
  })

  it('home shows only general groups when there is no history, and buy again when there is', async () => {
    const general: Recommendations = { personal: false, groups: { best_value: [row(hammer, 'Lowest price per unit in Tools.')], popular_now: [] }, titles: { best_value: 'Best value', popular_now: 'Popular' } }
    mockApi({ get: { ...shopGet, '/shopping/recommendations/': general } })
    const first = renderRoute('/')
    expect(await screen.findByRole('list', { name: 'Best value' })).toHaveTextContent('Lowest price per unit in Tools.')
    expect(screen.queryByText('Buy again')).not.toBeInTheDocument()
    expect(screen.queryByText('Based on your orders')).not.toBeInTheDocument()
    first.unmount()

    signIn()
    const personal: Recommendations = { personal: true, groups: { buy_again: [row(plugs, 'You ordered this before.')] }, titles: { buy_again: 'Buy again' } }
    mockApi({ get: { ...shopGet, '/auth/me/': customer, '/shopping/recommendations/': personal } })
    renderRoute('/')
    expect(await screen.findByRole('list', { name: 'Buy again' })).toHaveTextContent('You ordered this before.')
  })
})

describe('budget mode', () => {
  it('plans a cart within the budget and says what was swapped and left out', async () => {
    const plan: BudgetPlan = {
      text: 'drill a wall',
      language: 'en',
      budget: '600',
      complete: true,
      message: 'This plan costs ₹500, ₹100 under your ₹600 budget.',
      kit: kit([item()]),
      total: '500.00',
      remaining: '100.00',
      within_budget: true,
      swapped: [{ key: 'bits', label: 'Drill bits', from: 'Premium Bits', to: 'Masonry Drill Bits', saving: '150.00', reason: 'Same kind, ₹150 less.' }],
      dropped: [{ key: 'level', label: 'Spirit level', reason: 'Optional; left out to stay within budget.' }],
    }
    const api = mockApi({ get: shopGet, post: { '/shopping/budget/': plan } })
    const { user } = renderRoute('/budget')
    await user.type(await screen.findByLabelText('What do you need?'), 'drill a wall')
    await user.type(screen.getByLabelText('Budget (₹)'), '600')
    await user.click(screen.getByRole('button', { name: 'Plan my cart' }))
    expect(await screen.findByRole('status')).toHaveTextContent('₹100 under your ₹600 budget')
    expect(lastBody(api.post, '/shopping/budget/')).toMatchObject({ text: 'drill a wall', budget: '600' })
    expect(screen.getByRole('list', { name: 'Swapped' })).toHaveTextContent('Premium Bits → Masonry Drill Bits')
    expect(screen.getByRole('list', { name: 'Left out' })).toHaveTextContent('Spirit level')
    expect(screen.getByRole('list', { name: 'Planned items' })).toHaveTextContent('Masonry Drill Bits')
  })
})

describe('bundles', () => {
  const detail = (included = true): BundleDetail => ({
    id: 1,
    slug: 'wall-drilling-kit',
    name: 'Wall drilling kit',
    kind: 'drilling',
    kind_label: 'Drilling kit',
    description: 'Everything to hang a shelf.',
    promo_label: '',
    kit: kit([item(), item({ id: 2, material_key: 'plugs', label: 'Wall Plugs 6mm', product_id: 22, is_optional: true, included })]),
    savings: { vs_mrp: '100.00', bulk: '0', offers: '0' },
    valid: true,
  })

  it('lets the customer untick an item and adds the edited kit', async () => {
    signIn()
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer },
      post: {
        '/shopping/bundles/wall-drilling-kit/price/': ({ body }: RequestInfo) => detail((body as { overrides: Record<string, { included?: boolean }> }).overrides['2']?.included !== false),
        '/shopping/bundles/wall-drilling-kit/add-to-cart/': { added_lines: 1, added_units: 1 },
      },
    })
    const { user } = renderRoute('/bundles/wall-drilling-kit')
    expect(await screen.findByRole('heading', { name: 'Wall drilling kit' })).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Include Wall Plugs 6mm' }))
    await waitFor(() => expect(lastBody(api.post, '/shopping/bundles/wall-drilling-kit/price/')).toMatchObject({ overrides: { '2': { included: false } } }))
    await user.click(await screen.findByRole('button', { name: 'Add 1 item to cart' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/shopping/bundles/wall-drilling-kit/add-to-cart/', { overrides: { '2': { included: false } }, only_missing: false }),
    )
  })

  it('sends a signed-out customer to log in before adding', async () => {
    const api = mockApi({ get: shopGet, post: { '/shopping/bundles/wall-drilling-kit/price/': detail() } })
    const { user, router } = renderRoute('/bundles/wall-drilling-kit')
    await user.click(await screen.findByRole('button', { name: 'Add 2 items to cart' }))
    await waitFor(() => expect(currentUrl(router)).toBe(`/login?next=${encodeURIComponent('/bundles/wall-drilling-kit')}`))
    expect(api.post).not.toHaveBeenCalledWith('/shopping/bundles/wall-drilling-kit/add-to-cart/', expect.anything())
  })
})

describe('admin bundles and recommendation rules', () => {
  const saved: BundleRow = {
    id: 9,
    name: 'Shelf kit',
    slug: 'shelf-kit',
    kind: 'drilling',
    description: '',
    promo_label: '',
    is_active: true,
    starts_at: null,
    ends_at: null,
    priority: 100,
    state: 'live',
    items: [{ id: 1, product: 21, name: 'Masonry Drill Bits', variant: null, variant_name: '', quantity: 2, note: '', is_optional: false, live: true }],
    created_at: '2026-10-06T06:00:00Z',
    updated_at: '2026-10-06T06:00:00Z',
  }

  it('creates a bundle from real products', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/bundles/': [], '/admin/products/': page([{ ...bits, state: 'live' }]) }),
      post: { '/admin/bundles/': saved },
    })
    const { user } = renderRoute('/admin/bundles')
    expect(await screen.findByText('No bundles yet.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add bundle' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.type(dialog.getByLabelText(/^Name/), 'Shelf kit')
    await user.selectOptions(dialog.getByLabelText('Type'), 'drilling')
    await user.type(dialog.getByLabelText('Add a product'), 'masonry')
    await user.click(dialog.getByRole('button', { name: 'Find' }))
    await user.click(await dialog.findByRole('button', { name: 'Add Masonry Drill Bits' }))
    const qty = dialog.getByLabelText('Quantity')
    await user.clear(qty)
    await user.type(qty, '2')
    await user.click(dialog.getByRole('button', { name: /save/i }))
    await waitFor(() =>
      expect(lastBody(api.post, '/admin/bundles/')).toMatchObject({ name: 'Shelf kit', kind: 'drilling', item_rows: [{ product: 21, quantity: 2, note: '', is_optional: false }] }),
    )
  })

  it('will not save a bundle without products', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/admin/bundles/': [saved] }) })
    const { user } = renderRoute('/admin/bundles')
    await user.click(await screen.findByRole('button', { name: 'Add bundle' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.type(dialog.getByLabelText(/^Name/), 'Empty kit')
    await user.click(dialog.getByRole('button', { name: /save/i }))
    expect(await dialog.findByText('Add the products of this bundle.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('adds a complete-the-project rule between two categories', async () => {
    signIn()
    const flat = adminCategories.flatMap((c) => [c, ...c.children])
    const [source, target] = [flat[0]!, flat[1]!]
    const api = mockApi({
      get: staffGet('admin', {
        '/admin/recommendation-rules/': [],
        '/admin/categories/': ({ params }: RequestInfo) => (params.flat ? flat : adminCategories),
      }),
      post: { '/admin/recommendation-rules/': { id: 1, source_category: source.id, source_name: source.name, target_category: target.id, target_name: target.name, label: 'Finish the job', priority: 100, is_active: true } },
    })
    const { user } = renderRoute('/admin/recommendations')
    await user.click(await screen.findByRole('button', { name: 'Add rule' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.selectOptions(await dialog.findByLabelText('When looking at a product in'), String(source.id))
    await user.selectOptions(dialog.getByLabelText('Suggest popular products from'), String(target.id))
    await user.type(dialog.getByLabelText('Reason shown to customers'), 'Finish the job')
    await user.click(dialog.getByRole('button', { name: /save/i }))
    await waitFor(() =>
      expect(lastBody(api.post, '/admin/recommendation-rules/')).toEqual({ source_category: source.id, target_category: target.id, label: 'Finish the job', priority: 100, is_active: true }),
    )
  })
})
