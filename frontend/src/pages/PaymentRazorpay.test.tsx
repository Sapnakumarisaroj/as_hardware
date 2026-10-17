import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { OrderDetail, OrderPayment } from '@/features/orders/types'
import { customer, orderDetail, pendingOnlineOrder } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const NUMBER = 'OD260924ABCDEF'
const VERIFY = '/payments/pay-rzp-1/verify/'

const razorpayAttempt: OrderPayment = {
  public_id: 'pay-rzp-1',
  provider: 'razorpay',
  method: 'unknown',
  amount: '800.00',
  currency: 'INR',
  status: 'created',
  failure_reason: '',
  captured_at: null,
  created_at: '2026-09-24T10:00:00Z',
  client_payload: {
    razorpay: true,
    key_id: 'rzp_test_public',
    order_id: 'order_Rzp1',
    amount: 80000,
    currency: 'INR',
    name: 'BoltRun',
    description: `Order ${NUMBER}`,
    prefill: { name: 'Asha', email: 'asha@example.com' },
    test_mode: true,
  },
}

function waiting(overrides: Partial<OrderDetail> = {}) {
  return pendingOnlineOrder({ payments: [razorpayAttempt], ...overrides })
}

function baseGet(extra: Record<string, unknown> = {}) {
  return { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/cart/': { items: [] }, ...extra }
}

/** A stand-in for Razorpay Checkout that records its options and lets the test drive it. */
function installCheckout() {
  const opened: { options: Record<string, unknown>; failed?: (r: { error?: { description?: string } }) => void }[] = []
  class FakeRazorpay {
    entry: (typeof opened)[number]
    constructor(options: Record<string, unknown>) {
      this.entry = { options }
      opened.push(this.entry)
    }
    on(_event: string, handler: (r: { error?: { description?: string } }) => void) {
      this.entry.failed = handler
    }
    open() {}
  }
  window.Razorpay = FakeRazorpay as unknown as NonNullable<typeof window.Razorpay>
  return opened
}

beforeEach(() => signIn())
afterEach(() => {
  delete window.Razorpay
})

describe('Razorpay checkout', () => {
  it('opens Checkout with public data only and lets the server verify the result', async () => {
    const opened = installCheckout()
    let order = waiting()
    const paid = orderDetail({ payment_method: 'online', payment_status: 'paid' })
    const api = mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: () => order }),
      post: { [VERIFY]: () => ((order = paid), paid) },
    })
    const { user, router } = renderRoute(`/orders/${NUMBER}/pay`)
    expect(await screen.findByText(/Razorpay test mode/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Pay ₹800' }))

    await waitFor(() => expect(opened).toHaveLength(1))
    const { options } = opened[0]!
    expect(options).toMatchObject({ key: 'rzp_test_public', order_id: 'order_Rzp1', amount: 80000, currency: 'INR' })
    expect(JSON.stringify(options)).not.toMatch(/secret/i)

    const response = { razorpay_payment_id: 'pay_X', razorpay_order_id: 'order_Rzp1', razorpay_signature: 'sig' }
    ;(options.handler as (r: typeof response) => void)(response)
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(VERIFY, { payload: response }))
    await waitFor(() => expect(currentUrl(router)).toBe(`/order-confirmation/${NUMBER}`))
  })

  it('closing the window reports a cancellation, and in-window failures are shown', async () => {
    const opened = installCheckout()
    const cancelled = waiting({
      can_retry_payment: true,
      payments: [{ ...razorpayAttempt, status: 'cancelled', client_payload: {} }],
    })
    const api = mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: waiting() }), post: { [VERIFY]: cancelled } })
    const { user } = renderRoute(`/orders/${NUMBER}/pay`)
    await user.click(await screen.findByRole('button', { name: 'Pay ₹800' }))
    await waitFor(() => expect(opened).toHaveLength(1))

    opened[0]!.failed!({ error: { description: 'Your bank declined the payment.' } })
    expect(await screen.findByText(/Your bank declined the payment\./)).toBeInTheDocument()

    const modal = opened[0]!.options.modal as { ondismiss: () => void }
    modal.ondismiss()
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(VERIFY, { payload: { cancelled: true } }))
    expect(await screen.findByText('Payment cancelled')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try payment again' })).toBeInTheDocument()
  })

  it('waits for the server when the bank is still processing', async () => {
    const opened = installCheckout()
    let order = waiting()
    mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: () => order }),
      post: { [VERIFY]: () => waiting() }, // genuine, not final: attempt stays "created"
    })
    const { user, router } = renderRoute(`/orders/${NUMBER}/pay`)
    await user.click(await screen.findByRole('button', { name: 'Pay ₹800' }))
    await waitFor(() => expect(opened).toHaveLength(1))
    ;(opened[0]!.options.handler as (r: object) => void)({ razorpay_payment_id: 'pay_X' })

    expect(await screen.findByText('Confirming your payment…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pay ₹800' })).not.toBeInTheDocument() // no double payment
    order = orderDetail({ payment_method: 'online', payment_status: 'paid' }) // webhook confirmed it
    await waitFor(() => expect(currentUrl(router)).toBe(`/order-confirmation/${NUMBER}`), { timeout: 6000 })
  })
})

describe('Razorpay checkout when verification fails', () => {
  it('never offers a second payment after Razorpay reported success', async () => {
    const opened = installCheckout()
    let order = waiting()
    mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: () => order }),
      post: { [VERIFY]: httpError(503, 'Network Error', 'network_error') },
    })
    const { user, router } = renderRoute(`/orders/${NUMBER}/pay`)
    await user.click(await screen.findByRole('button', { name: 'Pay ₹800' }))
    await waitFor(() => expect(opened).toHaveLength(1))
    ;(opened[0]!.options.handler as (r: object) => void)({ razorpay_payment_id: 'pay_X' })

    expect(await screen.findByText('Confirming your payment…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pay ₹800' })).not.toBeInTheDocument()
    order = orderDetail({ payment_method: 'online', payment_status: 'paid' }) // the webhook confirmed it
    await waitFor(() => expect(currentUrl(router)).toBe(`/order-confirmation/${NUMBER}`), { timeout: 6000 })
  })

  it('a failed verification of a cancellation leaves the Pay button', async () => {
    const opened = installCheckout()
    mockApi({
      get: baseGet({ [`/orders/${NUMBER}/`]: waiting() }),
      post: { [VERIFY]: httpError(503, 'Network Error', 'network_error') },
    })
    const { user } = renderRoute(`/orders/${NUMBER}/pay`)
    await user.click(await screen.findByRole('button', { name: 'Pay ₹800' }))
    await waitFor(() => expect(opened).toHaveLength(1))
    ;(opened[0]!.options.modal as { ondismiss: () => void }).ondismiss()
    expect(await screen.findByRole('button', { name: 'Pay ₹800' })).toBeInTheDocument()
    expect(screen.queryByText('Confirming your payment…')).not.toBeInTheDocument()
  })

  it('names the UPI apps and explains where they open', async () => {
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: waiting() }) })
    renderRoute(`/orders/${NUMBER}/pay`)
    expect(await screen.findByText(/Google Pay, PhonePe, Paytm/)).toBeInTheDocument()
    expect(screen.getByText(/UPI apps open directly on Android phones in Chrome/)).toBeInTheDocument()
  })
})

describe('refund status on the order page', () => {
  it('explains gateway, store (COD) and delayed refunds', async () => {
    const refund = { reason: 'Order cancelled', created_at: '2026-09-24T11:00:00Z' }
    mockApi({
      get: baseGet({
        [`/orders/${NUMBER}/`]: orderDetail({
          status: 'cancelled',
          can_cancel: false,
          refunds: [
            { ...refund, public_id: 'r1', amount: '800.00', status: 'processed', manual: false, processed_at: '2026-09-25T10:00:00Z' },
            { ...refund, public_id: 'r2', amount: '140.00', status: 'pending', manual: true, processed_at: null },
            { ...refund, public_id: 'r3', amount: '60.00', status: 'failed', manual: false, processed_at: null },
          ],
        }),
      }),
    })
    renderRoute(`/account/orders/${NUMBER}`)
    expect(await screen.findByText(/Refunded ₹800 on .* to your original payment method/)).toBeInTheDocument()
    expect(screen.getByText(/₹140 requested — the store will pay it back/)).toBeInTheDocument()
    expect(screen.getByText(/₹60 is delayed/)).toBeInTheDocument()
  })
})

describe('mock gateway still works', () => {
  it('keeps the development mock buttons for mock attempts', async () => {
    const spy = vi.fn()
    mockApi({ get: baseGet({ [`/orders/${NUMBER}/`]: pendingOnlineOrder() }), post: { '/payments/pay-mock-1/verify/': spy } })
    renderRoute(`/orders/${NUMBER}/pay`)
    expect(await screen.findByRole('button', { name: /simulate success/ })).toBeInTheDocument()
    expect(screen.queryByText(/Pay securely/)).not.toBeInTheDocument()
  })
})
