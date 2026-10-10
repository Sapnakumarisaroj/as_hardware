import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { CollectionRow, FreeDeliveryRuleRow, OptionTypeRow, PaymentSettings } from '@/features/admin/types'
import { adminCategories, adminProduct, page, staffGet, zone } from '@/test/adminFixtures'
import { mockApi, type RequestInfo } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

/* Phase 15 dashboard screens: product options, bulk prices in the product form, curated lists,
   free-delivery rules and cash-on-delivery settings. The screens store rules; the server prices. */

type Api = ReturnType<typeof mockApi>
const lastBody = (spy: Api['post'] | Api['patch'], url: string) => spy.mock.calls.filter(([called]) => called === url).at(-1)?.[1]

const grade: OptionTypeRow = {
  id: 5,
  name: 'Grade',
  slug: 'grade',
  unit: '',
  sort_order: 0,
  is_active: true,
  categories: [10],
  category_details: [{ id: 10, name: 'Tools' }],
  values: [{ id: 51, value: '53 Grade', slug: '53-grade', used_by: 2 }],
  variant_count: 2,
}

const catalogGet = (extra: Record<string, unknown> = {}) => ({
  '/admin/categories/': ({ params }: RequestInfo) =>
    params.flat ? adminCategories.flatMap((c) => [c, ...c.children]) : adminCategories,
  '/admin/brands/': page([{ id: 1, name: 'DrillCo', slug: 'drillco', is_active: true, product_count: 3 }]),
  '/admin/option-types/': [grade],
  ...extra,
})

describe('product options', () => {
  it('lists options and adds one with values and categories', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', catalogGet()), post: { '/admin/option-types/': grade } })
    const { user } = renderRoute('/admin/options')
    const table = await screen.findByRole('table', { name: 'Product options' })
    expect(within(table).getByText('53 Grade')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add option' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Add option' }))
    await user.type(dialog.getByLabelText(/^Name/), 'Bag size')
    await user.type(dialog.getByLabelText(/^Unit/), 'kg')
    await user.type(dialog.getByLabelText('Value 1'), '50 kg')
    await user.click(dialog.getByRole('button', { name: 'Add value' }))
    await user.type(dialog.getByLabelText('Value 2'), '25 kg')
    await user.selectOptions(dialog.getByLabelText(/^Used for/), 'Tools')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(lastBody(api.post, '/admin/option-types/')).toEqual({
        name: 'Bag size',
        unit: 'kg',
        sort_order: 0,
        is_active: true,
        categories: [10],
        value_list: [{ value: '50 kg' }, { value: '25 kg' }],
      }),
    )
  })

  it('a value used by variants can’t be removed from the form', async () => {
    signIn()
    mockApi({ get: staffGet('admin', catalogGet()) })
    const { user } = renderRoute('/admin/options')
    await user.click(await screen.findByRole('button', { name: 'Edit Grade' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Edit option' }))
    expect(dialog.getByRole('button', { name: 'Remove value 1' })).toBeDisabled()
    expect(dialog.getByText('Used by 2 variant(s); renaming changes them too.')).toBeInTheDocument()
  })
})

describe('bulk prices and options in the product form', () => {
  it('sends tiers and options with the variant', async () => {
    signIn()
    const product = adminProduct({ id: 77, name: 'OPC Cement' })
    const api = mockApi({
      get: staffGet('admin', catalogGet({ '/admin/products/77/': product })),
      patch: { '/admin/products/77/': product },
    })
    const { user } = renderRoute('/admin/products/77')
    const first = within(await screen.findByRole('group', { name: /Variant 1/ }))
    await user.type(await first.findByLabelText('Grade'), '53 Grade')
    await user.click(first.getByRole('button', { name: 'Add bulk price to variant 1' }))
    await user.type(first.getByLabelText('From units'), '10')
    await user.type(first.getByLabelText('Price per unit (₹)'), '1')
    await user.click(screen.getByRole('button', { name: /^Save/ }))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    const body = lastBody(api.patch, '/admin/products/77/') as { variants: { price_tiers: unknown; options: unknown }[] }
    expect(body.variants[0]?.price_tiers).toEqual([{ min_quantity: '10', unit_price: '1' }])
    expect(body.variants[0]?.options).toEqual([{ option_type: 5, value: '53 Grade' }])
  })

  it('edits the purchase cost per variant only when the server sent it (administrators)', async () => {
    signIn()
    const base = adminProduct({ id: 77, name: 'OPC Cement' })
    const product = { ...base, variants: base.variants.map((v) => ({ ...v, cost_price: '610.00' })) }
    const api = mockApi({
      get: staffGet('admin', catalogGet({ '/admin/products/77/': product })),
      patch: { '/admin/products/77/': product },
    })
    const { user } = renderRoute('/admin/products/77')
    const first = within(await screen.findByRole('group', { name: /Variant 1/ }))
    const cost = first.getByLabelText('Purchase cost (₹)')
    expect(cost).toHaveValue('610.00')
    await user.clear(cost)
    await user.type(cost, 'abc')
    await user.click(screen.getByRole('button', { name: /^Save/ }))
    expect(await screen.findByText(/the purchase cost must be a number, 0 or more/)).toBeInTheDocument()
    expect(api.patch).not.toHaveBeenCalled()
    await user.clear(cost)
    await user.type(cost, '700')
    await user.click(screen.getByRole('button', { name: /^Save/ }))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect((lastBody(api.patch, '/admin/products/77/') as { variants: { cost_price?: unknown }[] }).variants[0]?.cost_price).toBe('700')
    await user.clear(cost)
    await user.click(screen.getByRole('button', { name: /^Save/ }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(2))
    expect((lastBody(api.patch, '/admin/products/77/') as { variants: { cost_price?: unknown }[] }).variants[0]?.cost_price).toBeNull()
  })

  it('leaves the purchase cost out when the server did not send it', async () => {
    signIn()
    const product = adminProduct({ id: 77, name: 'OPC Cement' })
    const api = mockApi({
      get: staffGet('admin', catalogGet({ '/admin/products/77/': product })),
      patch: { '/admin/products/77/': product },
    })
    const { user } = renderRoute('/admin/products/77')
    const first = within(await screen.findByRole('group', { name: /Variant 1/ }))
    expect(first.queryByLabelText('Purchase cost (₹)')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Save/ }))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect((lastBody(api.patch, '/admin/products/77/') as { variants: object[] }).variants[0]).not.toHaveProperty('cost_price')
  })

  it('saves product-page content and accessories chosen from the shop’s products (Phase 16)', async () => {
    signIn()
    const product = adminProduct({ id: 77, name: 'Impact Drill', accessories: [{ id: 80, name: 'Wall Plugs', slug: 'plugs', note: 'For walls' }] })
    const api = mockApi({
      get: staffGet('admin', catalogGet({
        '/admin/products/77/': product,
        '/admin/products/': ({ params }: RequestInfo) =>
          page(params.q ? [adminProduct({ id: 81, name: 'Masonry Bits', sku: 'BITS-5' }), adminProduct({ id: 77, name: 'Impact Drill' })] : []),
      })),
      patch: { '/admin/products/77/': product },
    })
    const { user } = renderRoute('/admin/products/77')
    await user.type(await screen.findByLabelText('Quick answer'), 'Drills brick')
    await user.type(screen.getByLabelText('Recommended uses (one per line)'), 'Walls')
    await user.click(screen.getByRole('button', { name: 'Add a question' }))
    await user.type(screen.getByLabelText('Question 1'), 'Concrete?')
    await user.type(screen.getByLabelText('Answer 1'), 'Yes')
    expect(screen.getByRole('list', { name: 'Chosen accessories' })).toHaveTextContent('Wall Plugs')
    await user.type(screen.getByLabelText('Find a product to add'), 'bit')
    // The product itself is never offered as its own accessory.
    expect(await screen.findByRole('button', { name: /Add Masonry Bits/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Add Impact Drill/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Add Masonry Bits/ }))
    await user.selectOptions(screen.getByLabelText('Link type for Masonry Bits'), 'incompatible')
    await user.click(screen.getByRole('button', { name: /^Save/ }))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    const body = lastBody(api.patch, '/admin/products/77/') as Record<string, unknown>
    expect(body.quick_answer).toBe('Drills brick')
    expect(body.uses).toBe('Walls')
    expect(body.faqs).toEqual([{ question: 'Concrete?', answer: 'Yes' }])
    expect(body.accessories).toEqual([
      { product: 80, note: 'For walls', kind: 'accessory' },
      { product: 81, note: '', kind: 'incompatible' },
    ])
  })

  it('points out a tier that costs more than the price for fewer units', async () => {
    signIn()
    const product = adminProduct({ id: 77, name: 'OPC Cement' })
    const api = mockApi({ get: staffGet('admin', catalogGet({ '/admin/products/77/': product })), patch: {} })
    const { user } = renderRoute('/admin/products/77')
    const first = within(await screen.findByRole('group', { name: /Variant 1/ }))
    const price = product.variants[0]?.price ?? '0'
    await user.click(first.getByRole('button', { name: 'Add bulk price to variant 1' }))
    await user.type(first.getByLabelText('From units'), '10')
    await user.type(first.getByLabelText('Price per unit (₹)'), String(Number(price) + 1))
    await user.click(screen.getByRole('button', { name: /^Save/ }))
    expect(await screen.findByText(/the 10\+ price (is above the MRP|must be lower than the price for fewer units)/)).toBeInTheDocument()
    expect(api.patch).not.toHaveBeenCalled()
  })
})

describe('curated lists', () => {
  const deals: CollectionRow = {
    id: 3,
    name: 'Deals of the week',
    slug: 'deals-of-the-week',
    description: '',
    rule: 'manual',
    window_days: 30,
    max_items: 12,
    categories: [],
    category_details: [],
    starts_at: null,
    ends_at: '2026-10-12T10:00:00Z',
    is_active: true,
    sort_order: 0,
    items: [{ product_id: 1, name: 'Impact Drill 650W', sku: 'DEMO-DRILL', live: true }],
    state: 'live',
  }

  it('creates an automatic best-seller list and previews a list', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        ...catalogGet(),
        '/admin/collections/': [deals],
        '/admin/collections/3/preview/': { is_live: true, count: 1, products: [{ id: 1, name: 'Impact Drill 650W', sku: 'DEMO-DRILL', price: '3200.00' }] },
      }),
      post: { '/admin/collections/': deals },
    })
    const { user } = renderRoute('/admin/collections')
    const table = await screen.findByRole('table', { name: 'Curated lists' })
    expect(within(table).getByText('1 chosen product(s)')).toBeInTheDocument()
    await user.click(within(table).getByRole('button', { name: 'Preview Deals of the week' }))
    expect(await screen.findByText('1 product(s) shown.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Done' }))

    await user.click(screen.getByRole('button', { name: 'Add list' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Add list' }))
    await user.type(dialog.getByLabelText(/^Name/), 'Best sellers')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('Choose the products for this list.')
    expect(api.post).not.toHaveBeenCalled()
    await user.selectOptions(dialog.getByLabelText('Products from'), 'Best sellers')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(lastBody(api.post, '/admin/collections/')).toMatchObject({ name: 'Best sellers', rule: 'best_sellers', window_days: 30, product_ids: [] }),
    )
  })

  it('store managers can’t open curated lists', async () => {
    signIn()
    mockApi({ get: staffGet('manager') })
    renderRoute('/admin/collections')
    expect(await screen.findByText('For administrators only')).toBeInTheDocument()
  })
})

describe('free-delivery rules', () => {
  const rule: FreeDeliveryRuleRow = {
    id: 8,
    name: 'Cement from ₹2,000',
    description: '',
    threshold: '2000.00',
    zones: [],
    products: [],
    categories: [10],
    zone_details: [],
    product_details: [],
    category_details: [{ id: 10, name: 'Tools' }],
    starts_at: '2026-10-01T00:00:00Z',
    ends_at: null,
    is_active: true,
    state: 'live',
    summary: 'Free delivery from ₹2,000 of Tools everywhere we deliver',
  }

  it('lists rules in words and creates one for a zone', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { ...catalogGet(), '/admin/free-delivery-rules/': [rule], '/admin/zones/': [zone()] }),
      post: { '/admin/free-delivery-rules/': rule },
    })
    const { user } = renderRoute('/admin/free-delivery')
    expect(await screen.findByText('Free delivery from ₹2,000 of Tools everywhere we deliver')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add rule' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Add free-delivery rule' }))
    await user.type(dialog.getByLabelText(/^Name/), 'Big orders ship free')
    await user.type(dialog.getByLabelText(/^Free from/), '5000')
    await user.click(dialog.getByLabelText(new RegExp(zone().name)))
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(lastBody(api.post, '/admin/free-delivery-rules/')).toMatchObject({
        name: 'Big orders ship free',
        threshold: '5000',
        zones: [zone().id],
        categories: [],
        products: [],
        is_active: true,
      }),
    )
  })
})

describe('cash on delivery', () => {
  const settings: PaymentSettings = {
    cod_enabled: true,
    cod_max_order_value: '10000.00',
    updated_at: '2026-10-05T10:00:00Z',
    updated_by_name: null,
    stores_without_cod: [{ id: 2, name: 'Hadapsar Store' }],
    zones_without_cod: [],
  }

  it('an administrator changes the limit', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/payment-settings/': settings }),
      patch: { '/admin/payment-settings/': { ...settings, cod_max_order_value: '15000.00' } },
    })
    const { user } = renderRoute('/admin/payment-settings')
    const limit = await screen.findByLabelText('Largest order payable in cash (₹)')
    expect(limit).toHaveValue('10000.00')
    expect(screen.getByText('Store: Hadapsar Store')).toBeInTheDocument()
    await user.clear(limit)
    await user.type(limit, '0')
    expect(screen.getByText('Enter an amount of at least ₹1, or tick “No limit”.')).toBeInTheDocument()
    await user.clear(limit)
    await user.type(limit, '15000')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(lastBody(api.patch, '/admin/payment-settings/')).toEqual({ cod_enabled: true, cod_max_order_value: '15000' }),
    )
  })

  it('a store manager sees the rules but can’t change them', async () => {
    signIn()
    mockApi({ get: staffGet('manager', { '/admin/payment-settings/': settings }) })
    renderRoute('/admin/payment-settings')
    expect(await screen.findByLabelText('Largest order payable in cash (₹)')).toBeDisabled()
    expect(screen.getByText('Only administrators can change these rules.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
  })
})
