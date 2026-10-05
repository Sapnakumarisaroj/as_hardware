/** Shapes of the staff APIs (/api/admin/* and the staff endpoints of earlier phases).
 * Money is a decimal string calculated by the server; the dashboard only displays it. */

import type { OrderDetail, OrderStatus, PaymentMethod, PaymentStatus } from '@/features/orders/types'

export type Section =
  | 'dashboard'
  | 'orders'
  | 'products'
  | 'categories'
  | 'brands'
  | 'inventory'
  | 'stores'
  | 'warehouses'
  | 'delivery'
  | 'offers'
  | 'coupons'
  | 'customers'
  | 'returns'
  | 'refunds'
  | 'support'
  | 'analytics'
  | 'search'
  | 'options'
  | 'collections'
  | 'free-delivery'
  | 'payment-settings'

export interface StoreRef {
  id: number
  name: string
  code: string
  kind: StoreKind
}

export interface AdminSession {
  user: { id: number; full_name: string; email: string; role: 'admin' | 'store_manager' }
  is_admin: boolean
  sections: Section[]
  stores: StoreRef[]
  can: Record<
    | 'manage_catalog'
    | 'manage_stores'
    | 'manage_offers'
    | 'manage_customers'
    | 'manage_riders'
    | 'adjust_stock'
    | 'handle_orders'
    | 'handle_returns',
    boolean
  >
}

// --- Dashboard and analytics ---------------------------------------------------------------------

export interface SeriesRow {
  start: string
  label: string
  orders: number
  paid_orders: number
  revenue: string
  refunded: string
  net_revenue: string
  average_order_value: string | null
  cancelled: number
  delivered: number
}

export interface AttentionItem {
  code: string
  label: string
  count: number
  link: string
}

export interface Summary {
  generated_at: string
  orders: {
    total: number
    today: number
    pending: number
    processing: number
    on_the_way: number
    delivered: number
    cancelled: number
    delivery_failed: number
    by_status: Record<OrderStatus, number>
  }
  revenue: { total: string; today: string; this_month: string; refunded_total: string }
  returns: { total: number; open: number }
  refunds: { pending: number; pending_amount: string; failed: number; processed: number; processed_amount: string }
  inventory: { low_stock: number; out_of_stock: number }
  delivery: {
    partners: number
    partners_online: number
    partners_available: number
    waiting_for_rider: number
    cash_with_riders: string
  }
  stores: { active: number; accepting_orders: number; warehouses: number }
  customers: { total: number; active: number; new_this_month: number } | null
  products: { total: number; published: number; unpublished: number } | null
  trend: SeriesRow[]
  attention: AttentionItem[]
}

export interface DeliveryGroup {
  delivered: number
  with_estimate: number
  on_time: number
  on_time_rate: number | null
  average_promised_minutes: number | null
  average_actual_minutes: number | null
}

export type GroupBy = 'day' | 'week' | 'month'

export interface Analytics {
  period: { from: string; to: string; group_by: GroupBy; days: number }
  totals: {
    orders: number
    paid_orders: number
    revenue: string
    refunded: string
    net_revenue: string
    average_order_value: string | null
    delivered: number
    cancelled: number
    cancellation_rate: number | null
    payment_methods: Partial<Record<PaymentMethod, number>>
  }
  series: SeriesRow[]
  category_sales: { category: string; units: number; sales: string; share: number | null }[]
  top_products: { product_id: number | null; name: string; units: number; orders: number; sales: string }[]
  low_performing_products: { product_id: number; name: string; slug: string; units: number }[]
  cancellations: { count: number; rate: number | null; value: string; reasons: { reason: string; count: number }[] }
  returns: {
    count: number
    rate: number | null
    open: number
    received: number
    rejected: number
    refund_value: string
    reasons: { code: string; label: string; count: number }[]
  }
  refunds: {
    requested: number
    requested_amount: string
    processed: number
    processed_amount: string
    pending: number
    failed: number
  }
  delivery: {
    all: DeliveryGroup
    fast: DeliveryGroup
    standard: DeliveryGroup
    first_attempt_rate: number | null
    failed_attempts: number
    failure_reasons: { code: string; label: string; count: number }[]
    delivered_by_partners: number
    fast_window_minutes: number
  }
}

// --- Orders --------------------------------------------------------------------------------------

export interface OrderCustomer {
  id: number
  name: string
  email: string
  phone: string
  is_active: boolean
}

export interface AdminOrderRow {
  order_number: string
  status: OrderStatus
  payment_method: PaymentMethod
  payment_status: PaymentStatus
  grand_total: string
  delivery_type: 'fast' | 'standard' | ''
  estimated_delivery_at: string | null
  created_at: string
  customer: OrderCustomer
  store_name: string | null
  item_count: number
  item_names: string[]
  shipments: { id: number; sequence: number; store_name: string; status: string; rider: string | null }[]
  open_return: boolean
  refund_status: 'failed' | 'pending' | 'processed' | null
}

export interface CodSummary {
  amount_due: string
  collected: boolean
  method: 'cash' | 'upi' | null
  reference: string
  collected_at: string | null
  handed_over: boolean
  handed_over_at: string | null
}

export interface StaffShipment {
  id: number
  order_number: string
  order_status: OrderStatus
  payment_method: PaymentMethod
  sequence: number
  store_name: string
  status: string
  status_label: string
  delivery_type: string
  distance_km: string | null
  estimated_ready_at: string | null
  estimated_delivery_at: string | null
  delivery_attempts: number
  picked_up_at: string | null
  out_for_delivery_at: string | null
  delivered_at: string | null
  failed_at: string | null
  failure_reason: string
  failure_note: string
  assigned_partner: string | null
  rider: {
    assignment_id: number
    assignment_status: string
    partner_id: number
    full_name: string
    phone: string
    completed_without_otp: boolean
  } | null
  cod: CodSummary | null
  proof_available: boolean
  can_assign: boolean
  can_reassign: boolean
}

export interface AdminOrderDetail extends OrderDetail {
  customer: OrderCustomer
  staff_shipments: StaffShipment[]
  allowed_actions: { status: OrderStatus; label: string }[]
  can_manage: boolean
}

export interface EligiblePartner {
  partner_id: number
  full_name: string
  vehicle_type: string
  same_store: boolean
  active_assignments: number
  capacity: number
  distance_km: number | null
}

// --- Catalogue -----------------------------------------------------------------------------------

export interface NamedRef {
  id: number
  name: string
  slug: string
}

export type ProductState = 'live' | 'draft' | 'inactive' | 'deleted'

export interface AdminProductRow {
  id: number
  name: string
  slug: string
  sku: string
  brand: NamedRef | null
  category: NamedRef | null
  subcategory: NamedRef | null
  unit: string
  is_active: boolean
  is_published: boolean
  is_featured: boolean
  is_returnable: boolean
  is_deleted: boolean
  state: ProductState
  variant_count: number
  price_from: string | null
  price_to: string | null
  stock_available: number
  image: string | null
  updated_at: string
}

export interface AdminVariant {
  id: number
  sku: string
  name: string
  attributes: Record<string, string>
  mrp: string
  price: string
  is_default: boolean
  is_active: boolean
  sort_order: number
  stock_available: number
  stock_reserved: number
  /** Bulk prices (Phase 15): from `min_quantity` units, `unit_price` each. */
  price_tiers?: { min_quantity: number; unit_price: string }[]
  options?: { option_type: number; option_name: string; value_id: number; value: string }[]
}

export interface AdminProductImage {
  id: number
  image: string
  alt_text: string
  is_primary: boolean
  sort_order: number
}

export interface AdminProduct extends AdminProductRow {
  short_description: string
  description: string
  tags: string[]
  gst_rate: string
  hsn_code: string
  max_order_quantity: number | null
  variants: AdminVariant[]
  specifications: { id?: number; group?: string; name: string; value: string }[]
  images: AdminProductImage[]
  launch_date?: string | null
  /** Options that can be set on this product's variants (its category's or shop-wide ones). */
  option_types?: { id: number; name: string; unit: string; values: { id: number; value: string }[] }[]
}

export interface VariantInput {
  id?: number
  sku: string
  name: string
  mrp: string
  price: string
  is_default: boolean
  is_active: boolean
  /** Replace-all lists; the server checks every rule (no overlaps, cheaper with quantity, ≤ MRP). */
  price_tiers?: { min_quantity: string; unit_price: string }[]
  options?: { option_type: number; value: string }[]
}

export interface ProductInput {
  name: string
  sku: string
  brand: number | null
  category: number | null
  subcategory: number | null
  short_description: string
  description: string
  unit: string
  gst_rate: string
  hsn_code: string
  is_active: boolean
  is_published: boolean
  is_featured: boolean
  is_returnable: boolean
  variants: VariantInput[]
  specifications: { name: string; value: string }[]
  launch_date?: string | null
}

export interface AdminCategory {
  id: number
  name: string
  slug: string
  parent: number | null
  parent_name: string | null
  description: string
  image: string | null
  sort_order: number
  is_active: boolean
  product_count: number
  children: AdminCategory[]
  /** 1 = department / main category, 2 = category, 3 = subcategory (the deepest). */
  level?: number
}

export interface AdminBrand {
  id: number
  name: string
  slug: string
  is_active: boolean
  product_count: number
}

// --- Inventory -----------------------------------------------------------------------------------

export interface InventoryRow {
  id: number
  store: number
  store_code: string
  store_name: string
  variant: number
  sku: string
  product_name: string
  variant_name: string
  available_quantity: number
  reserved_quantity: number
  low_stock_threshold: number
  is_low_stock: boolean
  is_active: boolean
  updated_at: string
}

export interface StockMovement {
  id: number
  inventory: number
  sku: string
  store_code: string
  movement_type: string
  quantity: number
  available_after: number
  reserved_after: number
  reason: string
  reference_type: string
  reference_id: string
  created_at: string
}

export type ManualMovement = 'purchase' | 'adjustment' | 'return'

export interface VariantHit {
  id: number
  sku: string
  product_name: string
  variant_name: string
  price: string
}

// --- Stores --------------------------------------------------------------------------------------

export type StoreKind = 'store' | 'dark_store' | 'warehouse'
export type Day = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
export type OpeningHours = Partial<Record<Day, [string, string] | null>>

export interface StoreRow {
  id: number
  name: string
  code: string
  kind: StoreKind
  kind_label: string
  phone: string
  area: string
  city: string
  postal_code: string
  is_active: boolean
  accepts_orders: boolean
  /** Cash on delivery allowed for orders shipped from this store (administrators decide). */
  cod_enabled?: boolean
  avg_prep_minutes: number
  own_riders: number
  has_location: boolean
  zone_count: number
  open_orders: number
  can_edit: 'all' | 'operations' | 'none'
}

export interface Zone {
  id: number
  store: number
  store_name: string
  name: string
  radius_km: string
  postal_codes: string
  pin_codes: string[]
  polygon: [number, number][] | null
  fast_delivery_enabled: boolean
  fast_delivery_max_minutes: number | null
  delivery_fee_override: string | null
  free_delivery_min_order: string | null
  effective_fee: string
  effective_free_from: string
  cod_enabled?: boolean
  is_active: boolean
}

export interface StoreDetail extends StoreRow {
  email: string
  address_line1: string
  address_line2: string
  state: string
  latitude: string | null
  longitude: string | null
  opening_hours: OpeningHours
  prep_minutes_per_item: number
  managers: { id: number; name: string; email: string }[]
  zones: Zone[]
  inventory: {
    stock_records: number
    units_available: number
    units_reserved: number
    low_stock: number
    out_of_stock: number
  }
  riders: { partners: number; online: number; own_riders: number }
}

// --- Delivery ------------------------------------------------------------------------------------

export interface Rider {
  partner_id: number
  user_id: number
  full_name: string
  email: string
  phone: string
  vehicle_type: string
  vehicle_number: string
  home_store: number | null
  home_store_name: string | null
  status: 'offline' | 'available' | 'busy'
  is_verified: boolean
  is_active: boolean
  active_assignments: number
  capacity: number
  can_take_jobs: boolean
  last_location_at: string | null
  cash_in_hand: string
  delivered: number
  delivered_today: number
  failed: number
  earnings_today: string
  earnings_7_days: string
  earnings_total: string
}

export interface JobRow {
  id: number
  kind: 'delivery' | 'return_pickup'
  kind_label: string
  status: string
  status_label: string
  partner_id: number
  partner_name: string
  assigned_at: string
  delivered_at: string | null
  failed_at: string | null
  failure_code: string
  failure_reason: string
  reject_reason: string
  completed_without_otp: boolean
  proof_available: boolean
  cod_amount_due: string
  cod_collected_amount: string | null
  earning_amount: string
  order_number: string
  order_status: OrderStatus
  shipment_id: number | null
  store_name: string | null
  return_number: string | null
  distance_km: string | null
}

export interface CodRow {
  assignment_id: number
  order_number: string
  store_name: string | null
  partner_id: number
  partner_name: string
  cod_amount_due: string
  cod_collected_amount: string | null
  cod_method: 'cash' | 'upi' | ''
  cod_reference: string
  cod_collected_at: string | null
  handed_over: boolean
  cod_handed_over_at: string | null
  handed_over_to: string | null
  cod_handover_note: string
}

// --- Offers --------------------------------------------------------------------------------------

export type RuleState = 'live' | 'scheduled' | 'expired' | 'inactive'

export interface DiscountRule {
  id: number
  description: string
  discount_type: 'percent' | 'fixed'
  value: string
  max_discount_amount: string | null
  min_order_value: string
  starts_at: string
  ends_at: string | null
  is_active: boolean
  state: RuleState
  summary: string
  products: number[]
  categories: number[]
  product_details: { id: number; name: string; sku: string }[]
  category_details: { id: number; name: string }[]
}

export interface Offer extends DiscountRule {
  name: string
  priority: number
  /** Phase 15 */
  benefit?: 'discount' | 'free_delivery'
  min_quantity?: number
  /** 0 = first order only; 4 = the first five orders; null = everyone. */
  max_prior_orders?: number | null
  campaign?: string
  usage_limit?: number | null
  per_customer_limit?: number | null
  used_count?: number
  remaining_uses?: number | null
  conditions?: string[]
}

export interface Coupon extends DiscountRule {
  code: string
  usage_limit: number | null
  per_customer_limit: number
  used_count: number
  remaining_uses: number | null
  show_in_checkout: boolean
}

export type RuleInput = Partial<
  Omit<Offer & Coupon, 'id' | 'state' | 'summary' | 'product_details' | 'category_details' | 'per_customer_limit'>
> & { per_customer_limit?: number | null }

// --- Customers -----------------------------------------------------------------------------------

export type Role = 'customer' | 'store_manager' | 'delivery_partner' | 'admin'

export interface CustomerRow {
  id: number
  full_name: string
  email: string
  phone: string | null
  role: Role
  is_active: boolean
  email_verified: boolean
  date_joined: string
  last_login: string | null
  order_count: number
  total_spend: string
  last_order_at: string | null
}

export interface CustomerDetail extends CustomerRow {
  deactivated_at: string | null
  cancelled_orders: number
  returns: number
  addresses: { area: string; city: string; postal_code: string; is_default: boolean }[]
  managed_stores: { id: number; name: string; code: string }[]
  recent_orders: {
    order_number: string
    status: OrderStatus
    payment_status: PaymentStatus
    grand_total: string
    store_name: string | null
    created_at: string
  }[]
}

// --- Refunds and support -------------------------------------------------------------------------

export interface StaffRefund {
  public_id: string
  order_number: string
  payment_provider: string
  customer_name: string
  store_name: string | null
  amount: string
  status: 'pending' | 'processed' | 'failed'
  reason: string
  is_manual: boolean
  provider_refund_id: string
  attempts: number
  failure_reason: string
  manual_reference: string
  created_at: string
  processed_at: string | null
}

export type SupportStatus = 'open' | 'waiting_customer' | 'resolved' | 'closed'

export interface SupportRow {
  id: number
  subject: string
  channel: string
  status: SupportStatus
  status_label: string
  customer: { id: number | null; name: string; email: string; phone: string } | null
  order_number: string | null
  store_name: string | null
  assigned_to: number | null
  assigned_to_name: string | null
  message_count: number
  last_message: string
  waiting_for_reply: boolean
  last_message_at: string | null
  created_at: string
}

export interface SupportDetail extends SupportRow {
  messages: {
    id: number
    sender_type: 'customer' | 'agent' | 'bot' | 'system'
    sender_name: string
    body: string
    created_at: string
  }[]
}

// --- Search index (Phase 13) ---------------------------------------------------------------------

export interface SearchIndexStatus {
  embedder: {
    kind: 'none' | 'hashing' | 'sentence_transformers'
    key: string
    available: boolean
    dimensions: number
    model?: string
    loaded?: boolean
  }
  search_backend: string
  products: number
  indexed: number
  missing: number
  stale: number
  other_embedder: number
  last_updated: string | null
  ready: boolean
}

export interface SearchRebuildResult {
  result: { embedded: number; unchanged: number; removed: number; failed: string[] }
  status: SearchIndexStatus
}

export interface SearchExplainRow {
  product_id: number
  name: string
  keyword: number
  related: number
  semantic: number
  cosine: number | null
  final: number
  reason?: { type: 'keyword' | 'related' | 'semantic'; text: string }
}

export interface SearchExplanation {
  mode: 'keyword' | 'hybrid'
  embedder?: string
  terms: string[]
  related_terms: string[]
  sources?: Record<string, string>
  matched: string
  results: SearchExplainRow[]
}

// --- Phase 15 commerce settings ----------------------------------------------------------------------

export interface OptionTypeRow {
  id: number
  name: string
  slug: string
  unit: string
  sort_order: number
  is_active: boolean
  categories: number[]
  category_details: { id: number; name: string }[]
  values: { id: number; value: string; slug: string; used_by: number }[]
  variant_count: number
}

export interface OptionTypeInput {
  name?: string
  unit?: string
  sort_order?: number
  is_active?: boolean
  categories?: number[]
  value_list?: { id?: number; value: string }[]
}

export type CollectionRule = 'manual' | 'best_sellers' | 'new_launches' | 'bulk_pricing'

export interface CollectionRow {
  id: number
  name: string
  slug: string
  description: string
  rule: CollectionRule
  window_days: number
  max_items: number
  categories: number[]
  category_details: { id: number; name: string }[]
  starts_at: string | null
  ends_at: string | null
  is_active: boolean
  sort_order: number
  items: { product_id: number; name: string; sku: string; live: boolean }[]
  state: RuleState
}

export interface CollectionInput {
  name?: string
  description?: string
  rule?: CollectionRule
  window_days?: number
  max_items?: number
  categories?: number[]
  starts_at?: string | null
  ends_at?: string | null
  is_active?: boolean
  sort_order?: number
  product_ids?: number[]
}

export interface CollectionPreview {
  is_live: boolean
  count: number
  products: { id: number; name: string; sku: string; price: string }[]
}

export interface FreeDeliveryRuleRow {
  id: number
  name: string
  description: string
  threshold: string
  zones: number[]
  products: number[]
  categories: number[]
  zone_details: { id: number; name: string }[]
  product_details: { id: number; name: string; sku: string }[]
  category_details: { id: number; name: string }[]
  starts_at: string
  ends_at: string | null
  is_active: boolean
  state: RuleState
  summary: string
}

export type FreeDeliveryRuleInput = Partial<
  Pick<FreeDeliveryRuleRow, 'name' | 'description' | 'threshold' | 'zones' | 'products' | 'categories' | 'starts_at' | 'ends_at' | 'is_active'>
>

export interface PaymentSettings {
  cod_enabled: boolean
  /** Largest order total payable in cash; null = no limit. */
  cod_max_order_value: string | null
  updated_at: string
  updated_by_name: string | null
  stores_without_cod: { id: number; name: string }[]
  zones_without_cod: { id: number; name: string; store_name: string }[]
}
