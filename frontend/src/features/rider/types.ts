/** The delivery partner's API shapes. Everything is decided by the server; the app only shows it. */

export type JobStatus =
  | 'assigned'
  | 'accepted'
  | 'picked_up'
  | 'out_for_delivery'
  | 'delivered'
  | 'failed'
  | 'rejected'
  | 'cancelled'

export type JobKind = 'delivery' | 'return_pickup'
export type JobAction = 'accept' | 'reject' | 'pickup' | 'start' | 'proof' | 'complete' | 'fail'
export type CodMethod = 'cash' | 'upi'

export type FailureCode =
  | 'customer_unavailable'
  | 'wrong_address'
  | 'customer_refused'
  | 'payment_not_ready'
  | 'damaged'
  | 'vehicle_problem'
  | 'other'

/** A place to go to. Customer details are present only while the job is active. */
export interface JobLocation {
  name?: string | null
  phone?: string | null
  address?: string
  area?: string | null
  city?: string | null
  landmark?: string | null
  postal_code?: string | null
  latitude?: string | null
  longitude?: string | null
  /** The customer's delivery note ("call before delivery"). */
  note?: string
  map_url?: string
  directions_url?: string
  geo_uri?: string
}

export interface JobCod {
  amount_due: string
  collected: boolean
  collected_amount: string | null
  method: CodMethod | null
  collected_at: string | null
  handed_over: boolean
  handed_over_at: string | null
}

export interface Job {
  id: number
  kind: JobKind
  kind_label: string
  status: JobStatus
  status_label: string
  order_number: string
  order_status: string
  payment_method: 'cod' | 'online'
  shipment_sequence: number | null
  return_number: string | null
  /** Cash still to collect at the door; null when nothing is due. */
  amount_to_collect: string | null
  cod: JobCod | null
  pickup: JobLocation | null
  drop: JobLocation | null
  items: { name: string; variant: string; sku: string; quantity: number }[]
  /** The rider never sees the code, only whether one is waiting to be entered. */
  otp_state: 'none' | 'active' | 'expired' | 'locked' | 'used'
  proof_uploaded: boolean
  proof_required: boolean
  received_by: string
  next_actions: JobAction[]
  assigned_at: string
  accepted_at: string | null
  picked_up_at: string | null
  out_for_delivery_at: string | null
  delivered_at: string | null
  failed_at: string | null
  failure_code: FailureCode | ''
  failure_reason: string
  rejected_at: string | null
  reject_reason: string
  distance_km: string | null
  earning_amount: string
  delivery_notes: string
  status_history: { from_status: string; to_status: string; note: string; created_at: string }[]
}

export interface RiderProfile {
  full_name: string
  email: string
  phone: string
  vehicle_type: string
  vehicle_number: string
  home_store_name: string | null
  status: 'offline' | 'available' | 'busy'
  is_verified: boolean
  is_active: boolean
  max_active_assignments: number
  active_assignments: number
  cash_in_hand: string
  last_location_at: string | null
}

export interface Earnings {
  delivered_count: number
  total_earnings: string
  today_earnings: string
  last_7_days_earnings: string
  today_delivered_count: number
  failed_count: number
  cash_in_hand: string
  cash_deliveries_pending_handover: number
}

export interface CompleteInput {
  otp?: string
  cod_collected?: boolean
  cod_amount?: string
  cod_method?: CodMethod
  cod_reference?: string
  received_by?: string
  notes?: string
}
