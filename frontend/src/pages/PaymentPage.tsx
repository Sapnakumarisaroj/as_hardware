import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router'

import { ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { useOrder, useRetryPayment, useVerifyPayment, type MockOutcome } from '@/features/orders/api'
import { CancelOrderDialog } from '@/features/orders/components'
import { openRazorpayCheckout } from '@/features/orders/razorpay'
import type { OrderDetail } from '@/features/orders/types'
import { ApiError, isNotFound } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

const CONFIRM_POLL_MS = 3000
const CONFIRM_GIVE_UP_MS = 120_000

/**
 * Online payment step. The gateway widget (Razorpay Checkout, or the development mock) only
 * *reports* an outcome; the backend verifies it with the gateway and decides the payment and
 * order status. If the gateway is still processing, the page waits for the server to confirm.
 */
export function PaymentPage() {
  usePageMeta('Payment')
  const { number = '' } = useParams()
  const { status } = useAuth()
  const [confirming, setConfirming] = useState<'waiting' | 'slow' | null>(null)
  const order = useOrder(number, confirming === 'waiting' ? CONFIRM_POLL_MS : false)
  const verify = useVerifyPayment()
  const retry = useRetryPayment(number)
  const navigate = useNavigate()
  const toast = useToast()
  const [result, setResult] = useState<'failed' | 'cancelled' | null>(null)
  const [gatewayMessage, setGatewayMessage] = useState('')
  const [opening, setOpening] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  useEffect(() => {
    if (confirming !== 'waiting') return
    const timer = window.setTimeout(() => setConfirming('slow'), CONFIRM_GIVE_UP_MS)
    return () => window.clearTimeout(timer)
  }, [confirming])

  if (status === 'loading') return <PageSpinner />
  if (status === 'anonymous') {
    return (
      <div className="container-page py-10">
        <SignInPrompt message="Sign in to complete your payment." next={`/orders/${number}/pay`} />
      </div>
    )
  }
  if (order.isPending) return <PageSpinner label="Loading payment…" />
  if (order.isError) {
    if (isNotFound(order.error)) return <NotFoundPage />
    return (
      <div className="container-page py-10">
        <ErrorState error={order.error} onRetry={() => order.refetch()} title="Couldn’t load this order" />
      </div>
    )
  }

  const data = order.data
  if (data.payment_status === 'paid' || data.payment_method !== 'online') {
    return <Navigate to={`/order-confirmation/${data.order_number}`} replace />
  }
  if (data.status === 'cancelled') return <Navigate to={`/account/orders/${data.order_number}`} replace />

  const attempt = data.payments.find((p) => p.status === 'created')
  const lastClosed = data.payments.find((p) => p.status === 'failed' || p.status === 'cancelled')
  const outcome = result ?? (lastClosed?.status === 'failed' ? 'failed' : lastClosed?.status === 'cancelled' ? 'cancelled' : null)
  const busy = verify.isPending || opening

  /** `paidAtGateway`: the gateway said the customer paid. If we can't verify that now (network, gateway
   * hiccup), wait for the server (webhook / reconciliation) instead of offering a second payment. */
  function report(payload: Record<string, string | boolean>, fallback: 'failed' | 'cancelled', paidAtGateway = false) {
    if (!attempt) return
    verify.mutate(
      { paymentId: attempt.public_id, payload },
      {
        onSuccess: (updated: OrderDetail) => {
          if (updated.payment_status === 'paid') {
            navigate(`/order-confirmation/${updated.order_number}`, { replace: true })
          } else if (updated.payments.some((p) => p.public_id === attempt.public_id && p.status === 'created')) {
            setConfirming('waiting') // genuine but not final yet: the server will confirm it
          } else {
            setResult(fallback)
          }
        },
        onError: (error) => {
          toast.show(error instanceof ApiError ? error.message : 'Could not verify the payment.', { tone: 'error' })
          if (paidAtGateway) setConfirming('waiting')
        },
      },
    )
  }

  async function payWithRazorpay() {
    if (!attempt) return
    setOpening(true)
    setGatewayMessage('')
    try {
      await openRazorpayCheckout(attempt.client_payload, {
        onSuccess: (response) => report({ ...response }, 'failed', true),
        onDismiss: () => report({ cancelled: true }, 'cancelled'),
        onFailure: (message) => setGatewayMessage(message),
      })
    } catch (error) {
      toast.show(error instanceof Error ? error.message : 'Could not open the payment window.', { tone: 'error' })
    } finally {
      setOpening(false)
    }
  }

  function payMock(choice: MockOutcome) {
    if (!attempt?.client_payload.mock_signature) return
    report({ mock_signature: attempt.client_payload.mock_signature, mock_outcome: choice }, choice === 'cancelled' ? 'cancelled' : 'failed')
  }

  return (
    <div className="container-page flex justify-center py-8">
      <div className="w-full max-w-md space-y-4">
        <div className="rounded-xl bg-white p-6 text-center shadow-sm ring-1 ring-steel-200">
          <p className="text-sm text-ink-600">Order {data.order_number}</p>
          <h1 className="mt-1 text-3xl font-bold">{formatPrice(data.grand_total)}</h1>
          <p className="mt-1 text-sm text-ink-600">Amount payable</p>
        </div>

        {confirming && (
          <div role="status" className="rounded-lg bg-amber-100 p-4 text-sm text-ink-900">
            {confirming === 'waiting' ? (
              <>
                <p className="font-semibold">Confirming your payment…</p>
                <p>Your bank is still processing it. This page updates by itself — please don’t pay again.</p>
              </>
            ) : (
              <>
                <p className="font-semibold">Still waiting for your bank</p>
                <p>
                  If money was taken, your order is confirmed automatically and you’ll get a notification. If not, it is
                  released within a few minutes and nothing is charged.
                </p>
              </>
            )}
          </div>
        )}
        {outcome === 'failed' && !attempt && (
          <div role="alert" className="rounded-lg bg-danger-600/10 p-4 text-sm text-danger-600">
            <p className="font-semibold">Payment failed</p>
            <p>No money was taken. {lastClosed?.failure_reason && `(${lastClosed.failure_reason})`} You can try again.</p>
          </div>
        )}
        {outcome === 'cancelled' && !attempt && (
          <div role="alert" className="rounded-lg bg-amber-100 p-4 text-sm text-ink-900">
            <p className="font-semibold">Payment cancelled</p>
            <p>Your order is saved and waiting for payment. You can pay now or cancel the order.</p>
          </div>
        )}
        {gatewayMessage && attempt && (
          <p role="alert" className="rounded-lg bg-danger-600/10 p-3 text-sm text-danger-600">
            {gatewayMessage} You can try another method in the payment window.
          </p>
        )}

        {attempt && !confirming ? (
          attempt.client_payload.razorpay ? (
            <section aria-labelledby="pay-heading" className="rounded-xl bg-white p-5 ring-1 ring-steel-200">
              <h2 id="pay-heading" className="font-bold">
                Pay securely
              </h2>
              <p className="mt-1 text-sm text-ink-600">
                UPI (Google Pay, PhonePe, Paytm and other UPI apps), cards, net banking and wallets via Razorpay.
              </p>
              <p className="mt-1 text-xs text-ink-600">
                UPI apps open directly on Android phones in Chrome. On other devices, choose UPI and pay with your UPI
                ID. If a method isn’t listed, it isn’t available for this payment. Please pick another one.
              </p>
              {attempt.client_payload.test_mode && (
                <p className="mt-2 rounded-md bg-amber-100 px-3 py-2 text-xs text-ink-900">
                  Razorpay test mode: use test cards/UPI only. No real money is charged.
                </p>
              )}
              <button type="button" onClick={() => void payWithRazorpay()} disabled={busy} className="btn-primary mt-4 w-full py-3">
                {opening ? 'Opening…' : `Pay ${formatPrice(attempt.amount)}`}
              </button>
            </section>
          ) : attempt.client_payload.mock ? (
            <section aria-labelledby="mock-heading" className="rounded-xl bg-white p-5 ring-1 ring-steel-200">
              <h2 id="mock-heading" className="font-bold">
                Mock payment gateway
              </h2>
              <p className="mt-1 rounded-md bg-amber-100 px-3 py-2 text-xs text-ink-900">
                {attempt.client_payload.notice ?? 'Development mock payment. No real money is charged.'} Choose the outcome to
                test each path.
              </p>
              <div className="mt-4 grid gap-2">
                <button type="button" onClick={() => payMock('success')} disabled={busy} className="btn-primary py-3">
                  Pay {formatPrice(attempt.amount)} (simulate success)
                </button>
                <button type="button" onClick={() => payMock('failed')} disabled={busy} className="btn-secondary py-3">
                  Simulate failed payment
                </button>
                <button type="button" onClick={() => payMock('cancelled')} disabled={busy} className="btn-secondary py-3">
                  Cancel payment
                </button>
              </div>
            </section>
          ) : (
            <p className="rounded-2xl bg-white shadow-(--shadow-card) p-5 text-sm ring-1 ring-steel-200">
              Online payment is not available right now. Please cancel this order and choose cash on delivery.
            </p>
          )
        ) : (
          !attempt && (
            <div className="grid gap-2">
              {data.can_retry_payment && (
                <button
                  type="button"
                  onClick={() => retry.mutate(undefined, { onSuccess: () => setResult(null) })}
                  disabled={retry.isPending}
                  className="btn-primary py-3"
                >
                  {retry.isPending ? 'Starting…' : 'Try payment again'}
                </button>
              )}
              {data.can_cancel && (
                <button type="button" onClick={() => setCancelling(true)} className="btn-secondary py-3">
                  Cancel order
                </button>
              )}
            </div>
          )
        )}
        {verify.isPending && (
          <p role="status" className="text-center text-sm text-ink-600">
            Verifying payment…
          </p>
        )}

        <p className="text-center text-sm">
          <Link to={`/account/orders/${data.order_number}`} className="font-semibold text-amber-700 hover:underline">
            View order details
          </Link>
        </p>
      </div>
      <CancelOrderDialog order={data} open={cancelling} onClose={() => setCancelling(false)} />
    </div>
  )
}
