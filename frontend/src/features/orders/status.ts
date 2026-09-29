import type { OrderDetail, OrderStatus, PaymentStatus } from './types'

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  pending: 'Awaiting payment',
  confirmed: 'Confirmed',
  processing: 'Processing',
  packed: 'Packed',
  assigned: 'Assigned to delivery partner',
  picked_up: 'Picked up',
  out_for_delivery: 'Out for delivery',
  delivered: 'Delivered',
  delivery_failed: 'Delivery attempt failed',
  cancelled: 'Cancelled',
  return_requested: 'Return requested',
  returned: 'Returned',
}

export const PAYMENT_STATUS_LABELS: Record<PaymentStatus, string> = {
  pending: 'Payment pending',
  paid: 'Paid',
  failed: 'Payment failed',
  refunded: 'Refunded',
  partially_refunded: 'Partially refunded',
}

/** COD orders are never "awaiting payment" — they pay at the door. */
export function orderStatusLabel(order: { status: OrderStatus; payment_method: string }): string {
  if (order.status === 'pending' && order.payment_method === 'cod') return 'Placed'
  return ORDER_STATUS_LABELS[order.status] ?? order.status
}

export function paymentStatusLabel(order: { payment_status: PaymentStatus; payment_method: string; status: OrderStatus }): string {
  if (order.payment_method === 'cod' && order.payment_status === 'pending') {
    return order.status === 'cancelled' ? 'Not charged' : 'Pay on delivery'
  }
  return PAYMENT_STATUS_LABELS[order.payment_status] ?? order.payment_status
}

export type Tone = 'neutral' | 'progress' | 'success' | 'danger' | 'warning'

export function orderTone(status: OrderStatus): Tone {
  if (status === 'delivered') return 'success'
  if (status === 'cancelled' || status === 'returned') return 'danger'
  if (status === 'pending' || status === 'return_requested' || status === 'delivery_failed') return 'warning'
  return 'progress'
}

/** The fulfilment path shown as a timeline (Picked up is folded into "Out for delivery"). */
export const TIMELINE: OrderStatus[] = ['confirmed', 'processing', 'packed', 'assigned', 'out_for_delivery', 'delivered']

export interface TimelineStep {
  status: OrderStatus
  label: string
  at: string | null
  state: 'done' | 'current' | 'upcoming'
}

/**
 * Timeline steps that exist for this order: steps it has actually reached (with their real
 * timestamps from the status history), followed by the remaining normal steps as "upcoming".
 * Cancelled/returned orders show only what really happened.
 */
export function buildTimeline(order: Pick<OrderDetail, 'status' | 'status_history'>): TimelineStep[] {
  // After a failed delivery the order goes out again: only what happened since then counts as
  // progress of the current attempt. The failed attempt itself stays visible.
  const history = order.status_history
  const lastFailure = history.map((entry) => entry.to_status).lastIndexOf('delivery_failed')
  const failedAt = lastFailure >= 0 ? history[lastFailure]!.created_at : null
  const reached = new Map<string, string>()
  history.forEach((entry, index) => {
    const beforePacking = ['pending', 'confirmed', 'processing', 'packed'].includes(entry.to_status)
    if (index > lastFailure || beforePacking) reached.set(entry.to_status, entry.created_at)
  })
  const terminal = ['cancelled', 'returned', 'return_requested', 'delivery_failed'].includes(order.status)

  const steps: TimelineStep[] = []
  for (const status of TIMELINE) {
    const at = reached.get(status) ?? (status === 'out_for_delivery' ? (reached.get('picked_up') ?? null) : null)
    if (at) steps.push({ status, label: ORDER_STATUS_LABELS[status], at, state: 'done' })
    else if (!terminal) steps.push({ status, label: ORDER_STATUS_LABELS[status], at: null, state: 'upcoming' })
  }
  if (failedAt) {
    const failure: TimelineStep = {
      status: 'delivery_failed',
      label: ORDER_STATUS_LABELS.delivery_failed,
      at: failedAt,
      state: 'done',
    }
    // In time order: after the steps reached before it, before those of the new attempt.
    const position = steps.findIndex((step) => step.state === 'upcoming' || (step.at !== null && step.at > failedAt))
    steps.splice(position < 0 ? steps.length : position, 0, failure)
  }
  for (const status of ['cancelled', 'return_requested', 'returned'] as const) {
    const at = reached.get(status)
    if (at) steps.push({ status, label: ORDER_STATUS_LABELS[status], at, state: 'done' })
  }
  // The latest reached step is "current" unless the order is finished.
  const lastDone = steps.map((s) => s.state).lastIndexOf('done')
  if (lastDone >= 0 && !['delivered', 'cancelled', 'returned'].includes(order.status)) {
    steps[lastDone] = { ...steps[lastDone]!, state: 'current' }
  }
  return steps
}
