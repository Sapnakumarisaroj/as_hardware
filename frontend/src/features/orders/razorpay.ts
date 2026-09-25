/**
 * Razorpay Checkout (https://checkout.razorpay.com/v1/checkout.js), loaded only on the payment page.
 *
 * The browser gets the *public* key id and the gateway order id from the server's `client_payload`.
 * Whatever Checkout reports is sent to `/payments/{id}/verify/`, where the server checks the signature
 * and asks Razorpay; the page never decides that a payment succeeded.
 */

export const RAZORPAY_SCRIPT = 'https://checkout.razorpay.com/v1/checkout.js'

export interface RazorpayPayload {
  razorpay?: boolean
  key_id?: string
  order_id?: string
  amount?: number
  currency?: string
  name?: string
  description?: string
  prefill?: { name?: string; email?: string; contact?: string }
  test_mode?: boolean
}

export interface RazorpaySuccess {
  razorpay_payment_id: string
  razorpay_order_id: string
  razorpay_signature: string
}

interface RazorpayInstance {
  open: () => void
  on: (event: 'payment.failed', handler: (response: { error?: { description?: string } }) => void) => void
}

type RazorpayConstructor = new (options: Record<string, unknown>) => RazorpayInstance

declare global {
  interface Window {
    Razorpay?: RazorpayConstructor
  }
}

let loading: Promise<RazorpayConstructor> | null = null

export function loadRazorpay(): Promise<RazorpayConstructor> {
  if (window.Razorpay) return Promise.resolve(window.Razorpay)
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = RAZORPAY_SCRIPT
    script.async = true
    script.onload = () => (window.Razorpay ? resolve(window.Razorpay) : reject(new Error('Razorpay did not load')))
    script.onerror = () => {
      loading = null
      reject(new Error('Could not load the payment window. Check your connection and try again.'))
    }
    document.body.appendChild(script)
  })
  return loading
}

export interface CheckoutHandlers {
  onSuccess: (response: RazorpaySuccess) => void
  onDismiss: () => void
  /** A failed attempt inside the window; Razorpay lets the customer try again there. */
  onFailure: (message: string) => void
}

export async function openRazorpayCheckout(payload: RazorpayPayload, handlers: CheckoutHandlers) {
  const Razorpay = await loadRazorpay()
  const checkout = new Razorpay({
    key: payload.key_id,
    order_id: payload.order_id,
    amount: payload.amount,
    currency: payload.currency ?? 'INR',
    name: payload.name,
    description: payload.description,
    prefill: payload.prefill ?? {},
    theme: { color: '#d97706' },
    handler: handlers.onSuccess,
    modal: { ondismiss: handlers.onDismiss, confirm_close: true },
  })
  checkout.on('payment.failed', (response) => handlers.onFailure(response.error?.description ?? 'Payment failed.'))
  checkout.open()
}
