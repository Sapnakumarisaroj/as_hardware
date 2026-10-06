import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { KitItem, ProjectKit } from '@/features/projects/types'
import type { QuantityResult, QuantityStatus } from '@/features/quantity/types'
import { ApiError } from '@/lib/api/errors'
import { cart, customer, productSummary } from '@/test/fixtures'
import { mockApi, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const shopGet = { '/categories/': [], '/wishlist/': [], '/cart/': cart(), '/search/recent/': [] }
const calculators = [
  { key: 'plastering', name: 'Plastering', summary: 'Cement plaster.', examples: [], risky: true },
  { key: 'painting', name: 'Painting', summary: 'Walls primed and painted.', examples: [], risky: false },
]
const status: QuantityStatus = { calculators, ai: { available: false }, pack_rule: 'lowest_cost', label: 'Estimated quantity' }

const cementCard = { ...productSummary({ id: 3, name: 'PPC Cement', slug: 'ppc-cement', price: '450.00' }), variant_id: 30, reason: '' }
const otherCement = { ...productSummary({ id: 4, name: 'OPC 53 Cement', slug: 'opc-cement', price: '470.00', default_variant_id: 40 }), variant_id: 40, reason: '' }

function cementItem(overrides: Partial<KitItem> = {}): KitItem {
  return {
    id: 'cement',
    material_key: 'cement',
    base_key: 'cement',
    steps: [],
    pack_explanation: '4 × 50 kg bag = ₹1,800 covers 3.7 pcs (cheapest way).',
    stock_status: 'available',
    label: 'Cement (50 kg bags)',
    rationale: 'PPC cement suits plastering.',
    note: '',
    status: 'found',
    need: { amount: 3.74, unit: 'pcs' },
    pack_amount: 1,
    size_known: true,
    suggested: { variant_id: 30, quantity: 4 },
    alternatives: [otherCement],
    added_by_customer: false,
    is_optional: false,
    is_estimate: true,
    included: true,
    customer_set: false,
    quantity: 4,
    unit: 'bag',
    product_id: 3,
    product: cementCard,
    variant: { id: 30, sku: 'PPC-50', name: '50 kg bag', options: [], price: '450.00', mrp: '500.00' },
    problem: '',
    stock_available: null,
    price: {
      unit_price: '450.00',
      base_unit_price: '450.00',
      applied_tier: null,
      next_tier: { min_quantity: 10, unit_price: '415.00', units_more: 6, reachable: true },
      line_total: '1800.00',
      bulk_saving: '0.00',
      offer_discount: '0.00',
    },
    ...overrides,
  }
}

function kit(overrides: Partial<ProjectKit> = {}): ProjectKit {
  return {
    items: [cementItem()],
    postal_code: '411001',
    totals: {
      item_count: 1,
      mrp_total: '2000.00',
      subtotal: '1800.00',
      bulk_savings: '0.00',
      offer_discount: '0.00',
      coupon_discount: '0.00',
      delivery_fee: '0.00',
      tax_included: '274.58',
      grand_total: '1800.00',
      savings_vs_mrp: '200.00',
    },
    offers: [],
    offers_in_reach: [],
    coupon: null,
    delivery: {
      checked: true,
      available: true,
      message: '⚡ Fast delivery · Delivery in 42 minutes',
      label: 'Delivery in 42 minutes',
      delivery_type: 'fast',
      eta_minutes: 42,
      fee: '0.00',
      free_delivery_reason: 'Orders from ₹499',
      amount_to_free_delivery: '0.00',
      free_delivery_hint: '',
      shipments: [],
    },
    issues: [],
    can_add_to_cart: true,
    not_found_count: 1,
    included_count: 1,
    ...overrides,
  }
}

function result(overrides: Partial<QuantityResult> = {}): QuantityResult {
  return {
    text: 'I need materials for 500 sq ft plastering',
    language: 'en',
    label: 'Estimated quantity',
    understood_by: 'rules',
    ai: { available: false, used: false, notice: '' },
    calculators,
    calculator: 'plastering',
    name: 'Plastering',
    summary: 'Cement plaster.',
    title: 'Plastering · 500 sq ft',
    answers: { area: 500 },
    from_description: ['area'],
    from_ai: [],
    interpretations: [],
    questions: [
      { key: 'area', kind: 'number', text: 'How big is the area to plaster (sq ft)?', unit: 'sq ft', min: 1, max: 50000, choices: [], default: null, units: ['sq ft', 'sq m'] },
      { key: 'thickness_mm', kind: 'number', text: 'Plaster thickness (mm)', unit: 'mm', min: 6, max: 40, choices: [], default: 12, units: ['mm', 'cm', 'm', 'ft', 'inch'] },
    ],
    missing: [],
    assumptions: [{ key: 'thickness_mm', value: 12, text: 'Assumed: Plaster thickness (mm) 12 mm' }],
    complete: true,
    safety: [],
    professional: '',
    verify: 'Verify measurements with a qualified professional before purchasing.',
    not_sold: 'Sand may not be sold here.',
    estimate_notice: '',
    materials: [
      {
        key: 'cement',
        label: 'Cement (50 kg bags)',
        need: { amount: 3.74, unit: 'pcs', unit_label: 'pcs' },
        is_estimate: true,
        is_optional: false,
        steps: [
          { label: 'Area', value: '500 sq ft = 46.5 sq m' },
          { label: 'Cement', value: '1:5 → 0.124 m³ ÷ 0.0347 m³ per bag = 3.7 bags' },
        ],
        recommended: '4 × 50 kg bag',
        covers: 4,
        extra: 0.26,
        found: true,
        explanation: '4 × 50 kg bag = ₹1,800 covers 3.7 pcs (cheapest way).',
        item_keys: ['cement'],
      },
      {
        key: 'sand',
        label: 'Plastering sand',
        need: { amount: 22.9, unit: 'cft', unit_label: 'cft' },
        is_estimate: true,
        is_optional: false,
        steps: [],
        recommended: '',
        covers: null,
        extra: null,
        found: false,
        explanation: '',
        item_keys: ['sand'],
      },
    ],
    kit: kit(),
    ...overrides,
  }
}

const bodyOf = (spy: ReturnType<typeof mockApi>['post'], url: string) =>
  spy.mock.calls.filter(([called]) => called === url).map(([, body]) => body as Record<string, unknown>)

describe('Quantity calculator', () => {
  it('turns a requirement into estimated materials, real products, prices and delivery', async () => {
    const api = mockApi({ get: { ...shopGet, '/ai/quantity/': status }, post: { '/ai/quantity/': result() } })
    const { user } = renderRoute('/quantity')
    await user.type(await screen.findByLabelText('What do you need?'), 'I need materials for 500 sq ft plastering')
    await user.click(screen.getByRole('button', { name: 'Calculate' }))
    expect(await screen.findByRole('heading', { name: 'Plastering · 500 sq ft' })).toBeInTheDocument()
    expect(bodyOf(api.post, '/ai/quantity/')[0]).toMatchObject({ text: 'I need materials for 500 sq ft plastering' })
    expect(screen.getByRole('note')).toHaveTextContent('Verify measurements with a qualified professional before purchasing.')
    expect(screen.getAllByText('Estimated quantity').length).toBe(2)
    expect(screen.getByText(/Recommended: 4 × 50 kg bag/)).toHaveTextContent('0.26 pcs extra from rounding up')
    expect(screen.getByText('Not found in our catalogue.')).toBeInTheDocument()
    expect(screen.getByText('1:5 → 0.124 m³ ÷ 0.0347 m³ per bag = 3.7 bags')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /PPC Cement/ })).toHaveAttribute('href', '/p/ppc-cement')
    expect(screen.getByText('In stock')).toBeInTheDocument()
    const total = within(screen.getByRole('complementary', { name: 'Estimated total' }))
    expect(total.getByText('Delivery in 42 minutes', { exact: false })).toBeInTheDocument()
    expect(total.getByText('Estimated total').nextSibling).toHaveTextContent('₹1,800')
  })

  it('runs the requirement from the link it was opened with', async () => {
    const api = mockApi({ get: { ...shopGet, '/ai/quantity/': status }, post: { '/ai/quantity/': result() } })
    renderRoute('/quantity?q=500%20sq%20ft%20plastering')
    expect(await screen.findByRole('heading', { name: 'Plastering · 500 sq ft' })).toBeInTheDocument()
    expect(bodyOf(api.post, '/ai/quantity/')[0]).toMatchObject({ text: '500 sq ft plastering' })
  })

  it('asks only the missing questions and sends answers with their units', async () => {
    const asking = result({
      complete: false,
      missing: ['area'],
      kit: null,
      materials: [],
      title: '',
      answers: {},
    })
    const api = mockApi({ get: { ...shopGet, '/ai/quantity/': status }, post: { '/ai/quantity/': (r: RequestInfo) => ((r.body as { answers?: object }).answers && Object.keys((r.body as { answers: object }).answers).length ? result() : asking) } })
    const { user } = renderRoute('/quantity?q=plastering')
    const form = within(await screen.findByRole('form', { name: 'A few details for the right amounts' }))
    expect(form.queryByLabelText('Plaster thickness (mm)')).not.toBeInTheDocument()
    expect(form.getByText('Assumed: Plaster thickness (mm) 12 mm')).toBeInTheDocument()
    await user.type(form.getByLabelText('How big is the area to plaster (sq ft)?'), '46.5')
    await user.selectOptions(form.getByLabelText('Unit for How big is the area to plaster (sq ft)?'), 'sq m')
    await user.click(form.getByRole('button', { name: 'Calculate' }))
    await waitFor(() => expect(bodyOf(api.post, '/ai/quantity/').at(-1)).toMatchObject({ answers: { area: { value: 46.5, unit: 'sq m' } } }))
    expect(await screen.findByRole('heading', { name: 'Plastering · 500 sq ft' })).toBeInTheDocument()
  })

  it('changes the product and the quantity through the server', async () => {
    const api = mockApi({ get: { ...shopGet, '/ai/quantity/': status }, post: { '/ai/quantity/': result() } })
    const { user } = renderRoute('/quantity?q=500%20sq%20ft%20plastering')
    await user.click(await screen.findByRole('button', { name: 'Add 6 more to unlock ₹415/unit' }))
    await waitFor(() => expect(bodyOf(api.post, '/ai/quantity/').at(-1)).toMatchObject({ overrides: { cement: { quantity: 10 } } }))
    await user.click(screen.getByText('Change product'))
    await user.click(screen.getByRole('button', { name: 'Use this' }))
    await waitFor(() =>
      expect(bodyOf(api.post, '/ai/quantity/').at(-1)).toMatchObject({ overrides: { cement: { quantity: 10, variant_id: 40 } } }),
    )
    await user.click(screen.getByRole('checkbox', { name: 'Include PPC Cement' }))
    await waitFor(() => expect(bodyOf(api.post, '/ai/quantity/').at(-1)).toMatchObject({ overrides: { cement: { included: false } } }))
  })

  it('adds all lines to the cart and saves the calculation as a project', async () => {
    signIn()
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/quantity/': status, '/ai/projects/9/': { id: 9 } },
      post: {
        '/ai/quantity/': result(),
        '/ai/quantity/add-to-cart/': { added_lines: 1, added_units: 4 },
        '/ai/quantity/save/': { project_id: 9, path: '/projects/9' },
      },
    })
    const { user, router } = renderRoute('/quantity?q=500%20sq%20ft%20plastering')
    await user.click(await screen.findByRole('button', { name: 'Add all 1 item to cart' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ai/quantity/add-to-cart/', { lines: [{ variant_id: 30, quantity: 4 }] }))
    expect(await screen.findByText('Added 1 item to your cart.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save as a project' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/projects/9'))
    expect(bodyOf(api.post, '/ai/quantity/save/')[0]).toMatchObject({ text: '500 sq ft plastering' })
  })

  it('sends visitors to sign in before adding to the cart', async () => {
    mockApi({ get: { ...shopGet, '/ai/quantity/': status }, post: { '/ai/quantity/': result() } })
    const { user, router } = renderRoute('/quantity?q=500%20sq%20ft%20plastering')
    await user.click(await screen.findByRole('button', { name: 'Add all 1 item to cart' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/login?next=%2Fquantity'))
  })

  it('lists the lines that stopped the cart and blocks a kit with problems', async () => {
    signIn()
    const refused = new ApiError({
      message: 'Some items can’t be added. Nothing was added to your cart.',
      code: 'project_not_addable',
      status: 400,
      details: { items: [{ variant_id: 30, code: 'insufficient_stock', message: 'PPC Cement: Only 2 unit(s) available.' }] },
    })
    mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/quantity/': status },
      post: { '/ai/quantity/': result(), '/ai/quantity/add-to-cart/': refused },
    })
    const { user } = renderRoute('/quantity?q=500%20sq%20ft%20plastering')
    await user.click(await screen.findByRole('button', { name: 'Add all 1 item to cart' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Only 2 unit(s) available')
  })

  it('shows a delivery problem and keeps add-to-cart off', async () => {
    const blocked = kit({ can_add_to_cart: false, issues: [{ item_id: null, code: 'not_deliverable', message: 'We don’t deliver to PIN 110001 yet.' }] })
    mockApi({ get: { ...shopGet, '/ai/quantity/': status }, post: { '/ai/quantity/': result({ kit: blocked }) } })
    renderRoute('/quantity?q=500%20sq%20ft%20plastering')
    expect(await screen.findByRole('button', { name: 'Add all 1 item to cart' })).toBeDisabled()
    expect(within(screen.getByRole('list', { name: 'Problems' })).getByText(/110001/)).toBeInTheDocument()
  })

  it('explains an unknown requirement and offers the calculators', async () => {
    const unknown = result({ calculator: null, complete: false, message: 'I couldn’t tell what to calculate.', kit: null, materials: [], ai: { available: false, used: false, notice: 'The AI helper isn’t available right now.' } })
    const api = mockApi({ get: { ...shopGet, '/ai/quantity/': status }, post: { '/ai/quantity/': (r: RequestInfo) => ((r.body as { calculator?: string }).calculator ? result() : unknown) } })
    const { user } = renderRoute('/quantity?q=hello')
    expect(await screen.findByText('I couldn’t tell what to calculate.')).toBeInTheDocument()
    expect(screen.getByText('The AI helper isn’t available right now.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Plastering' }))
    await waitFor(() => expect(bodyOf(api.post, '/ai/quantity/').at(-1)).toMatchObject({ calculator: 'plastering' }))
  })

  it('shows a refused answer next to its field and keeps the result', async () => {
    const refused = new ApiError({ message: 'Some answers aren’t valid.', code: 'invalid_answers', status: 400, details: { area: 'Enter a number from 1 to 50000 sq ft.' } })
    let calls = 0
    mockApi({ get: { ...shopGet, '/ai/quantity/': status }, post: { '/ai/quantity/': () => (++calls === 1 ? result() : refused) } })
    const { user } = renderRoute('/quantity?q=500%20sq%20ft%20plastering')
    await user.click(await screen.findByRole('button', { name: 'Edit measurements' }))
    const area = screen.getByLabelText('How big is the area to plaster (sq ft)?')
    await user.clear(area)
    await user.type(area, '0')
    await user.click(screen.getByRole('button', { name: 'Recalculate' }))
    expect(await screen.findByText('Enter a number from 1 to 50000 sq ft.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Plastering · 500 sq ft' })).toBeInTheDocument()
  })

  it('shows progress while working it out, and a server error', async () => {
    let release: (value: unknown) => void = () => {}
    const { httpError } = await import('@/test/mockApi')
    mockApi({
      get: { ...shopGet, '/ai/quantity/': status },
      post: { '/ai/quantity/': () => new Promise((resolve) => (release = resolve)) },
    })
    renderRoute('/quantity?q=500%20sq%20ft%20plastering')
    expect(await screen.findByText('Working it out…')).toBeInTheDocument()
    release(httpError(429, 'Too many requests. Wait a minute.'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests. Wait a minute.')
  })
})
