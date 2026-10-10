import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AdminQuote, Quote } from '@/features/quotes/api'
import { adminSession, managerSession, page, staffGet } from '@/test/adminFixtures'
import { cart, cartLine, customer, TOTALS_800 } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

function quote(overrides: Partial<Quote> = {}): Quote {
  return {
    id: 7,
    number: 'RFQ261009ABCDE',
    status: 'requested',
    status_label: 'Requested',
    customer_note: 'Site in Whitefield',
    address: null,
    buyer_type: 'contractor',
    business_name: 'Asha Interiors',
    gstin: '',
    shop_note: '',
    valid_until: null,
    quoted_at: null,
    accepted_at: null,
    closed_reason: '',
    order_number: null,
    items: [
      {
        id: 70,
        variant_id: 5,
        sku: 'HNG-SC-35',
        product_name: 'Soft-close Hinge',
        product_slug: 'soft-close-hinge',
        variant_name: '',
        unit: 'piece',
        quantity: 200,
        customer_note: '',
        unit_mrp: '150.00',
        list_unit_price: '120.00',
        list_line_total: '24000.00',
        quoted_unit_price: null,
        quoted_line_total: null,
      },
    ],
    list_goods_total: '24000.00',
    quoted_goods_total: null,
    can_accept: false,
    can_checkout: false,
    can_close: true,
    created_at: '2026-10-09T09:00:00Z',
    updated_at: '2026-10-09T09:00:00Z',
    ...overrides,
  }
}

function quoted(overrides: Partial<Quote> = {}): Quote {
  const base = quote()
  return quote({
    status: 'quoted',
    status_label: 'Quotation sent',
    valid_until: '2026-10-16T09:00:00Z',
    shop_note: 'Delivery in 2 lots',
    items: [{ ...base.items[0]!, quoted_unit_price: '100.00', quoted_line_total: '20000.00' }],
    quoted_goods_total: '20000.00',
    can_accept: true,
    ...overrides,
  })
}

const customerGet = (extra: Record<string, unknown> = {}) => ({
  '/categories/': [],
  '/auth/me/': customer,
  '/wishlist/': [],
  '/search/recent/': [],
  '/cart/': { items: [] },
  ...extra,
})

describe('customer quotes', () => {
  it('shows the quotation with quoted and list prices and accepts it', async () => {
    signIn()
    const api = mockApi({
      get: customerGet({ '/quotes/7/': quoted() }),
      post: { '/quotes/7/accept/': quoted({ status: 'accepted', status_label: 'Accepted', can_accept: false, can_checkout: true }) },
    })
    const { user } = renderRoute('/account/quotes/7')
    expect(await screen.findByRole('heading', { name: 'Quote RFQ261009ABCDE' })).toBeInTheDocument()
    expect(screen.getByText(/valid until/)).toBeInTheDocument()
    expect(screen.getByText('From the shop: Delivery in 2 lots')).toBeInTheDocument()
    expect(screen.getAllByText('₹20,000').length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: 'Accept quotation' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/quotes/7/accept/'))
    expect(await screen.findByRole('link', { name: 'Check out this quotation' })).toHaveAttribute('href', '/checkout?quote=7')
  })

  it('shows the server’s reason when accepting fails (expired)', async () => {
    signIn()
    mockApi({
      get: customerGet({ '/quotes/7/': quoted() }),
      post: { '/quotes/7/accept/': httpError(409, 'This quotation has expired. Please request a new one.', 'quote_expired') },
    })
    const { user } = renderRoute('/account/quotes/7')
    await user.click(await screen.findByRole('button', { name: 'Accept quotation' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This quotation has expired.')
  })

  it('lists quotes and shows an empty state', async () => {
    signIn()
    mockApi({ get: customerGet({ '/quotes/': page([quoted()]) }) })
    renderRoute('/account/quotes')
    expect(await screen.findByText('RFQ261009ABCDE')).toBeInTheDocument()
    expect(screen.getByText('Quotation sent')).toBeInTheDocument()
  })

  it('empty list points to the cart', async () => {
    signIn()
    mockApi({ get: customerGet({ '/quotes/': page([]) }) })
    renderRoute('/account/quotes')
    expect(await screen.findByText('No quote requests yet')).toBeInTheDocument()
  })

  it('requests a quote for the cart and opens it', async () => {
    signIn()
    const api = mockApi({
      get: customerGet({
        '/cart/': cart({ items: [cartLine()], totals: TOTALS_800, can_checkout: true }),
        '/quotes/7/': quote(),
      }),
      post: { '/quotes/': quote() },
    })
    const { user, router } = renderRoute('/cart')
    await user.click(await screen.findByRole('button', { name: 'Request a bulk quote' }))
    const dialog = await screen.findByRole('dialog', { name: 'Request a bulk quote' })
    await user.type(within(dialog).getByLabelText(/Note for the shop/), 'Two lots')
    await user.click(within(dialog).getByRole('button', { name: 'Send request' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/quotes/', { from_cart: true, note: 'Two lots' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/account/quotes/7'))
  })
})

function adminQuote(overrides: Partial<AdminQuote> = {}): AdminQuote {
  return { ...quote(), customer_name: 'Asha Kulkarni', customer_email: 'asha@example.com', customer_phone: '9876543210', ...overrides }
}

describe('staff quotations', () => {
  const session = { ...adminSession, sections: [...adminSession.sections, 'quotes' as const] }

  it('lists requests', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/session/': session, '/admin/quotes/': page([adminQuote()]) }) })
    renderRoute('/admin/quotes')
    expect(await screen.findByRole('link', { name: 'RFQ261009ABCDE' })).toHaveAttribute('href', '/admin/quotes/7')
    expect(screen.getByText('Asha Interiors')).toBeInTheDocument()
  })

  it('checks prices against the MRP before sending, then sends the quotation', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/session/': session, '/admin/quotes/7/': adminQuote() }),
      post: { '/admin/quotes/7/quotation/': adminQuote({ status: 'quoted', status_label: 'Quotation sent' }) },
    })
    const { user } = renderRoute('/admin/quotes/7')
    await user.click(await screen.findByRole('button', { name: 'Send quotation' }))
    const dialog = await screen.findByRole('dialog', { name: 'Send quotation' })
    const price = within(dialog).getByLabelText('Unit price for Soft-close Hinge')
    expect(price).toHaveValue('120.00') // starts at the list price
    await user.clear(price)
    await user.type(price, '151')
    await user.click(within(dialog).getByRole('button', { name: 'Send quotation' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('not above the MRP')
    expect(api.post).not.toHaveBeenCalled()

    await user.clear(price)
    await user.type(price, '100')
    await user.click(within(dialog).getByRole('button', { name: 'Send quotation' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/admin/quotes/7/quotation/', {
        lines: [{ item_id: 70, unit_price: '100' }],
        valid_days: 7,
        shop_note: '',
      }),
    )
  })

  it('store managers can read but not send', async () => {
    signIn()
    mockApi({
      get: staffGet('manager', {
        '/admin/session/': { ...managerSession, sections: [...managerSession.sections, 'quotes' as const] },
        '/admin/quotes/7/': adminQuote(),
      }),
    })
    renderRoute('/admin/quotes/7')
    expect(await screen.findByText('Only administrators can send quotations.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Send quotation' })).not.toBeInTheDocument()
  })
})
