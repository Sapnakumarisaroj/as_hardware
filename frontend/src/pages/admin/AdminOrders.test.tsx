import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AdminOrderDetail } from '@/features/admin/types'
import { adminOrder, assignedShipment, orderRow, page, staffGet, staffShipment } from '@/test/adminFixtures'
import { httpError, mockApi, paramsSent, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const NUMBER = 'OD260929ABCDEF'
const DETAIL = `/admin/orders/${NUMBER}/`

function lastBody(spy: ReturnType<typeof mockApi>['post'], url: string) {
  return spy.mock.calls.filter(([called]) => called === url).at(-1)?.[1]
}

describe('orders: list', () => {
  it('lists orders with customer, payment, status, store and rider', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', {
        '/admin/orders/': page([
          orderRow(),
          orderRow({
            order_number: 'OD260928REFUND',
            status: 'cancelled',
            payment_method: 'online',
            payment_status: 'paid',
            refund_status: 'failed',
            shipments: [],
          }),
          orderRow({
            order_number: 'OD260927RETURN',
            status: 'delivered',
            payment_status: 'paid',
            open_return: true,
            shipments: [{ id: 9, sequence: 1, store_name: 'Kothrud Store', status: 'delivered', rider: 'Ravi Rider' }],
          }),
        ]),
      }),
    })
    renderRoute('/admin/orders')
    const table = await screen.findByRole('table', { name: 'Orders' })
    const row = within(within(table).getByRole('row', { name: new RegExp(NUMBER) }))
    expect(row.getByRole('link', { name: NUMBER })).toHaveAttribute('href', `/admin/orders/${NUMBER}`)
    expect(row.getByText('Asha Kulkarni')).toBeInTheDocument()
    expect(row.getByText('9876543210')).toBeInTheDocument()
    expect(row.getByText('₹1,240')).toBeInTheDocument()
    expect(row.getByText('Pay on delivery')).toBeInTheDocument()
    expect(row.getByText('Packed')).toBeInTheDocument()
    expect(row.getByText('No rider yet')).toBeInTheDocument()

    expect(within(within(table).getByRole('row', { name: /OD260928REFUND/ })).getByText('Refund failed')).toBeInTheDocument()
    const returned = within(within(table).getByRole('row', { name: /OD260927RETURN/ }))
    expect(returned.getByText('Return open')).toBeInTheDocument()
    expect(returned.getByText('Ravi Rider')).toBeInTheDocument()
    expect(screen.getByText('1–3 of 3')).toBeInTheDocument()
  })

  it('searches and filters on the server and keeps the filters in the address', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/admin/orders/': page([orderRow()], 45) }) })
    const { user, router } = renderRoute('/admin/orders')
    await screen.findByRole('table', { name: 'Orders' })
    expect(paramsSent(api.get, '/admin/orders/')).toEqual([{ page_size: '20', page: '1' }])

    await user.type(screen.getByLabelText('Search orders'), 'asha')
    expect(paramsSent(api.get, '/admin/orders/')).toHaveLength(1) // nothing is asked while typing
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await user.selectOptions(screen.getByLabelText('Status'), 'Being prepared')
    await user.selectOptions(screen.getByLabelText('Method'), 'Cash on delivery')
    await user.selectOptions(screen.getByLabelText('Store'), 'Kothrud Store')
    await waitFor(() =>
      expect(currentUrl(router)).toBe('/admin/orders?q=asha&status=preparing&payment_method=cod&store=1'),
    )
    await waitFor(() =>
      expect(paramsSent(api.get, '/admin/orders/').at(-1)).toEqual({
        page_size: '20',
        page: '1',
        q: 'asha',
        status: 'preparing',
        payment_method: 'cod',
        store: '1',
      }),
    )

    await user.click(screen.getByRole('button', { name: 'Page 2' }))
    await waitFor(() => expect(paramsSent(api.get, '/admin/orders/').at(-1)).toMatchObject({ page: '2', q: 'asha' }))
    expect(screen.getByRole('button', { name: 'Page 3' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/admin/orders'))
    expect(screen.getByLabelText('Search orders')).toHaveValue('')
  })

  it('opens with the filters of a shared link', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/admin/orders/': page([orderRow()]) }) })
    renderRoute('/admin/orders?status=delivery_failed&page=2&customer=7')
    await screen.findByRole('table', { name: 'Orders' })
    expect(paramsSent(api.get, '/admin/orders/')).toEqual([{ page_size: '20', page: '2', status: 'delivery_failed', customer: '7' }])
    expect(screen.getByLabelText('Status')).toHaveValue('delivery_failed')
  })

  it('tells the difference between no orders and no matches', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/orders/': page([]) }) })
    const { user } = renderRoute('/admin/orders')
    expect(await screen.findByText('No orders yet')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Status'), 'Cancelled')
    expect(await screen.findByText('Nothing matches these filters')).toBeInTheDocument()
  })

  it('shows an error with a retry', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/orders/': httpError(500, 'Server error.') }) })
    renderRoute('/admin/orders')
    expect(await screen.findByText('Couldn’t load orders')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('a store manager with one store gets no store filter', async () => {
    signIn()
    mockApi({ get: staffGet('manager', { '/admin/orders/': page([orderRow()]) }) })
    renderRoute('/admin/orders')
    await screen.findByRole('table', { name: 'Orders' })
    expect(screen.queryByLabelText('Store')).not.toBeInTheDocument()
  })
})

describe('orders: detail', () => {
  it('shows customer, items, totals, delivery, shipment and history', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { [DETAIL]: adminOrder() }) })
    renderRoute(`/admin/orders/${NUMBER}`)
    expect(await screen.findByRole('heading', { name: `Order ${NUMBER}`, level: 1 })).toBeInTheDocument()

    const customer = within(screen.getByRole('region', { name: 'Customer' }))
    expect(customer.getByText('Asha Kulkarni')).toBeInTheDocument()
    expect(customer.getByRole('link', { name: 'asha@example.com' })).toHaveAttribute('href', 'mailto:asha@example.com')
    expect(customer.getByRole('link', { name: 'Open customer' })).toHaveAttribute('href', '/admin/customers/7')

    const order = adminOrder()
    const items = within(screen.getByRole('table', { name: 'Items of this order' }))
    expect(items.getAllByRole('row')).toHaveLength(order.items.length + 1)
    expect(items.getByText(order.items[0]!.product_name)).toBeInTheDocument()

    const shipment = within(screen.getByRole('region', { name: 'Shipment' }))
    expect(shipment.getByText('Kothrud Store')).toBeInTheDocument()
    expect(shipment.getByText('Waiting for a rider')).toBeInTheDocument()
    expect(shipment.getByText('Not assigned')).toBeInTheDocument()
    expect(shipment.getByRole('button', { name: `Assign rider for order ${NUMBER}` })).toBeInTheDocument()

    expect(screen.getByRole('region', { name: 'History' })).toBeInTheDocument()
    const crumbs = within(screen.getByRole('navigation', { name: 'Breadcrumb' }))
    expect(crumbs.getByRole('link', { name: 'Orders' })).toHaveAttribute('href', '/admin/orders')
  })

  it('offers only the steps the server allows', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { [DETAIL]: adminOrder() }) })
    renderRoute(`/admin/orders/${NUMBER}`)
    const next = within(await screen.findByRole('region', { name: 'What to do next' }))
    expect(next.getAllByRole('button').map((b) => b.textContent)).toEqual(['Hand to own rider', 'Cancel order'])
    expect(next.queryByRole('button', { name: 'Mark as delivered' })).not.toBeInTheDocument()
  })

  it('changes the status through the order API after a confirmation', async () => {
    signIn()
    let current: AdminOrderDetail = adminOrder({
      status: 'confirmed',
      allowed_actions: [
        { status: 'processing', label: 'Processing' },
        { status: 'cancelled', label: 'Cancelled' },
      ],
    })
    const api = mockApi({
      get: staffGet('admin', { [DETAIL]: () => current }),
      post: {
        [`/orders/${NUMBER}/transition/`]: ({ body }: RequestInfo) => {
          const status = (body as { status: 'processing' }).status
          current = adminOrder({ status, allowed_actions: [{ status: 'packed', label: 'Packed' }] })
          return current
        },
      },
    })
    const { user } = renderRoute(`/admin/orders/${NUMBER}`)
    await user.click(await screen.findByRole('button', { name: 'Start preparing' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Start preparing?' }))
    expect(api.post).not.toHaveBeenCalled() // nothing happens before the confirmation
    await user.click(dialog.getByRole('button', { name: 'Start preparing' }))

    await waitFor(() => expect(lastBody(api.post, `/orders/${NUMBER}/transition/`)).toEqual({ status: 'processing', note: '' }))
    expect(await screen.findByText(`Order ${NUMBER} updated.`)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Mark as packed' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('needs a reason to cancel, and shows why the server refused', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { [DETAIL]: adminOrder() }),
      post: {
        [`/orders/${NUMBER}/transition/`]: httpError(409, 'The goods have already left the store.', 'invalid_transition'),
      },
    })
    const { user } = renderRoute(`/admin/orders/${NUMBER}`)
    await user.click(await screen.findByRole('button', { name: 'Cancel order' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Cancel order?' }))
    const confirm = dialog.getByRole('button', { name: 'Cancel order' })
    expect(confirm).toBeDisabled()
    await user.type(dialog.getByLabelText(/Reason for cancelling/), 'Customer called')
    await user.click(confirm)
    expect(await dialog.findByRole('alert')).toHaveTextContent('The goods have already left the store.')
    expect(lastBody(api.post, `/orders/${NUMBER}/transition/`)).toEqual({ status: 'cancelled', note: 'Customer called' })
    expect(screen.getByRole('dialog', { name: 'Cancel order?' })).toBeInTheDocument() // stays open to try again
  })

  it('leaves the delivery steps to the rider once one is in charge', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', {
        [DETAIL]: adminOrder({ status: 'assigned', allowed_actions: [], staff_shipments: [assignedShipment()] }),
      }),
    })
    renderRoute(`/admin/orders/${NUMBER}`)
    expect(await screen.findByText('A delivery partner is handling this order; their steps move it forward.')).toBeInTheDocument()
    const shipment = within(screen.getByRole('region', { name: 'Shipment' }))
    expect(shipment.getByText('Ravi Rider · 9123456780')).toBeInTheDocument()
    expect(shipment.getByRole('button', { name: `Reassign for order ${NUMBER}` })).toBeInTheDocument()
    expect(shipment.getByRole('button', { name: `Unassign order ${NUMBER}` })).toBeInTheDocument()
  })

  it('assigns a rider the server calls eligible', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        [DETAIL]: adminOrder(),
        '/delivery/shipments/31/eligible-partners/': [
          { partner_id: 4, full_name: 'Ravi Rider', vehicle_type: 'scooter', same_store: true, active_assignments: 0, capacity: 2, distance_km: 1.2 },
          { partner_id: 6, full_name: 'Imran Shaikh', vehicle_type: 'van', same_store: false, active_assignments: 1, capacity: 3, distance_km: null },
        ],
      }),
      post: { '/delivery/shipments/31/assign/': { assignment_id: 5, order_status: 'assigned', partner_id: 6 } },
    })
    const { user } = renderRoute(`/admin/orders/${NUMBER}`)
    await user.click(await screen.findByRole('button', { name: `Assign rider for order ${NUMBER}` }))
    const dialog = within(screen.getByRole('dialog', { name: `Assign order ${NUMBER}` }))
    const assign = dialog.getByRole('button', { name: 'Assign' })
    expect(assign).toBeDisabled()
    expect(await dialog.findByText('scooter · 0 of 2 jobs · 1.2 km from the store')).toBeInTheDocument()
    await user.click(dialog.getByRole('radio', { name: /Imran Shaikh/ }))
    await user.click(assign)
    await waitFor(() => expect(lastBody(api.post, '/delivery/shipments/31/assign/')).toEqual({ partner_id: 6 }))
    expect(await screen.findByText(`Order ${NUMBER} assigned.`)).toBeInTheDocument()
  })

  it('says so when no rider can take the shipment', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { [DETAIL]: adminOrder(), '/delivery/shipments/31/eligible-partners/': [] }) })
    const { user } = renderRoute(`/admin/orders/${NUMBER}`)
    await user.click(await screen.findByRole('button', { name: `Assign rider for order ${NUMBER}` }))
    expect(await screen.findByText(/No delivery partner can take this shipment right now/)).toBeInTheDocument()
  })

  it('a manager of another store can look but not act', async () => {
    signIn()
    mockApi({
      get: staffGet('manager', {
        [DETAIL]: adminOrder({ can_manage: false, allowed_actions: [], staff_shipments: [staffShipment()] }),
      }),
    })
    renderRoute(`/admin/orders/${NUMBER}`)
    expect(await screen.findByText('This order belongs to a store you don’t manage, so you can’t change it.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Assign rider/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open customer' })).not.toBeInTheDocument()
  })

  it('shows “not found” for an order of another store', async () => {
    signIn()
    mockApi({ get: staffGet('manager', { '/admin/orders/OD000/': httpError(404, 'Not found.', 'not_found') }) })
    renderRoute('/admin/orders/OD000')
    expect(await screen.findByRole('heading', { name: /not found|can’t find|couldn’t find/i })).toBeInTheDocument()
  })
})
