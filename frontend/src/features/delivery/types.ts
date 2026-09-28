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

export interface OrderShipment {
  sequence: number
  store_name: string
  store_area: string
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
