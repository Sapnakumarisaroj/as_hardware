import { useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router'

import { ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { useOrder, useRetryPayment, useVerifyPayment, type MockOutcome } from '@/features/orders/api'
import { CancelOrderDialog } from '@/features/orders/components'
import { ApiError, isNotFound } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

/**
 * Online payment step. In development the configured gateway is the MockPaymentProvider:
 * the shopper chooses the outcome, and the backend verifies the signed payload and decides
 * the payment/order status. Phase 8 swaps this screen's buttons for the real gateway widget.
 */
export function PaymentPage() {
  usePageMeta('Payment')
  const { number = '' } = useParams()
  const { status } = useAuth()
  const order = useOrder(number)
  const verify = useVerifyPayment()
  const retry = useRetryPayment(number)
  const navigate = useNavigate()
  const toast = useToast()
  const [result, setResult] = useState<'failed' | 'cancelled' | null>(null)
  const [cancelling, setCancelling] = useState(false)

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

  function pay(choice: MockOutcome) {
    if (!attempt?.client_payload.mock_signature) return
    verify.mutate(
      { paymentId: attempt.public_id, payload: { mock_signature: attempt.client_payload.mock_signature, mock_outcome: choice } },
      {
        onSuccess: (updated) => {
          if (updated.payment_status === 'paid') {
            navigate(`/order-confirmation/${updated.order_number}`, { replace: true })
          } else {
            setResult(choice === 'cancelled' ? 'cancelled' : 'failed')
          }
        },
        onError: (error) =>
          toast.show(error instanceof ApiError ? error.message : 'Could not verify the payment.', { tone: 'error' }),
      },
    )
  }

  return (
    <div className="container-page flex justify-center py-8">
      <div className="w-full max-w-md space-y-4">
        <div className="rounded-xl bg-white p-6 text-center shadow-sm ring-1 ring-steel-200">
          <p className="text-sm text-ink-600">Order {data.order_number}</p>
          <h1 className="mt-1 text-3xl font-bold">{formatPrice(data.grand_total)}</h1>
          <p className="mt-1 text-sm text-ink-600">Amount payable</p>
        </div>

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

        {attempt ? (
          attempt.client_payload.mock ? (
            <section aria-labelledby="mock-heading" className="rounded-xl bg-white p-5 ring-1 ring-steel-200">
              <h2 id="mock-heading" className="font-bold">
                Mock payment gateway
              </h2>
              <p className="mt-1 rounded-md bg-amber-100 px-3 py-2 text-xs text-ink-900">
                {attempt.client_payload.notice ?? 'Development mock payment. No real money is charged.'} Choose the outcome to
                test each path.
              </p>
              <div className="mt-4 grid gap-2">
                <button type="button" onClick={() => pay('success')} disabled={verify.isPending} className="btn-primary py-3">
                  Pay {formatPrice(attempt.amount)} (simulate success)
                </button>
                <button type="button" onClick={() => pay('failed')} disabled={verify.isPending} className="btn-secondary py-3">
                  Simulate failed payment
                </button>
                <button type="button" onClick={() => pay('cancelled')} disabled={verify.isPending} className="btn-secondary py-3">
                  Cancel payment
                </button>
              </div>
              {verify.isPending && (
                <p role="status" className="mt-3 text-center text-sm text-ink-600">
                  Verifying payment…
                </p>
              )}
            </section>
          ) : (
            <p className="rounded-lg bg-white p-5 text-sm ring-1 ring-steel-200">
              Online payment is not available yet. Please cancel this order and choose cash on delivery.
            </p>
          )
        ) : (
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
        )}

        <p className="text-center text-sm">
          <Link to={`/account/orders/${data.order_number}`} className="font-semibold text-amber-600 hover:underline">
            View order details
          </Link>
        </p>
      </div>
      <CancelOrderDialog order={data} open={cancelling} onClose={() => setCancelling(false)} />
    </div>
  )
}
