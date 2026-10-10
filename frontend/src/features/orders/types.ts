/** Order shapes from the API. Money is a decimal string computed by the server. */

import type { OrderDelivery, OrderShipment } from '@/features/delivery/types'

import type { RazorpayPayload } from './razorpay'

export type OrderStatus =
  | 'pending'
  | 'confirmed'
  | 'processing'
  | 'packed'
  | 'assigned'
  | 'picked_up'
  | 'out_for_delivery'
  | 'delivered'
  | 'delivery_failed'
  | 'cancelled'
  | 'return_requested'
  | 'returned'

export type PaymentStatus = 'pending' | 'paid' | 'failed' | 'refunded' | 'partially_refunded'
export type PaymentMethod = 'online' | 'cod'

export interface OrderSummary {
  order_number: string
  status: OrderStatus
  payment_method: PaymentMethod
  payment_status: PaymentStatus
  grand_total: string
  item_count: number
  item_names: string[]
  image: string | null
  estimated_delivery_at: string | null
  delivery_message: string
  /** Fast or standard, the estimate and the window promised for this order. */
  delivery: OrderDelivery
  created_at: string
}

export interface OrderItem {
  id: number
  product: number | null
  product_slug: string | null
  variant: number | null
  product_name: string
  variant_name: string
  sku: string
  brand_name: string
  unit: string
  unit_mrp: string
  unit_price: string
  gst_rate: string
  quantity: number
  line_total: string
  offer_discount: string
  image: string | null
  /** Units the customer can return right now (0 outside the return window). */
  returnable_quantity: number
  /** Units the store has already received back. */
  returned_quantity: number
}

export type ReturnStatus = 'requested' | 'approved' | 'rejected' | 'received' | 'cancelled'
export type ReturnReason = 'damaged' | 'defective' | 'wrong_item' | 'not_as_described' | 'no_longer_needed' | 'other'

export interface ReturnRequest {
  return_number: string
  order_number: string
  status: ReturnStatus
  status_label: string
  reason: ReturnReason
  reason_label: string
  details: string
  /** Server-calculated: what was paid for these units (delivery fee excluded). */
  refund_amount: string
  refund_method: 'original_payment' | 'manual'
  refund_method_label: string
  refund_status: 'pending' | 'processed' | 'failed' | null
  restocked: boolean
  decision_note: string
  created_at: string
  decided_at: string | null
  received_at: string | null
  cancelled_at: string | null
  can_cancel: boolean
  /** The delivery partner sent to collect the items, if the store arranged a pickup. */
  pickup: {
    status: string
    status_label: string
    rider_name: string
    rider_phone: string | null
    picked_up_at: string | null
    failure_reason: string
  } | null
  items: {
    order_item_id: number
    sku: string
    product_name: string
    variant_name: string
    quantity: number
    refund_amount: string
    image: string | null
  }[]
}

export interface ReorderLine {
  sku: string
  name: string
  requested: number
  added: number
  reason: string
}

export interface StatusHistoryEntry {
  from_status: OrderStatus | ''
  to_status: OrderStatus
  note: string
  created_at: string
}

export interface OrderPayment {
  public_id: string
  provider: 'mock' | 'razorpay' | 'cod'
  method: string
  amount: string
  currency: string
  status: 'created' | 'pending' | 'authorized' | 'captured' | 'failed' | 'cancelled' | 'refunded' | 'partially_refunded'
  failure_reason: string
  captured_at: string | null
  created_at: string
  /** Public data needed to open the payment screen (only while status is "created"). Never secrets. */
  client_payload: { mock?: boolean; notice?: string; mock_signature?: string } & RazorpayPayload
}

export interface OrderRefund {
  public_id: string
  amount: string
  status: 'pending' | 'processed' | 'failed'
  reason: string
  /** Cash-on-delivery money: paid back by the store, not through the gateway. */
  manual: boolean
  created_at: string
  processed_at: string | null
}

export interface AddressSnapshot {
  name: string
  phone: string
  address_line1: string
  address_line2: string
  area: string
  landmark: string
  city: string
  state: string
  postal_code: string
  address_type: string
}

/** Phase 17: credits used on the order, given back, and cashback/rewards earned with it. */
export interface OrderLoyalty {
  credits_used: string
  credits_restored: string
  earned: {
    kind: 'cashback' | 'referral' | 'promo'
    amount: string
    status: 'pending' | 'eligible' | 'available' | 'reversed' | 'expired'
    status_label: string
    available_at: string | null
    description: string
  }[]
}

export interface OrderDetail extends Omit<OrderSummary, 'item_count' | 'item_names' | 'image'> {
  credit_discount?: string
  loyalty?: OrderLoyalty
  public_id: string
  address_snapshot: AddressSnapshot
  store_name: string | null
  subtotal: string
  mrp_total: string
  discount_total: string
  offer_discount: string
  coupon_discount: string
  /** Snapshot of automatic offers applied when the order was placed. */
  applied_offers: { id: number; name: string; badge: string; discount: string; skus: string[] }[]
  delivery_fee: string
  tax_total: string
  coupon_code: string
  customer_note: string
  eta_minutes: number | null
  /** One per store the order ships from (usually one). */
  shipments: OrderShipment[]
  cancellation_reason: string
  cancelled_at: string | null
  delivered_at: string | null
  can_cancel: boolean
  can_retry_payment: boolean
  can_return: boolean
  return_window_ends_at: string | null
  can_reorder: boolean
  items: OrderItem[]
  status_history: StatusHistoryEntry[]
  payments: OrderPayment[]
  refunds: OrderRefund[]
  returns: ReturnRequest[]
}
