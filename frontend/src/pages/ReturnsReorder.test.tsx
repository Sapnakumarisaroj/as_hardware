import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ReturnRequest } from '@/features/orders/types'
import { cart, customer, orderDetail } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const NUMBER = 'OD260924ABCDEF'

function baseGet(extra: Record<string, unknown> = {}) {
  return { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/cart/': { items: [] }, ...extra }
}

function delivered(overrides = {}) {
  const base = orderDetail()
  return orderDetail({
    status: 'delivered',
    delivered_at: '2026-09-24T12:00:00Z',
    can_cancel: false,
    can_return: true,
    return_window_ends_at: '2026-10-01T12:00:00Z',
    items: [{ ...base.items[0]!, returnable_quantity: 2 }],
    ...overrides,
  })
}

function returnRequest(overrides: Partial<ReturnRequest> = {}): ReturnRequest {
  return {
    return_number: 'RT260925ABCDEF',
    order_number: NUMBER,
    status: 'requested',
    status_label: 'Requested',
    reason: 'damaged',
    reason_label: 'Arrived damaged',
    details: '',
    refund_amount: '400.00',
    refund_method: 'manual',
    refund_method_label: 'Manual (cash on delivery orders)',
    refund_status: null,
    restocked: false,
    decision_note: '',
    created_at: '2026-09-25T09:00:00Z',
    decided_at: null,
    received_at: null,
    cancelled_at: null,
    can_cancel: true,
    pickup: null,
    items: [
      {
        order_item_id: 1,
        sku: 'DEMO-WIRE-15-10',
        product_name: 'FR PVC Insulated Copper Wire',
        variant_name: '1.5 sq mm × 10 m',
        quantity: 1,
        refund_amount: '400.00',
        image: null,
      },
    ],
    ...overrides,
  }
}

describe('buy again', () => {
  it('adds the order to the cart and explains what could not be added', async () => {
    signIn()
    const api = mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: delivered() }),
      post: {
        [`/orders/${NUMBER}/reorder/`]: {
          added: [{ sku: 'DEMO-WIRE-15-10', name: 'FR PVC Insulated Copper Wire', requested: 2, added: 1, reason: 'Only 1 added (stock or order limit).' }],
          skipped: [
            { sku: 'DEMO-WIRE-15-10', name: 'FR PVC Insulated Copper Wire', requested: 2, added: 1, reason: 'Only 1 added (stock or order limit).' },
            { sku: 'DEMO-TAPE', name: 'PTFE Tape', requested: 1, added: 0, reason: 'No longer sold.' },
          ],
          cart: cart(),
        },
      },
    })
    const { user } = renderRoute(`/account/orders/${NUMBER}`)
    await user.click(await screen.findByRole('button', { name: 'Buy again' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/orders/${NUMBER}/reorder/`))
    expect(await screen.findByText('Added 1 item to your cart')).toBeInTheDocument()
    const notice = screen.getByText('Not everything was added:').closest('div')!
    expect(within(notice).getByText(/PTFE Tape: No longer sold\./)).toBeInTheDocument()
    expect(within(notice).getByText(/Only 1 added/)).toBeInTheDocument()
  })

  it('is hidden when no item can be bought again', async () => {
    signIn()
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: delivered({ can_reorder: false }) }) })
    renderRoute(`/account/orders/${NUMBER}`)
    expect(await screen.findByRole('heading', { name: `Order ${NUMBER}` })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Buy again' })).not.toBeInTheDocument()
  })
})

describe('returns', () => {
  it('requests a return with chosen quantity and reason; the server decides the refund', async () => {
    signIn()
    const api = mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: delivered() }),
      post: { '/returns/': returnRequest() },
    })
    const { user } = renderRoute(`/account/orders/${NUMBER}`)
    expect(await screen.findByText(/Returns open until/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Return items' }))
    const dialog = await screen.findByRole('dialog', { name: 'Return items' })

    await user.click(within(dialog).getByRole('button', { name: 'Request return' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Choose at least one item to return.')

    const quantity = within(dialog).getByRole('combobox', { name: /Return quantity for FR PVC/ })
    expect(within(quantity).getAllByRole('option').map((o) => o.textContent)).toEqual(['0', '1', '2'])
    await user.selectOptions(quantity, '1')
    await user.click(within(dialog).getByRole('button', { name: 'Request return' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Please choose a reason.')

    await user.click(within(dialog).getByRole('radio', { name: 'Arrived damaged' }))
    await user.click(within(dialog).getByRole('button', { name: 'Request return' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/returns/', {
        order_number: NUMBER,
        reason: 'damaged',
        details: '',
        items: [{ order_item_id: 1, quantity: 1 }],
      }),
    )
    expect(await screen.findByText('Return RT260925ABCDEF requested')).toBeInTheDocument()
  })

  it('"Other" needs details and server errors are shown', async () => {
    signIn()
    mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: delivered() }),
      post: { '/returns/': httpError(400, 'The return window for this order has closed (7 days after delivery).', 'return_window_closed') },
    })
    const { user } = renderRoute(`/account/orders/${NUMBER}`)
    await user.click(await screen.findByRole('button', { name: 'Return items' }))
    const dialog = await screen.findByRole('dialog', { name: 'Return items' })
    await user.selectOptions(within(dialog).getByRole('combobox', { name: /Return quantity/ }), '2')
    await user.click(within(dialog).getByRole('radio', { name: 'Other' }))
    await user.click(within(dialog).getByRole('button', { name: 'Request return' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Please describe the problem.')
    await user.type(within(dialog).getByLabelText(/Details/), 'Wrong colour')
    await user.click(within(dialog).getByRole('button', { name: 'Request return' }))
    expect(await within(dialog).findByText(/return window for this order has closed/)).toBeInTheDocument()
  })

  it('no return option before delivery or after the window', async () => {
    signIn()
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: orderDetail() }) })
    renderRoute(`/account/orders/${NUMBER}`)
    expect(await screen.findByRole('button', { name: 'Cancel order' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Return items' })).not.toBeInTheDocument()
  })

  it('shows the order’s returns with refund and lets the customer withdraw an open request', async () => {
    signIn()
    const received = returnRequest({
      return_number: 'RT260925RECVD1',
      status: 'received',
      status_label: 'Received — refund initiated',
      refund_status: 'pending',
      can_cancel: false,
    })
    const api = mockApi({
      get: baseGet({
        [`/orders/${NUMBER}/`]: delivered({ status: 'return_requested', can_return: false, returns: [returnRequest(), received] }),
      }),
      post: { '/returns/RT260925ABCDEF/cancel/': returnRequest({ status: 'cancelled', can_cancel: false }) },
    })
    const { user } = renderRoute(`/account/orders/${NUMBER}`)
    const open = await screen.findByRole('article', { name: 'Return RT260925ABCDEF' })
    expect(within(open).getByText('We’re reviewing your request.')).toBeInTheDocument()
    const done = screen.getByRole('article', { name: 'Return RT260925RECVD1' })
    expect(within(done).getByText(/Your refund has been initiated/)).toBeInTheDocument()
    expect(within(done).queryByRole('button', { name: /Cancel return/ })).not.toBeInTheDocument()

    await user.click(within(open).getByRole('button', { name: 'Cancel return request' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/returns/RT260925ABCDEF/cancel/'))
    expect(await screen.findByText('Return RT260925ABCDEF cancelled')).toBeInTheDocument()
  })

  it('shows the delivery partner who collects an approved return', async () => {
    signIn()
    const approved = returnRequest({
      status: 'approved',
      status_label: 'Approved — awaiting pickup/drop',
      can_cancel: false,
      pickup: {
        status: 'accepted',
        status_label: 'A delivery partner will collect your items',
        rider_name: 'Ravi',
        rider_phone: '9123456780',
        picked_up_at: null,
        failure_reason: '',
      },
    })
    mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: delivered({ status: 'return_requested', can_return: false, returns: [approved] }) }),
    })
    renderRoute(`/account/orders/${NUMBER}`)
    const card = await screen.findByRole('article', { name: 'Return RT260925ABCDEF' })
    expect(card).toHaveTextContent('Pickup: A delivery partner will collect your items (Ravi)')
    expect(within(card).getByRole('link', { name: 'Call Ravi' })).toHaveAttribute('href', 'tel:9123456780')
  })

  it('returns page lists returns with a link to the order, or an empty state', async () => {
    signIn()
    mockApi({ get: baseGet({ '/returns/': { count: 1, next: null, previous: null, results: [returnRequest()] } }) })
    const view = renderRoute('/account/returns')
    expect(await screen.findByRole('heading', { name: 'Your returns' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: `Order ${NUMBER}` })).toHaveAttribute('href', `/account/orders/${NUMBER}`)
    view.unmount()

    mockApi({ get: baseGet({ '/returns/': { count: 0, next: null, previous: null, results: [] } }) })
    renderRoute('/account/returns')
    expect(await screen.findByText('No returns')).toBeInTheDocument()
  })
})
