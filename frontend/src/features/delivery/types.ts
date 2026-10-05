/** Delivery shapes from the API. Every estimate is calculated by the backend fulfilment engine. */

export type DeliveryType = 'fast' | 'standard'

export interface QuoteShipment {
  sequence: number
  store_name: string
  store_area: string
  line_count: number
  delivery_type: DeliveryType | null
  eta_minutes: number | null
  label: string
  distance_km: number | null
}

/** Estimate for a product, a cart or a checkout (GET /delivery/estimate/, /delivery/cart-estimate/, checkout preview). */
export interface DeliveryQuote {
  available: boolean
  fee: string
  free_delivery_min_order: string
  amount_to_free_delivery: string
  fast_delivery_possible: boolean
  /** null until a location is known, or when the items can't be delivered there. */
  eta_minutes: number | null
  message: string
  delivery_type: DeliveryType | null
  /** "Delivery in 38 minutes" or "Tomorrow, 10:00 AM – 12:00 PM". */
  label: string
  store_name: string | null
  estimated_delivery_at: string | null
  window_start: string | null
  window_end: string | null
  prep_minutes: number | null
  distance_km: number | null
  fast_unavailable_reason: string
  location_precision: 'exact' | 'pin' | 'unknown' | null
  /** Why not deliverable: out_of_zone, location_unknown, insufficient_stock, cart_empty. */
  reason_code: string
  shipments: QuoteShipment[]
  /** Why delivery is free (a rule, an offer or the order value); empty when it is not. */
  free_delivery_reason?: string
  /** Items that count towards free delivery, e.g. "Cement" (empty = everything). */
  free_delivery_hint?: string
}

/** GET /delivery/check/ */
export interface Serviceability {
  serviceable: boolean
  postal_code: string
  location_precision: 'exact' | 'pin' | 'unknown'
  fast_delivery_available: boolean
  label: string
  fast_unavailable_reason: string
  message: string
  stores: {
    name: string
    area: string
    distance_km: number | null
    fast_available: boolean
    eta_minutes: number
    label: string
  }[]
}

/** The delivery promise stored on an order. */
export interface OrderDelivery {
  /** null for orders placed before delivery estimates existed. */
  type: DeliveryType | null
  type_label: string | null
  fast: boolean
  eta_minutes: number | null
  minutes_left: number | null
  estimated_ready_at: string | null
  estimated_delivery_at: string | null
  window_start: string | null
  window_end: string | null
  label: string
}

export type ShipmentStatus =
  | 'pending'
  | 'assigned'
  | 'picked_up'
  | 'out_for_delivery'
  | 'delivered'
  | 'failed'
  | 'cancelled'

/** The code the customer gives the rider at the door. Present only while it is needed. */
export interface DeliveryCode {
  state: 'none' | 'active' | 'expired' | 'locked' | 'used'
  /** null when the code can't be used (expired or locked): ask for a new one. */
  code: string | null
  expires_at: string | null
  can_request_new: boolean
}

export interface ShipmentRider {
  name: string
  vehicle: string
  /** Shown only while the rider is carrying the goods. */
  phone: string | null
  status: string
}

export interface ShipmentFailure {
  code: string
  reason: string
  failed_at: string | null
  next_step: string
}

export interface OrderShipment {
  sequence: number
  store_name: string
  store_area: string
  status: ShipmentStatus
  status_label: string
  delivery_attempts: number
  picked_up_at: string | null
  out_for_delivery_at: string | null
  delivered_at: string | null
  rider: ShipmentRider | null
  delivery_code: DeliveryCode | null
  failure: ShipmentFailure | null
  proof_available: boolean
  received_by: string
  /** Cash on delivery: what to pay the rider for this shipment; null when nothing is due. */
  amount_to_pay: string | null
  delivery_type: DeliveryType
  distance_km: string | null
  prep_minutes: number
  eta_minutes: number
  estimated_ready_at: string | null
  estimated_delivery_at: string | null
  window_start: string | null
  window_end: string | null
  item_ids: number[]
}
