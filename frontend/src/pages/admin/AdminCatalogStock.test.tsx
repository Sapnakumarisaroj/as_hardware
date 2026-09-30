import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  adminCategories,
  adminProduct,
  inventoryRow,
  page,
  productRow,
  staffGet,
  storeDetail,
  storeRow,
  zone,
} from '@/test/adminFixtures'
import { httpError, mockApi, paramsSent, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

type Api = ReturnType<typeof mockApi>
const lastBody = (spy: Api['post'] | Api['patch'], url: string) => spy.mock.calls.filter(([called]) => called === url).at(-1)?.[1]

const flatCategories = adminCategories.flatMap((category) => [category, ...category.children])

const catalogGet = (extra: Record<string, unknown> = {}) => ({
  '/admin/categories/': ({ params }: RequestInfo) => (params.flat ? flatCategories : adminCategories),
  '/admin/brands/': page([{ id: 1, name: 'DrillCo', slug: 'drillco', is_active: true, product_count: 3 }]),
  ...extra,
})

describe('products', () => {
  it('lists products with price, stock and status', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', {
        ...catalogGet(),
        '/admin/products/': page([
          productRow(),
          productRow({ id: 2, name: 'Wall Primer', sku: 'PRIMER', state: 'draft', is_published: false, stock_available: 0, is_returnable: false, price_to: '3900.00' }),
        ]),
      }),
    })
    renderRoute('/admin/products')
    const table = await screen.findByRole('table', { name: 'Products' })
    const drill = within(within(table).getByRole('row', { name: /Impact Drill 650W/ }))
    expect(drill.getByRole('link', { name: 'Impact Drill 650W' })).toHaveAttribute('href', '/admin/products/1')
    expect(drill.getByText('₹3,200')).toBeInTheDocument()
    expect(drill.getByText('Tools › Drills')).toBeInTheDocument()
    expect(drill.getByText('On sale')).toBeInTheDocument()
    expect(drill.getByRole('button', { name: 'Unpublish Impact Drill 650W' })).toBeInTheDocument()

    const primer = within(within(table).getByRole('row', { name: /Wall Primer/ }))
    expect(primer.getByText('₹3,200 – ₹3,900')).toBeInTheDocument()
    expect(primer.getByText('Out of stock')).toBeInTheDocument()
    expect(primer.getByText('Not published')).toBeInTheDocument()
    expect(primer.getByText('No returns')).toBeInTheDocument()
    expect(primer.getByRole('button', { name: 'Publish Wall Primer' })).toBeInTheDocument()
  })

  it('filters on the server', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { ...catalogGet(), '/admin/products/': page([productRow()]) }) })
    const { user } = renderRoute('/admin/products')
    await screen.findByRole('table', { name: 'Products' })
    await user.type(screen.getByLabelText('Search by name or SKU'), 'drill{Enter}')
    await user.selectOptions(screen.getByLabelText('Status'), 'Deleted')
    await user.selectOptions(screen.getByLabelText('Category'), 'Tools › Drills')
    await waitFor(() =>
      expect(paramsSent(api.get, '/admin/products/').at(-1)).toEqual({
        page_size: '20',
        page: '1',
        q: 'drill',
        state: 'deleted',
        category: '11',
      }),
    )
  })

  it('publishes and unpublishes', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { ...catalogGet(), '/admin/products/': page([productRow()]) }),
      patch: { '/admin/products/1/': adminProduct({ is_published: false, state: 'draft' }) },
    })
    const { user } = renderRoute('/admin/products')
    await user.click(await screen.findByRole('button', { name: 'Unpublish Impact Drill 650W' }))
    await waitFor(() => expect(lastBody(api.patch, '/admin/products/1/')).toEqual({ is_published: false }))
    expect(await screen.findByText('Impact Drill 650W is no longer on sale.')).toBeInTheDocument()
  })

  it('deletes only after a confirmation, and restores a deleted product', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        ...catalogGet(),
        '/admin/products/': page([productRow(), productRow({ id: 5, name: 'Old Saw', state: 'deleted', is_deleted: true })]),
      }),
      delete: { '/admin/products/1/': '' },
      post: { '/admin/products/5/restore/': adminProduct({ id: 5, name: 'Old Saw', state: 'draft' }) },
    })
    const { user } = renderRoute('/admin/products?state=all')
    await user.click(await screen.findByRole('button', { name: 'Delete Impact Drill 650W' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Delete Impact Drill 650W?' }))
    expect(api.delete).not.toHaveBeenCalled()
    await user.click(dialog.getByRole('button', { name: 'Cancel' }))
    expect(api.delete).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Delete Impact Drill 650W' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete product' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/admin/products/1/'))
    expect(await screen.findByText(/Impact Drill 650W deleted/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Restore Old Saw' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/products/5/restore/', {}))
  })

  it('a store manager can look up products but not change them', async () => {
    signIn()
    mockApi({ get: staffGet('manager', { ...catalogGet(), '/admin/products/': page([productRow()]), '/admin/products/1/': adminProduct() }) })
    const { user } = renderRoute('/admin/products')
    await screen.findByRole('table', { name: 'Products' })
    expect(screen.queryByRole('link', { name: 'Add product' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Delete|Unpublish/ })).not.toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Impact Drill 650W' }))
    const variants = within(await screen.findByRole('table', { name: 'Variants of Impact Drill 650W' }))
    expect(variants.getByText('₹4,000')).toBeInTheDocument()
    expect(variants.getByText('14')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save product' })).not.toBeInTheDocument()
  })

  it('checks a new product before sending it', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', catalogGet()), post: {} })
    const { user } = renderRoute('/admin/products/new')
    await user.click(await screen.findByRole('button', { name: 'Add product' }))
    const alert = within(await screen.findByRole('alert'))
    expect(alert.getByText('Give the product a name.')).toBeInTheDocument()
    expect(alert.getByText('Choose a category.')).toBeInTheDocument()
    expect(alert.getByText('Variant 1: give it a SKU.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Name *'), 'Angle Grinder')
    await user.type(screen.getByLabelText(/^Product SKU/), 'AG-850')
    await user.selectOptions(screen.getByLabelText(/^Category/), 'Tools')
    const first = within(screen.getByRole('group', { name: /Variant 1/ }))
    await user.type(first.getByLabelText(/^SKU/), 'AG-850-STD')
    await user.type(first.getByLabelText(/^MRP/), '3000')
    await user.type(first.getByLabelText(/^Selling price/), '3500')
    await user.click(screen.getByRole('button', { name: 'Add product' }))
    expect(await screen.findByText('AG-850-STD: the selling price can’t be higher than the MRP.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('creates a product with category, variants, prices, specifications and the returnable flag', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', catalogGet({ '/admin/products/77/': adminProduct({ id: 77, name: 'Angle Grinder' }) })),
      post: { '/admin/products/': adminProduct({ id: 77, name: 'Angle Grinder' }) },
    })
    const { user, router } = renderRoute('/admin/products/new')
    await user.type(await screen.findByLabelText('Name *'), 'Angle Grinder')
    await user.type(screen.getByLabelText(/^Product SKU/), 'AG-850')
    await user.selectOptions(screen.getByLabelText(/^Category/), 'Tools')
    await user.selectOptions(screen.getByLabelText('Subcategory'), 'Drills')
    await user.selectOptions(await screen.findByLabelText('Brand'), 'DrillCo')

    const first = within(screen.getByRole('group', { name: /Variant 1/ }))
    await user.type(first.getByLabelText(/^SKU/), 'AG-850-STD')
    await user.type(first.getByLabelText(/^MRP/), '3200')
    await user.type(first.getByLabelText(/^Selling price/), '2799')
    await user.click(screen.getByRole('button', { name: 'Add variant' }))
    const second = within(screen.getByRole('group', { name: /Variant 2/ }))
    await user.type(second.getByLabelText(/^SKU/), 'AG-850-KIT')
    await user.type(second.getByLabelText('Name'), 'With 5 discs')
    await user.type(second.getByLabelText(/^MRP/), '3800')
    await user.type(second.getByLabelText(/^Selling price/), '3299')

    await user.click(screen.getByRole('button', { name: 'Add specification' }))
    await user.type(screen.getByLabelText('Specification 1'), 'Power')
    await user.type(screen.getByLabelText('Value'), '850 W')
    await user.click(screen.getByLabelText(/^Published/))
    await user.click(screen.getByLabelText(/^Can be returned/))
    await user.click(screen.getByRole('button', { name: 'Add product' }))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(lastBody(api.post, '/admin/products/')).toMatchObject({
      name: 'Angle Grinder',
      sku: 'AG-850',
      category: 10,
      subcategory: 11,
      brand: 1,
      is_published: true,
      is_returnable: false,
      variants: [
        { sku: 'AG-850-STD', mrp: '3200', price: '2799', is_default: true, is_active: true },
        { sku: 'AG-850-KIT', name: 'With 5 discs', mrp: '3800', price: '3299', is_default: false },
      ],
      specifications: [{ name: 'Power', value: '850 W' }],
    })
    await waitFor(() => expect(currentUrl(router)).toBe('/admin/products/77'))
  })

  it('edits a product, shows the server’s complaint, and manages pictures', async () => {
    signIn()
    const withPictures = adminProduct({
      images: [
        { id: 1, image: '/media/a.jpg', alt_text: 'Front', is_primary: true, sort_order: 0 },
        { id: 2, image: '/media/b.jpg', alt_text: '', is_primary: false, sort_order: 1 },
      ],
    })
    const api = mockApi({
      get: staffGet('admin', catalogGet({ '/admin/products/1/': withPictures })),
      patch: {
        '/admin/products/1/': httpError(409, 'SKU ‘DEMO-DRILL-STD’ is already used by another variant.', 'duplicate_sku'),
        '/admin/products/1/images/2/': withPictures,
      },
      delete: { '/admin/products/1/images/2/': withPictures },
      post: { '/admin/products/1/images/': withPictures },
    })
    const { user } = renderRoute('/admin/products/1')
    const name = await screen.findByLabelText('Name *')
    expect(name).toHaveValue('Impact Drill 650W')
    expect(within(screen.getByRole('group', { name: /Variant 1/ })).getByLabelText(/^Selling price/)).toHaveValue('3200.00')
    expect(screen.getByLabelText('Specification 1')).toHaveValue('Power')

    await user.clear(name)
    await user.type(name, 'Impact Drill 700W')
    await user.click(screen.getByRole('button', { name: 'Save product' }))
    expect(await screen.findByText('SKU ‘DEMO-DRILL-STD’ is already used by another variant.')).toBeInTheDocument()
    expect(lastBody(api.patch, '/admin/products/1/')).toMatchObject({
      name: 'Impact Drill 700W',
      variants: [{ id: 101, sku: 'DEMO-DRILL-STD' }],
    })

    const pictures = within(screen.getByRole('region', { name: 'Pictures' }))
    expect(pictures.getByText('Main picture')).toBeInTheDocument()
    await user.click(pictures.getByRole('button', { name: 'Make main picture 2' }))
    await waitFor(() => expect(lastBody(api.patch, '/admin/products/1/images/2/')).toEqual({ is_primary: true }))
    await user.click(pictures.getByRole('button', { name: 'Remove picture 2' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/admin/products/1/images/2/'))

    const file = new File(['x'], 'side.png', { type: 'image/png' })
    await user.upload(pictures.getByLabelText('Add a picture'), file)
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    const form = lastBody(api.post, '/admin/products/1/images/') as FormData
    expect(form.get('image')).toBe(file)
  })
})

describe('categories and brands', () => {
  it('shows the tree and creates a subcategory', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', catalogGet()),
      post: { '/admin/categories/': adminCategories[0] },
      patch: { '/admin/categories/20/': adminCategories[1] },
    })
    const { user } = renderRoute('/admin/categories')
    expect(await screen.findByText('12 products · position 1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit Tools' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit Drills' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add subcategory to Drills' })).not.toBeInTheDocument() // two levels only
    expect(screen.getByText('Inactive')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add subcategory to Tools' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Add subcategory' }))
    expect(dialog.getByLabelText('Inside')).toHaveValue('10')
    await user.type(dialog.getByLabelText(/^Name/), 'Hand Tools')
    await user.clear(dialog.getByLabelText('Position'))
    await user.type(dialog.getByLabelText('Position'), '3')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(lastBody(api.post, '/admin/categories/')).toEqual({
        name: 'Hand Tools',
        parent: 10,
        description: '',
        sort_order: 3,
        is_active: true,
      }),
    )

    await user.click(screen.getByRole('button', { name: 'Activate Paint' }))
    await waitFor(() => expect(lastBody(api.patch, '/admin/categories/20/')).toEqual({ is_active: true }))
  })

  it('explains why a category with products can’t be deleted', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', catalogGet()),
      delete: { '/admin/categories/10/': httpError(409, 'Move or remove its products first.', 'category_has_products') },
    })
    const { user } = renderRoute('/admin/categories')
    await user.click(await screen.findByRole('button', { name: 'Delete Tools' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Delete Tools?' }))
    await user.click(dialog.getByRole('button', { name: 'Delete category' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('Move or remove its products first.')
  })

  it('adds and deactivates brands', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', catalogGet()),
      post: { '/admin/brands/': {} },
      patch: { '/admin/brands/1/': {} },
    })
    const { user } = renderRoute('/admin/brands')
    const row = within(await screen.findByRole('row', { name: /DrillCo/ }))
    expect(row.getByText('3')).toBeInTheDocument()
    await user.click(row.getByRole('button', { name: 'Deactivate DrillCo' }))
    await waitFor(() => expect(lastBody(api.patch, '/admin/brands/1/')).toEqual({ is_active: false }))

    await user.click(screen.getByRole('button', { name: 'Add brand' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Add brand' }))
    await user.type(dialog.getByLabelText(/^Name/), 'Stanley')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(lastBody(api.post, '/admin/brands/')).toEqual({ name: 'Stanley', is_active: true }))
  })
})

describe('inventory', () => {
  const rows = page([
    inventoryRow(),
    inventoryRow({ id: 52, sku: 'PRIMER-10', product_name: 'Wall Primer', variant_name: '10 L', available_quantity: 0, reserved_quantity: 0 }),
    inventoryRow({ id: 53, sku: 'HAMMER', product_name: 'Claw Hammer', variant_name: '', available_quantity: 60, is_low_stock: false }),
  ])

  it('shows available, reserved and low-stock status per store', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/inventory/': rows }) })
    renderRoute('/admin/inventory')
    const table = await screen.findByRole('table', { name: 'Inventory' })
    const drill = within(within(table).getByRole('row', { name: /DEMO-DRILL-STD/ }))
    expect(drill.getByText('Kothrud Store')).toBeInTheDocument()
    expect(drill.getByText('4')).toBeInTheDocument()
    expect(drill.getByText('2')).toBeInTheDocument()
    expect(drill.getByText('Low stock')).toBeInTheDocument()
    expect(within(within(table).getByRole('row', { name: /PRIMER-10/ })).getByText('Out of stock')).toBeInTheDocument()
    expect(within(within(table).getByRole('row', { name: /HAMMER/ })).getByText('In stock')).toBeInTheDocument()
  })

  it('opens on the low-stock filter from the dashboard link', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/inventory/': rows }) })
    renderRoute('/admin/inventory?stock=low')
    await screen.findByRole('table', { name: 'Inventory' })
    expect(paramsSent(api.get, '/inventory/')).toEqual([{ page_size: '20', page: '1', stock: 'low' }])
  })

  it('never sends an adjustment that would make stock negative', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/inventory/': rows }), post: {} })
    const { user } = renderRoute('/admin/inventory')
    await user.click(await screen.findByRole('button', { name: 'Adjust stock of DEMO-DRILL-STD' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Adjust stock: Impact Drill 650W' }))
    expect(dialog.getByText(/4 available, 2 reserved for orders/)).toBeInTheDocument()
    await user.selectOptions(dialog.getByLabelText('What happened'), 'Correction: remove')
    await user.type(dialog.getByLabelText(/^Units/), '5')
    await user.type(dialog.getByLabelText(/^Reason/), 'Miscount')
    await user.click(dialog.getByRole('button', { name: 'Record movement' }))
    expect(await dialog.findByText('Only 4 units are available; stock can’t go below zero.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('records a movement in the stock ledger, with a reason', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/inventory/': rows }),
      post: {
        '/inventory/51/adjust/': ({ body }: RequestInfo) => ({
          id: 900,
          inventory: 51,
          movement_type: 'adjustment',
          quantity: (body as { quantity: number }).quantity,
          available_after: 1,
          reserved_after: 2,
        }),
      },
    })
    const { user } = renderRoute('/admin/inventory')
    await user.click(await screen.findByRole('button', { name: 'Adjust stock of DEMO-DRILL-STD' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('What happened'), 'Correction: remove')
    await user.type(dialog.getByLabelText(/^Units/), '3')
    expect(dialog.getByText('Available afterwards: 1')).toBeInTheDocument()

    expect(dialog.getByLabelText(/^Reason/)).toBeRequired()
    await user.click(dialog.getByRole('button', { name: 'Record movement' }))
    expect(api.post).not.toHaveBeenCalled() // no movement without a reason

    await user.type(dialog.getByLabelText(/^Reason/), 'Two damaged, one lost')
    await user.click(dialog.getByRole('button', { name: 'Record movement' }))
    await waitFor(() =>
      expect(lastBody(api.post, '/inventory/51/adjust/')).toEqual({
        movement_type: 'adjustment',
        quantity: -3,
        reason: 'Two damaged, one lost',
      }),
    )
    expect(await screen.findByText('DEMO-DRILL-STD: 1 units available now.')).toBeInTheDocument()
  })

  it('shows what the server says when it refuses a movement', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', { '/inventory/': rows }),
      post: { '/inventory/51/adjust/': httpError(409, 'Not enough stock: 1 available.', 'insufficient_stock') },
    })
    const { user } = renderRoute('/admin/inventory')
    await user.click(await screen.findByRole('button', { name: 'Adjust stock of DEMO-DRILL-STD' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.type(dialog.getByLabelText(/^Units/), '2')
    await user.type(dialog.getByLabelText(/^Reason/), 'Delivery from supplier')
    await user.click(dialog.getByRole('button', { name: 'Record movement' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('Not enough stock: 1 available.')
  })

  it('shows the movements of a stock record', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        '/inventory/': rows,
        '/inventory/movements/': page([
          { id: 2, inventory: 51, sku: 'DEMO-DRILL-STD', store_code: 'PUN-01', movement_type: 'sale', quantity: -2, available_after: 4, reserved_after: 2, reason: '', reference_type: 'order', reference_id: 'OD260929ABCDEF', created_at: '2026-09-29T06:45:00Z' },
          { id: 1, inventory: 51, sku: 'DEMO-DRILL-STD', store_code: 'PUN-01', movement_type: 'purchase', quantity: 6, available_after: 6, reserved_after: 0, reason: 'Opening stock', reference_type: '', reference_id: '', created_at: '2026-09-20T06:45:00Z' },
        ]),
      }),
    })
    const { user } = renderRoute('/admin/inventory')
    await screen.findByRole('table', { name: 'Inventory' })
    expect(api.get).not.toHaveBeenCalledWith('/inventory/movements/', expect.anything()) // only when asked for
    await user.click(screen.getByRole('button', { name: 'Movements of DEMO-DRILL-STD' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Stock movements: DEMO-DRILL-STD' }))
    expect(await dialog.findByText('+6')).toBeInTheDocument()
    expect(dialog.getByText('-2')).toBeInTheDocument()
    expect(dialog.getByText(/Opening stock/)).toBeInTheDocument()
    expect(paramsSent(api.get, '/inventory/movements/')).toEqual([{ page_size: '10', inventory: '51', page: '1' }])
  })

  it('a store manager adjusts stock of their own store', async () => {
    signIn()
    mockApi({ get: staffGet('manager', { '/inventory/': page([inventoryRow()]) }) })
    renderRoute('/admin/inventory')
    expect(await screen.findByRole('button', { name: 'Adjust stock of DEMO-DRILL-STD' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Store')).not.toBeInTheDocument()
  })
})

describe('stores and warehouses', () => {
  it('lists stores and warehouses separately', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        '/admin/stores/': ({ params }: RequestInfo) =>
          page(
            params.kind === 'warehouse'
              ? [storeRow({ id: 3, name: 'Central Warehouse', code: 'WH-01', kind: 'warehouse', kind_label: 'Warehouse' })]
              : [storeRow(), storeRow({ id: 2, name: 'Hadapsar Store', code: 'PUN-02', zone_count: 0, accepts_orders: false, has_location: false })],
          ),
      }),
    })
    const { user } = renderRoute('/admin/stores')
    const table = await screen.findByRole('table', { name: 'Stores' })
    expect(within(within(table).getByRole('row', { name: /Kothrud Store/ })).getByText('Taking orders')).toBeInTheDocument()
    const other = within(within(table).getByRole('row', { name: /Hadapsar Store/ }))
    expect(other.getByText('Orders paused')).toBeInTheDocument()
    expect(other.getByText('No zone: can’t deliver')).toBeInTheDocument()
    expect(other.getByText('Missing')).toBeInTheDocument()
    expect(paramsSent(api.get, '/admin/stores/')[0]).toMatchObject({ kind: 'fulfilment' })

    await user.click(within(screen.getByRole('navigation', { name: 'Admin sections' })).getByRole('link', { name: 'Warehouses' }))
    expect(await screen.findByRole('link', { name: 'Central Warehouse' })).toHaveAttribute('href', '/admin/warehouses/3')
    expect(screen.getByRole('link', { name: 'Add warehouse' })).toHaveAttribute('href', '/admin/warehouses/new')
  })

  it('shows hours, zones, stock summary and riders of a store', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/stores/1/': storeDetail() }) })
    renderRoute('/admin/stores/1')
    expect(await screen.findByRole('heading', { name: 'Kothrud Store', level: 1 })).toBeInTheDocument()

    const stock = within(screen.getByRole('region', { name: 'Stock' }))
    expect(stock.getByText('2,400')).toBeInTheDocument()
    expect(stock.getByRole('link', { name: 'Open inventory' })).toHaveAttribute('href', '/admin/inventory?store=1')

    const zones = within(screen.getByRole('region', { name: 'Delivery zones' }))
    expect(zones.getByText('Kothrud 5 km')).toBeInTheDocument()
    expect(zones.getByText('Within 5.00 km · PIN codes 411029, 411038')).toBeInTheDocument()
    expect(zones.getByText('Delivery ₹40, free from ₹999 · fast delivery up to 45 min')).toBeInTheDocument()

    expect(within(screen.getByRole('region', { name: 'Managers' })).getByText('Sunil Manager')).toBeInTheDocument()
    expect(screen.getByLabelText('Monday opens')).toHaveValue('09:00')
    expect(screen.getByLabelText('Monday closes')).toHaveValue('21:00')
    expect(screen.queryByLabelText('Sunday opens')).not.toBeInTheDocument() // closed
    expect(screen.getByLabelText(/^Packing time/)).toHaveValue(10)
  })

  it('an administrator changes hours, packing time and fast-delivery settings', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/stores/1/': storeDetail() }),
      patch: { '/admin/stores/1/': storeDetail(), '/admin/zones/8/': zone() },
    })
    const { user } = renderRoute('/admin/stores/1')
    const opens = await screen.findByLabelText('Monday opens')
    await user.clear(opens)
    await user.type(opens, '08:30')
    await user.click(screen.getByRole('checkbox', { name: 'Sunday: open' }))
    await user.clear(screen.getByLabelText(/^Packing time/))
    await user.type(screen.getByLabelText(/^Packing time/), '15')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(lastBody(api.patch, '/admin/stores/1/')).toMatchObject({
      name: 'Kothrud Store',
      avg_prep_minutes: 15,
      opening_hours: { mon: ['08:30', '21:00'], tue: ['09:00', '21:00'], sun: ['09:00', '21:00'] },
    })

    await user.click(screen.getByRole('button', { name: 'Edit zone Kothrud 5 km' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Edit delivery zone' }))
    await user.click(dialog.getByLabelText('Fast delivery in this zone'))
    await user.type(dialog.getByLabelText(/^Delivery fee/), '25')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(lastBody(api.patch, '/admin/zones/8/')).toMatchObject({
        store: 1,
        radius_km: '5.00',
        postal_codes: '411029, 411038',
        fast_delivery_enabled: false,
        delivery_fee_override: '25',
        free_delivery_min_order: null,
      }),
    )
  })

  it('a store manager changes only how the store runs', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('manager', { '/admin/stores/1/': storeDetail({ can_edit: 'operations' }) }),
      patch: { '/admin/stores/1/': storeDetail({ can_edit: 'operations', accepts_orders: false }) },
    })
    const { user } = renderRoute('/admin/stores/1')
    expect(await screen.findByText(/You can change how this store runs day to day/)).toBeInTheDocument()
    expect(screen.getByLabelText('Name *')).toBeDisabled()
    expect(screen.getByLabelText(/^PIN code/)).toBeDisabled()
    expect(screen.getByLabelText('Latitude')).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Edit zone|Add zone|Remove/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Change managers' })).not.toBeInTheDocument()

    await user.click(screen.getByLabelText(/^Taking new orders/))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    const sent = lastBody(api.patch, '/admin/stores/1/') as Record<string, unknown>
    expect(Object.keys(sent).sort()).toEqual([
      'accepts_orders',
      'avg_prep_minutes',
      'opening_hours',
      'own_riders',
      'phone',
      'prep_minutes_per_item',
    ])
    expect(sent.accepts_orders).toBe(false)
  })

  it('explains why a store with orders can’t be removed', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', { '/admin/stores/1/': storeDetail() }),
      delete: { '/admin/stores/1/': httpError(409, 'This store still has orders in progress.', 'store_has_open_orders') },
    })
    const { user } = renderRoute('/admin/stores/1')
    await user.click(await screen.findByRole('button', { name: 'Remove' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Remove Kothrud Store?' }))
    await user.click(dialog.getByRole('button', { name: 'Remove store' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('This store still has orders in progress.')
  })
})
