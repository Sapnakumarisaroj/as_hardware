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
  if (status === 'pending' || status === 'return_requested') return 'warning'
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
  const reached = new Map<string, string>()
  for (const entry of order.status_history) reached.set(entry.to_status, entry.created_at)
  const terminal = order.status === 'cancelled' || order.status === 'returned' || order.status === 'return_requested'

  const steps: TimelineStep[] = []
  for (const status of TIMELINE) {
    const at = reached.get(status) ?? (status === 'out_for_delivery' ? (reached.get('picked_up') ?? null) : null)
    if (at) steps.push({ status, label: ORDER_STATUS_LABELS[status], at, state: 'done' })
    else if (!terminal) steps.push({ status, label: ORDER_STATUS_LABELS[status], at: null, state: 'upcoming' })
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
