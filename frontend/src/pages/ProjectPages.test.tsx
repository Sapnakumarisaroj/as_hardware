import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { KitItem, ProjectKit, ProjectPlan, ProjectType } from '@/features/projects/types'
import { ApiError } from '@/lib/api/errors'
import { cart, customer, productSummary } from '@/test/fixtures'
import { mockApi } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results })
const shopGet = { '/categories/': [], '/wishlist/': [], '/cart/': cart(), '/search/recent/': [] }

const types: ProjectType[] = [
  { key: 'painting', name: 'Painting', summary: 'Walls are prepared, primed and painted.', first_question: null },
  { key: 'tiling', name: 'Tiling', summary: 'Tiles are fixed with adhesive.', first_question: null },
]

const paint = { ...productSummary({ id: 5, name: 'Interior Emulsion Paint', slug: 'interior-emulsion', price: '999.00' }), variant_id: 50, reason: '' }

function item(overrides: Partial<KitItem> = {}): KitItem {
  return {
    id: 1,
    material_key: 'emulsion',
    label: 'Interior emulsion paint',
    rationale: 'About 486 sq ft of wall, 2 coats.',
    note: '',
    status: 'found',
    need: { amount: 7.48, unit: 'l' },
    pack_amount: 4,
    size_known: true,
    suggested: { variant_id: 50, quantity: 2 },
    alternatives: [],
    added_by_customer: false,
    is_optional: false,
    is_estimate: true,
    included: true,
    customer_set: false,
    quantity: 2,
    unit: 'piece',
    product_id: 5,
    product: paint,
    variant: { id: 50, sku: 'INTEMUL-4', name: '4 L', options: [], price: '999.00', mrp: '1150.00' },
    problem: '',
    stock_available: 40,
    price: {
      unit_price: '999.00',
      base_unit_price: '999.00',
      applied_tier: null,
      next_tier: { min_quantity: 3, unit_price: '969.00', units_more: 1 },
      line_total: '1998.00',
      bulk_saving: '0.00',
      offer_discount: '0.00',
    },
    ...overrides,
  }
}

function kit(overrides: Partial<ProjectKit> = {}): ProjectKit {
  return {
    items: [
      item(),
      item({ id: 2, material_key: 'masking_tape', label: 'Masking tape', status: 'not_found', included: false, product: null, product_id: null, variant: null, price: null, problem: 'not_found', is_estimate: true }),
    ],
    postal_code: '411038',
    totals: {
      item_count: 1,
      mrp_total: '2300.00',
      subtotal: '1998.00',
      bulk_savings: '0.00',
      offer_discount: '0.00',
      delivery_fee: '40.00',
      tax_included: '304.78',
      grand_total: '2038.00',
      savings_vs_mrp: '302.00',
    },
    offers: [],
    offers_in_reach: [],
    delivery: {
      checked: true,
      available: true,
      message: '⚡ Fast delivery · Delivery in 20 minutes',
      label: 'Delivery in 20 minutes',
      delivery_type: 'fast',
      eta_minutes: 20,
      fee: '40.00',
      free_delivery_reason: '',
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

function plan(overrides: Partial<ProjectPlan> = {}): ProjectPlan {
  return {
    id: 7,
    title: 'Painting · 12 × 15 ft room',
    project_type: 'painting',
    type_name: 'Painting',
    status: 'ready',
    description: 'Paint my 12x15 bedroom',
    language: 'en',
    summary: 'Walls are prepared, primed and painted.',
    answers: { length: 12, width: 15, surface: 'interior', condition: 'minor' },
    from_description: ['length', 'width'],
    questions: [
      { key: 'length', kind: 'number', text: 'How long is the room (in feet)?', unit: 'ft', min: 1, max: 200, choices: [], default: null },
      {
        key: 'condition',
        kind: 'choice',
        text: 'What condition are the walls in?',
        unit: '',
        min: 1,
        max: 10000,
        choices: [
          { value: 'good', label: 'Good, just repainting' },
          { value: 'minor', label: 'A few cracks or holes' },
        ],
        default: null,
      },
    ],
    missing: [],
    assumptions: [{ key: 'height', value: 10, text: 'Assumed: Wall height (feet) 10 ft' }],
    complete: true,
    safety: ['Keep the room ventilated.'],
    professional: '',
    not_sold: '',
    estimate_notice: 'Quantities marked “estimate” come from common rules of thumb.',
    created_at: '2026-10-06T10:00:00Z',
    updated_at: '2026-10-06T10:00:00Z',
    kit: kit(),
    ...overrides,
  }
}

const signedInGet = { ...shopGet, '/auth/me/': customer, '/ai/project-types/': { results: types }, '/ai/projects/': page([]) }

describe('Project builder', () => {
  it('starts a project from a description and opens it', async () => {
    signIn()
    const api = mockApi({ get: { ...signedInGet, '/ai/projects/7/': plan() }, post: { '/ai/projects/': plan() } })
    const { user, router } = renderRoute('/projects')
    await user.type(await screen.findByLabelText('What are you working on?'), 'Paint my 12x15 bedroom')
    await user.click(screen.getByRole('button', { name: 'Plan my project' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/projects/7'))
    expect(api.post).toHaveBeenCalledWith('/ai/projects/', { description: 'Paint my 12x15 bedroom' })
    expect(await screen.findByRole('heading', { name: 'Painting · 12 × 15 ft room' })).toBeInTheDocument()
  })

  it('starts from a job type and asks visitors to sign in first', async () => {
    mockApi({ get: { ...shopGet, '/ai/project-types/': { results: types } } })
    const { user, router } = renderRoute('/projects')
    await user.click(await screen.findByRole('button', { name: /Tiling/ }))
    await waitFor(() => expect(currentUrl(router)).toBe('/login?next=%2Fprojects'))
  })

  it('shows why a description could not be planned', async () => {
    signIn()
    const { httpError } = await import('@/test/mockApi')
    mockApi({ get: signedInGet, post: { '/ai/projects/': httpError(400, 'We couldn’t tell what kind of project this is.', 'project_type_unknown') } })
    const { user } = renderRoute('/projects')
    await user.type(await screen.findByLabelText('What are you working on?'), 'hello')
    await user.click(screen.getByRole('button', { name: 'Plan my project' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('couldn’t tell what kind of project')
  })

  it('asks only the missing questions and sends the answers', async () => {
    signIn()
    const draft = plan({ complete: false, status: 'draft', missing: ['condition'], kit: null })
    const api = mockApi({ get: { ...signedInGet, '/ai/projects/7/': draft }, patch: { '/ai/projects/7/': plan() } })
    const { user } = renderRoute('/projects/7')
    const form = within(await screen.findByRole('form', { name: 'A few details for the right amounts' }))
    expect(form.queryByLabelText('How long is the room (in feet)?')).not.toBeInTheDocument()
    await user.click(form.getByText('A few cracks or holes'))
    await user.click(form.getByRole('button', { name: 'Build my kit' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/ai/projects/7/', { answers: { condition: 'minor' } }))
    expect(await screen.findByRole('heading', { name: 'Your kit' })).toBeInTheDocument()
  })

  it('shows the kit with estimates, bulk nudges, missing items, safety and totals', async () => {
    signIn()
    mockApi({ get: { ...signedInGet, '/ai/projects/7/': plan() } })
    renderRoute('/projects/7')
    expect(await screen.findByRole('note')).toHaveTextContent('Keep the room ventilated.')
    expect(screen.getByRole('link', { name: /Interior Emulsion Paint/ })).toHaveAttribute('href', '/p/interior-emulsion')
    expect(screen.getAllByText('Estimate').length).toBeGreaterThan(0)
    expect(screen.getByText(/Need about 7.5 L · 4 L per pack/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add 1 more for ₹969 each' })).toBeInTheDocument()
    expect(screen.getByText('Not found in our catalogue.')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Include Masking tape' })).toBeDisabled()
    const total = within(screen.getByRole('complementary', { name: 'Kit total' }))
    expect(total.getByText('₹2,038')).toBeInTheDocument()
    expect(total.getByText(/Fast delivery/)).toBeInTheDocument()
  })

  it('changes a line through the API', async () => {
    signIn()
    const api = mockApi({
      get: { ...signedInGet, '/ai/projects/7/': plan() },
      patch: { '/ai/projects/7/items/1/': plan({ kit: kit({ items: [item({ quantity: 3, customer_set: true })] }) }) },
    })
    const { user } = renderRoute('/projects/7')
    await user.click(await screen.findByRole('button', { name: 'Add 1 more for ₹969 each' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/ai/projects/7/items/1/', expect.objectContaining({ quantity: 3 })))
    expect(await screen.findByText('Changed by you')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Include Interior emulsion paint' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/ai/projects/7/items/1/', expect.objectContaining({ included: false })))
  })

  it('adds the whole kit to the cart', async () => {
    signIn()
    const api = mockApi({
      get: { ...signedInGet, '/ai/projects/7/': plan() },
      post: { '/ai/projects/7/add-to-cart/': plan({ status: 'ordered', added: { added_lines: 1, added_units: 2 } }) },
    })
    const { user } = renderRoute('/projects/7')
    await user.click(await screen.findByRole('button', { name: 'Add 1 item to cart' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ai/projects/7/add-to-cart/', expect.anything()))
    expect(await screen.findByText('Added 1 item to your cart.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to cart' })).toHaveAttribute('href', '/cart')
  })

  it('lists the lines that stopped the kit being added', async () => {
    signIn()
    const refused = new ApiError({
      message: 'Some items can’t be added. Nothing was added to your cart.',
      code: 'project_not_addable',
      status: 400,
      details: { items: [{ variant_id: 50, code: 'insufficient_stock', message: 'Interior Emulsion Paint: Only 1 unit(s) available.' }] },
    })
    mockApi({ get: { ...signedInGet, '/ai/projects/7/': plan() }, post: { '/ai/projects/7/add-to-cart/': refused } })
    const { user } = renderRoute('/projects/7')
    await user.click(await screen.findByRole('button', { name: 'Add 1 item to cart' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Only 1 unit(s) available')
  })

  it('cannot add a kit with problems', async () => {
    signIn()
    const blocked = kit({ can_add_to_cart: false, issues: [{ item_id: null, code: 'not_deliverable', message: 'We don’t deliver to PIN 110001 yet.' }] })
    mockApi({ get: { ...signedInGet, '/ai/projects/7/': plan({ kit: blocked }) } })
    renderRoute('/projects/7')
    expect(await screen.findByRole('button', { name: 'Add 1 item to cart' })).toBeDisabled()
    expect(within(screen.getByRole('list', { name: 'Problems' })).getByText(/110001/)).toBeInTheDocument()
  })

  it('asks visitors to sign in to see a project', async () => {
    mockApi({ get: shopGet })
    renderRoute('/projects/7')
    expect(await screen.findByText('Sign in to see your project.')).toBeInTheDocument()
  })
})
