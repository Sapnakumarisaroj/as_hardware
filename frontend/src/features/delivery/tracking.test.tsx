import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { OrderShipment } from '@/features/delivery/types'
import type { OrderDetail } from '@/features/orders/types'
import { customer, orderDetail } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const NUMBER = 'OD260924ABCDEF'
const RIDER = { name: 'Ravi', vehicle: 'Scooter / bike', phone: null, status: 'assigned' }

function baseGet(extra: Record<string, unknown> = {}) {
  return { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/cart/': { items: [] }, ...extra }
}

function shipment(overrides: Partial<OrderShipment> = {}): OrderShipment {
  return { ...orderDetail().shipments[0]!, ...overrides }
}

function order(status: OrderDetail['status'], shipments: OrderShipment[], overrides: Partial<OrderDetail> = {}) {
  return orderDetail({ status, shipments, can_cancel: false, ...overrides })
}

function tracking() {
  return screen.getByRole('heading', { name: 'Track delivery' }).closest('section')!
}

async function open(data: OrderDetail, extra: Parameters<typeof mockApi>[0] = {}) {
  signIn()
  const api = mockApi({ ...extra, get: { ...baseGet({ [`/orders/${NUMBER}/`]: data }), ...extra.get } })
  const view = renderRoute(`/account/orders/${NUMBER}`)
  await screen.findByRole('heading', { name: `Order ${NUMBER}` })
  return { api, ...view }
}

describe('delivery tracking on the order page', () => {
  it('is not shown before a delivery partner is involved', async () => {
    await open(orderDetail())
    expect(screen.queryByRole('heading', { name: 'Track delivery' })).not.toBeInTheDocument()
  })

  it('shows the assigned rider, the steps and the cash to pay, but no phone number or code yet', async () => {
    await open(
      order('assigned', [
        shipment({ status: 'assigned', status_label: 'Delivery partner assigned', rider: RIDER, amount_to_pay: '800.00' }),
      ]),
    )
    const section = tracking()
    const progress = within(section).getByRole('list', { name: 'Delivery progress' })
    const steps = within(progress).getAllByRole('listitem').map((li) => li.textContent)
    expect(steps[0]).toMatch(/Delivery partner assigned — done.*Now/)
    expect(steps[1]).toMatch(/Picked up from the store — not yet/)
    expect(section).toHaveTextContent('Ravi · Scooter / bike')
    expect(section).toHaveTextContent('Cash on delivery: pay ₹800 to the delivery partner')
    expect(within(section).queryByRole('link', { name: /Call/ })).not.toBeInTheDocument()
    expect(within(section).queryByRole('group', { name: 'Delivery code' })).not.toBeInTheDocument()
  })

  it('out for delivery: shows the code to read out, its validity and a way to call the rider', async () => {
    await open(
      order('out_for_delivery', [
        shipment({
          status: 'out_for_delivery',
          status_label: 'Out for delivery',
          delivery_attempts: 1,
          picked_up_at: '2026-09-24T10:20:00Z',
          out_for_delivery_at: '2026-09-24T10:25:00Z',
          rider: { ...RIDER, phone: '9123456780', status: 'out_for_delivery' },
          delivery_code: { state: 'active', code: '482913', expires_at: '2026-09-24T10:55:00Z', can_request_new: false },
        }),
      ]),
    )
    const code = within(tracking()).getByRole('group', { name: 'Delivery code' })
    expect(code).toHaveTextContent('482913')
    expect(code).toHaveTextContent('Code: 4 8 2 9 1 3') // read digit by digit by screen readers
    expect(code).toHaveTextContent('Valid until 4:25 PM')
    expect(code).toHaveTextContent('Never share it on a call or message')
    expect(within(code).queryByRole('button', { name: 'Get a new code' })).not.toBeInTheDocument()
    expect(within(tracking()).getByRole('link', { name: /Call Ravi/ })).toHaveAttribute('href', 'tel:9123456780')
    expect(tracking()).toHaveTextContent(/Out for delivery — done.*Now/)
  })

  it('an expired or blocked code is replaced on request', async () => {
    const expired = order('out_for_delivery', [
      shipment({
        status: 'out_for_delivery',
        rider: RIDER,
        delivery_code: { state: 'expired', code: null, expires_at: '2026-09-24T10:55:00Z', can_request_new: true },
      }),
    ])
    const fresh = order('out_for_delivery', [
      shipment({
        status: 'out_for_delivery',
        rider: RIDER,
        delivery_code: { state: 'active', code: '730155', expires_at: '2026-09-24T11:40:00Z', can_request_new: false },
      }),
    ])
    const { api, user } = await open(expired, { post: { [`/orders/${NUMBER}/shipments/1/delivery-code/`]: fresh } })
    const box = within(tracking()).getByRole('group', { name: 'Delivery code' })
    expect(box).toHaveTextContent('Your code has expired. Get a new code to receive your order.')
    await user.click(within(box).getByRole('button', { name: 'Get a new code' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/orders/${NUMBER}/shipments/1/delivery-code/`))
    expect(await within(tracking()).findByText('730155')).toBeInTheDocument()
  })

  it('explains when a new code cannot be issued yet', async () => {
    const locked = order('out_for_delivery', [
      shipment({
        status: 'out_for_delivery',
        rider: RIDER,
        delivery_code: { state: 'locked', code: null, expires_at: null, can_request_new: true },
      }),
    ])
    const { user } = await open(locked, {
      post: {
        [`/orders/${NUMBER}/shipments/1/delivery-code/`]: httpError(
          409,
          'Please wait 60 seconds before asking for another code.',
          'otp_too_soon',
        ),
      },
    })
    const box = within(tracking()).getByRole('group', { name: 'Delivery code' })
    expect(box).toHaveTextContent('Too many wrong codes were entered')
    await user.click(within(box).getByRole('button', { name: 'Get a new code' }))
    expect(await within(box).findByRole('alert')).toHaveTextContent('Please wait 60 seconds')
  })

  it('shows a completed delivery with who received it and the photo on request', async () => {
    const createObjectURL = vi.fn(() => 'blob:proof-1')
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() })
    const done = order(
      'delivered',
      [
        shipment({
          status: 'delivered',
          status_label: 'Delivered',
          delivered_at: '2026-09-24T10:40:00Z',
          rider: { ...RIDER, status: 'delivered' },
          received_by: 'Asha',
          proof_available: true,
        }),
      ],
      { delivered_at: '2026-09-24T10:40:00Z', delivery_message: 'Delivered' },
    )
    const { api, user } = await open(done, {
      get: { [`/orders/${NUMBER}/shipments/1/proof/`]: new Blob(['jpeg'], { type: 'image/jpeg' }) },
    })
    const section = tracking()
    expect(section).toHaveTextContent('Delivered on 24 Sept, 4:10 PM')
    expect(section).toHaveTextContent('Received by Asha')
    expect(within(section).queryByRole('group', { name: 'Delivery code' })).not.toBeInTheDocument()
    expect(within(section).queryByRole('link', { name: /Call/ })).not.toBeInTheDocument()
    expect(within(section).queryByRole('img')).not.toBeInTheDocument() // not downloaded until asked for

    await user.click(within(section).getByRole('button', { name: 'View delivery photo' }))
    const photo = await within(section).findByRole('img', { name: 'Photo taken when your order was delivered' })
    expect(photo).toHaveAttribute('src', 'blob:proof-1')
    expect(api.get).toHaveBeenCalledWith(`/orders/${NUMBER}/shipments/1/proof/`, { responseType: 'blob' })
  })

  it('explains a failed delivery and what happens next', async () => {
    await open(
      order(
        'delivery_failed',
        [
          shipment({
            status: 'failed',
            status_label: 'Delivery attempt failed',
            delivery_attempts: 1,
            picked_up_at: '2026-09-24T10:20:00Z',
            out_for_delivery_at: '2026-09-24T10:25:00Z',
            rider: { ...RIDER, status: 'failed' },
            failure: {
              code: 'customer_unavailable',
              reason: 'Customer not available',
              failed_at: '2026-09-24T10:50:00Z',
              next_step: 'The store will contact you to arrange another delivery attempt.',
            },
          }),
        ],
        {
          delivery_message: 'We couldn’t deliver your order. The store will contact you to arrange another attempt.',
          status_history: [
            ...orderDetail().status_history,
            { from_status: 'out_for_delivery', to_status: 'delivery_failed', note: '', created_at: '2026-09-24T10:50:00Z' },
          ],
        },
      ),
    )
    const section = tracking()
    const alert = within(section).getByRole('alert')
    expect(alert).toHaveTextContent('We couldn’t deliver this: customer not available.')
    expect(alert).toHaveTextContent('The store will contact you to arrange another delivery attempt.')
    expect(section).toHaveTextContent('Delivery attempt failed24 Sept, 4:20 PM')
    expect(within(section).queryByRole('group', { name: 'Delivery code' })).not.toBeInTheDocument()
    expect(screen.getAllByText('Delivery attempt failed').length).toBeGreaterThan(1) // badge + timeline
    const timeline = screen.getByRole('list', { name: 'Order progress' })
    expect(within(timeline).queryByText('Delivered')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel order' })).not.toBeInTheDocument()
  })

  it('tracks each store’s shipment of a split order separately', async () => {
    const base = orderDetail()
    await open(
      order(
        'assigned',
        [
          shipment({ status: 'delivered', delivered_at: '2026-09-24T10:40:00Z', rider: RIDER, item_ids: [1] }),
          shipment({
            sequence: 2,
            store_name: 'Demo Dark Store',
            status: 'assigned',
            rider: { ...RIDER, name: 'Meera' },
            item_ids: [2],
            amount_to_pay: '120.00',
          }),
        ],
        { items: [base.items[0]!, { ...base.items[0]!, id: 2, product_name: 'PTFE Tape', sku: 'DEMO-TAPE' }] },
      ),
    )
    const [first, second] = within(tracking()).getAllByRole('listitem').filter((li) => li.textContent?.startsWith('From '))
    expect(first).toHaveTextContent('From Demo Store')
    expect(first).toHaveTextContent('FR PVC Insulated Copper Wire')
    expect(first).toHaveTextContent('Delivered on 24 Sept')
    expect(second).toHaveTextContent('From Demo Dark Store')
    expect(second).toHaveTextContent('PTFE Tape')
    expect(second).toHaveTextContent('Meera · Scooter / bike')
    expect(second).toHaveTextContent('pay ₹120')
  })

  it('also appears on the order confirmation page', async () => {
    signIn()
    const data = order('assigned', [shipment({ status: 'assigned', rider: RIDER })])
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: data }) })
    renderRoute(`/order-confirmation/${NUMBER}`)
    expect(await screen.findByRole('heading', { name: 'Track delivery' })).toBeInTheDocument()
  })
})
