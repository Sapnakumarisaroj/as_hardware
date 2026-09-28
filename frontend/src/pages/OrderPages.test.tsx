import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { address, customer, NO_ESTIMATE, orderDelivery, orderDetail, pendingOnlineOrder } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const NUMBER = 'OD260924ABCDEF'

function baseGet(extra: Record<string, unknown> = {}) {
  return { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/cart/': { items: [] }, ...extra }
}

describe('payment step (mock gateway)', () => {
  it('successful mock payment is verified by the server and shows the confirmation', async () => {
    signIn()
    const paid = orderDetail({
      payment_method: 'online',
      payment_status: 'paid',
      payments: [{ ...pendingOnlineOrder().payments[0]!, status: 'captured', client_payload: {} }],
    })
    let order = pendingOnlineOrder()
    const api = mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: () => order }),
      post: { '/payments/pay-mock-1/verify/': () => ((order = paid), paid) },
    })
    const { user, router } = renderRoute(`/orders/${NUMBER}/pay`)
    expect(await screen.findByText(/No real money is charged/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /simulate success/ }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/payments/pay-mock-1/verify/', {
        payload: { mock_signature: 'sig-1', mock_outcome: 'success' },
      }),
    )
    await waitFor(() => expect(currentUrl(router)).toBe(`/order-confirmation/${NUMBER}`))
    expect(await screen.findByText('Paid')).toBeInTheDocument()
  })

  it('failed mock payment explains nothing was charged and offers a retry', async () => {
    signIn()
    const failed = pendingOnlineOrder({
      payment_status: 'failed',
      can_retry_payment: true,
      payments: [{ ...pendingOnlineOrder().payments[0]!, status: 'failed', failure_reason: 'Mock payment declined.', client_payload: {} }],
    })
    const api = mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: pendingOnlineOrder() }),
      post: {
        '/payments/pay-mock-1/verify/': failed,
        [`/orders/${NUMBER}/retry-payment/`]: pendingOnlineOrder(),
      },
    })
    const { user } = renderRoute(`/orders/${NUMBER}/pay`)
    await user.click(await screen.findByRole('button', { name: 'Simulate failed payment' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Payment failed')
    expect(alert).toHaveTextContent('No money was taken')
    await user.click(screen.getByRole('button', { name: 'Try payment again' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/orders/${NUMBER}/retry-payment/`))
    expect(await screen.findByRole('button', { name: /simulate success/ })).toBeInTheDocument()
  })

  it('cancelled mock payment keeps the order and offers pay again or cancel order', async () => {
    signIn()
    const cancelledAttempt = pendingOnlineOrder({
      can_retry_payment: true,
      payments: [{ ...pendingOnlineOrder().payments[0]!, status: 'cancelled', client_payload: {} }],
    })
    mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: pendingOnlineOrder() }),
      post: { '/payments/pay-mock-1/verify/': cancelledAttempt },
    })
    const { user } = renderRoute(`/orders/${NUMBER}/pay`)
    await user.click(await screen.findByRole('button', { name: 'Cancel payment' }))
    expect(await screen.findByText('Payment cancelled')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try payment again' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel order' })).toBeInTheDocument()
  })
})

describe('order history and detail', () => {
  it('lists orders newest first with status, payment and totals, and paginates', async () => {
    signIn()
    const summary = {
      order_number: NUMBER,
      status: 'confirmed',
      payment_method: 'cod',
      payment_status: 'pending',
      grand_total: '800.00',
      item_count: 2,
      item_names: ['FR PVC Insulated Copper Wire'],
      image: null,
      estimated_delivery_at: '2026-09-24T10:38:00Z',
      delivery_message: '⚡ Delivery in 31 minutes (by about 4:08 PM)',
      delivery: orderDelivery(),
      created_at: '2026-09-24T10:00:00Z',
    }
    const api = mockApi({
      get: baseGet({ '/orders/': { count: 12, next: 'x', previous: null, results: [summary] } }),
    })
    const { user } = renderRoute('/account/orders')
    const link = await screen.findByRole('link', { name: new RegExp(NUMBER) })
    expect(link).toHaveAttribute('href', `/account/orders/${NUMBER}`)
    expect(within(link).getByText('Confirmed')).toBeInTheDocument()
    expect(within(link).getByText('Pay on delivery')).toBeInTheDocument()
    expect(within(link).getByText('₹800')).toBeInTheDocument()
    expect(within(link).getByText('⚡ Delivery in 31 minutes (by about 4:08 PM)')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Page 2' }))
    await waitFor(() =>
      expect(api.get).toHaveBeenLastCalledWith('/orders/', { params: { page: 2, page_size: 10 } }),
    )
  })

  it('shows an empty state when there are no orders', async () => {
    signIn()
    mockApi({ get: baseGet({ '/orders/': { count: 0, next: null, previous: null, results: [] } }) })
    renderRoute('/account/orders')
    expect(await screen.findByText('No orders yet')).toBeInTheDocument()
  })

  it('order detail shows items, price snapshot, address, payment and a timeline of real statuses', async () => {
    signIn()
    const packed = orderDetail({
      status: 'packed',
      can_cancel: false,
      status_history: [
        ...orderDetail().status_history,
        { from_status: 'confirmed', to_status: 'processing', note: '', created_at: '2026-09-24T10:05:00Z' },
        { from_status: 'processing', to_status: 'packed', note: '', created_at: '2026-09-24T10:20:00Z' },
      ],
    })
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: packed }) })
    renderRoute(`/account/orders/${NUMBER}`)
    expect(await screen.findByRole('heading', { name: `Order ${NUMBER}` })).toBeInTheDocument()
    expect(screen.getByText(/SKU DEMO-WIRE-15-10 · Qty 2 × ₹400/)).toBeInTheDocument()
    expect(screen.getByText('12 MG Road, Kothrud, Pune 411038')).toBeInTheDocument()

    const timeline = screen.getByRole('list', { name: 'Order progress' })
    const steps = within(timeline).getAllByRole('listitem').map((li) => li.textContent)
    expect(steps[0]).toMatch(/Confirmed.*completed/)
    expect(steps[2]).toMatch(/Packed.*Current/)
    expect(steps.at(-1)).toMatch(/Delivered.*upcoming/)
    expect(within(timeline).queryByText('Cancelled')).not.toBeInTheDocument()

    expect(screen.queryByRole('button', { name: 'Cancel order' })).not.toBeInTheDocument()
    expect(screen.getByText(/can’t be cancelled online/)).toBeInTheDocument()
  })

  it('customer cancels with a reason; the server result replaces the page state', async () => {
    signIn()
    const cancelled = orderDetail({
      status: 'cancelled',
      can_cancel: false,
      cancellation_reason: 'Ordered by mistake',
      cancelled_at: '2026-09-24T11:00:00Z',
      delivery_message: '',
      status_history: [
        ...orderDetail().status_history,
        { from_status: 'confirmed', to_status: 'cancelled', note: 'Ordered by mistake', created_at: '2026-09-24T11:00:00Z' },
      ],
    })
    const api = mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: orderDetail() }),
      post: { [`/orders/${NUMBER}/cancel/`]: cancelled },
    })
    const { user } = renderRoute(`/account/orders/${NUMBER}`)
    await user.click(await screen.findByRole('button', { name: 'Cancel order' }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel this order?' })
    expect(within(dialog).getByText(/Nothing has been charged/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Cancel order' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Please choose a reason.')
    await user.click(within(dialog).getByRole('radio', { name: 'Ordered by mistake' }))
    await user.click(within(dialog).getByRole('button', { name: 'Cancel order' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/orders/${NUMBER}/cancel/`, { reason: 'Ordered by mistake' }))
    expect(await screen.findByText(/Cancelled on .* — Ordered by mistake/)).toBeInTheDocument()
    const timeline = screen.getByRole('list', { name: 'Order progress' })
    expect(within(timeline).getByText('Cancelled')).toBeInTheDocument()
    expect(within(timeline).queryByText('Delivered')).not.toBeInTheDocument()
  })

  it('a paid order being cancelled mentions the refund; refund status shows afterwards', async () => {
    signIn()
    const paid = orderDetail({ payment_method: 'online', payment_status: 'paid' })
    mockApi({
      get: baseGet({
        [`/orders/${NUMBER}/`]: {
          ...paid,
          status: 'cancelled',
          can_cancel: false,
          refunds: [
            {
              public_id: 'r1',
              amount: '800.00',
              status: 'pending',
              reason: 'Order cancelled',
              manual: false,
              created_at: '',
              processed_at: null,
            },
          ],
        },
      }),
    })
    renderRoute(`/account/orders/${NUMBER}`)
    expect(await screen.findByText(/Refund of ₹800 requested — it is being processed to your original payment/)).toBeInTheDocument()
  })

  it('another customer’s order number shows not found', async () => {
    signIn()
    mockApi({ get: baseGet({ '/orders/OD-OTHER/': httpError(404, 'Not found.') }) })
    renderRoute('/account/orders/OD-OTHER')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('confirmation page shows order number, status, items, total and actions', async () => {
    signIn()
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: orderDetail() }) })
    renderRoute(`/order-confirmation/${NUMBER}`)
    expect(await screen.findByRole('heading', { name: 'Thank you! Your order is placed.' })).toBeInTheDocument()
    expect(screen.getByText(NUMBER)).toBeInTheDocument()
    expect(screen.getAllByText('Confirmed')).not.toHaveLength(0)
    expect(screen.getByText('Pay on delivery')).toBeInTheDocument()
    expect(screen.getByText(/Total ₹800/)).toBeInTheDocument()
    expect(screen.getByText('⚡ Delivery in 31 minutes (by about 4:08 PM)')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View order' })).toHaveAttribute('href', `/account/orders/${NUMBER}`)
    expect(screen.getByRole('link', { name: 'Continue shopping' })).toHaveAttribute('href', '/products')
  })

  it('confirmation and order detail show the delivery promise: store, type, estimate, window, preparation', async () => {
    signIn()
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: orderDetail() }) })
    const confirmation = renderRoute(`/order-confirmation/${NUMBER}`)
    let card = (await screen.findByRole('heading', { name: 'Delivery' })).closest('section')!
    expect(card).toHaveTextContent('Fast delivery')
    expect(card).toHaveTextContent('Estimated delivery: 31 minutes')
    expect(card).toHaveTextContent('Delivery statusConfirmed')
    expect(card).toHaveTextContent('Fast deliveryEligible')
    expect(card).toHaveTextContent('Delivery window4:08 PM – 4:23 PM')
    expect(card).toHaveTextContent('Preparation timeAbout 10 minutes (ready by 3:40 PM)')
    expect(card).toHaveTextContent('Fulfilled byDemo Store, Kothrud')
    expect(card).not.toHaveTextContent(/60 min/)
    confirmation.unmount()

    renderRoute(`/account/orders/${NUMBER}`)
    card = (await screen.findByRole('heading', { name: 'Delivery' })).closest('section')!
    expect(card).toHaveTextContent('Estimated delivery: 31 minutes')
    expect(card).toHaveTextContent('Fulfilled byDemo Store, Kothrud')
  })

  it('standard delivery shows its window; a delivered order shows no countdown', async () => {
    signIn()
    const standard = orderDetail({
      delivery_message: '🚚 Standard delivery · Tomorrow, 10:00 AM – 12:00 PM',
      delivery: orderDelivery({
        type: 'standard',
        type_label: 'Standard delivery',
        fast: false,
        eta_minutes: 1260,
        minutes_left: 1250,
        window_start: '2026-09-25T04:30:00Z',
        window_end: '2026-09-25T06:30:00Z',
        label: 'Tomorrow, 10:00 AM – 12:00 PM',
      }),
    })
    let order = standard
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: () => order }) })
    const first = renderRoute(`/account/orders/${NUMBER}`)
    let card = (await screen.findByRole('heading', { name: 'Delivery' })).closest('section')!
    expect(card).toHaveTextContent('Standard delivery')
    expect(card).toHaveTextContent('Estimated delivery: Tomorrow, 10:00 AM – 12:00 PM')
    expect(card).toHaveTextContent('Fast deliveryNot available for this order')
    first.unmount()

    order = { ...standard, status: 'delivered', delivery_message: 'Delivered', can_cancel: false }
    renderRoute(`/account/orders/${NUMBER}`)
    card = (await screen.findByRole('heading', { name: 'Delivery' })).closest('section')!
    expect(card).toHaveTextContent('Delivery statusDelivered')
    expect(card).not.toHaveTextContent('Estimated delivery')
    expect(card).not.toHaveTextContent('Delivery window')
  })

  it('an order shipped from two stores lists each store with its items', async () => {
    signIn()
    const base = orderDetail()
    const split = orderDetail({
      items: [base.items[0]!, { ...base.items[0]!, id: 2, product_name: 'PTFE Tape', sku: 'DEMO-TAPE' }],
      shipments: [
        base.shipments[0]!,
        { ...base.shipments[0]!, sequence: 2, store_name: 'Demo Dark Store', store_area: 'Baner', delivery_type: 'standard', item_ids: [2] },
      ],
    })
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: split }) })
    renderRoute(`/account/orders/${NUMBER}`)
    const card = (await screen.findByRole('heading', { name: 'Delivery' })).closest('section')!
    expect(card).toHaveTextContent('This order ships from 2 stores')
    const stores = within(card).getAllByRole('listitem')
    expect(stores[0]).toHaveTextContent('Demo Store, Kothrud')
    expect(stores[0]).toHaveTextContent('FR PVC Insulated Copper Wire')
    expect(stores[1]).toHaveTextContent('Demo Dark Store, Baner')
    expect(stores[1]).toHaveTextContent('PTFE Tape')
    expect(stores[1]).toHaveTextContent('Standard delivery')
  })

  it('orders placed before delivery estimates existed keep the older wording', async () => {
    signIn()
    const old = orderDetail({
      delivery: NO_ESTIMATE,
      shipments: [],
      eta_minutes: null,
      estimated_delivery_at: null,
      delivery_message: 'Delivery estimate will be confirmed after your order is placed.',
    })
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: old }) })
    renderRoute(`/account/orders/${NUMBER}`)
    const card = (await screen.findByRole('heading', { name: 'Delivery' })).closest('section')!
    expect(card).toHaveTextContent('Delivery estimate will be confirmed after your order is placed.')
    expect(card).not.toHaveTextContent('Estimated delivery:')
    expect(card).toHaveTextContent('Fulfilled byDemo Store')
  })

  it('addresses page lists, sets default and deletes addresses', async () => {
    signIn()
    const second = address({ id: 32, name: 'Site', is_default: false })
    const api = mockApi({
      get: baseGet({ '/addresses/': [address(), second] }),
      post: { '/addresses/32/set-default/': second },
      delete: { '/addresses/32/': null },
    })
    const { user } = renderRoute('/account/addresses')
    await user.click(await screen.findByRole('button', { name: /Set as default/ }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/addresses/32/set-default/'))
    window.confirm = () => true
    await user.click(screen.getByRole('button', { name: /Delete\s*address for Site/ }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/addresses/32/'))
  })
})
