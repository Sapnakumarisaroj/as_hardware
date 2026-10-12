import type {
  AdminOrderDetail,
  AdminOrderRow,
  AdminProduct,
  AdminProductRow,
  AdminSession,
  Analytics,
  CodRow,
  Coupon,
  CustomerDetail,
  CustomerRow,
  InventoryRow,
  Offer,
  Rider,
  SeriesRow,
  StaffRefund,
  StaffShipment,
  StoreDetail,
  StoreRow,
  Summary,
  SupportDetail,
  Zone,
} from '@/features/admin/types'
import type { User } from '@/features/auth/api'
import type { ReturnRequest } from '@/features/orders/types'

import { customer, orderDetail } from './fixtures'

/** Staff-API-shaped test data for the business dashboard. */

export const adminUser: User = { ...customer, id: 1, email: 'owner@example.com', full_name: 'Meera Owner', role: 'admin' }
export const managerUser: User = { ...customer, id: 2, email: 'manager@example.com', full_name: 'Sunil Manager', role: 'store_manager' }
export const riderUser: User = { ...customer, id: 21, email: 'ravi@example.com', full_name: 'Ravi Rider', role: 'delivery_partner' }

const KOTHRUD = { id: 1, name: 'Kothrud Store', code: 'PUN-01', kind: 'store' as const }
const HADAPSAR = { id: 2, name: 'Hadapsar Store', code: 'PUN-02', kind: 'store' as const }
const WAREHOUSE = { id: 3, name: 'Central Warehouse', code: 'WH-01', kind: 'warehouse' as const }

const ALL_SECTIONS: AdminSession['sections'] = [
  'dashboard', 'orders', 'products', 'categories', 'brands', 'inventory', 'stores', 'warehouses',
  'delivery', 'offers', 'coupons', 'customers', 'returns', 'refunds', 'support', 'analytics', 'search',
  'options', 'collections', 'free-delivery', 'payment-settings', 'delivery-charges', 'loyalty',
] // prettier-ignore

export const adminSession: AdminSession = {
  user: { id: 1, full_name: 'Meera Owner', email: 'owner@example.com', role: 'admin' },
  is_admin: true,
  sections: ALL_SECTIONS,
  stores: [KOTHRUD, HADAPSAR, WAREHOUSE],
  can: {
    manage_catalog: true,
    manage_stores: true,
    manage_offers: true,
    manage_customers: true,
    manage_riders: true,
    adjust_stock: true,
    handle_orders: true,
    handle_returns: true,
  },
}

export const managerSession: AdminSession = {
  user: { id: 2, full_name: 'Sunil Manager', email: 'manager@example.com', role: 'store_manager' },
  is_admin: false,
  sections: ['dashboard', 'orders', 'inventory', 'stores', 'delivery', 'returns', 'refunds', 'support', 'analytics'],
  stores: [KOTHRUD],
  can: {
    ...adminSession.can,
    manage_catalog: false,
    manage_stores: false,
    manage_offers: false,
    manage_customers: false,
    manage_riders: false,
  },
}

export function page<T>(results: T[], count = results.length) {
  return { count, next: null, previous: null, results }
}

export function seriesRow(overrides: Partial<SeriesRow> = {}): SeriesRow {
  return {
    start: '2026-09-29',
    label: '29 Sep',
    orders: 3,
    paid_orders: 2,
    revenue: '2600.00',
    refunded: '0.00',
    net_revenue: '2600.00',
    average_order_value: '1300.00',
    cancelled: 1,
    delivered: 1,
    ...overrides,
  }
}

export function summary(overrides: Partial<Summary> = {}): Summary {
  return {
    generated_at: '2026-09-29T06:30:00Z',
    orders: {
      total: 128,
      today: 7,
      pending: 2,
      processing: 5,
      on_the_way: 3,
      delivered: 104,
      cancelled: 11,
      delivery_failed: 1,
      by_status: {
        pending: 2,
        confirmed: 3,
        processing: 1,
        packed: 1,
        assigned: 1,
        picked_up: 1,
        out_for_delivery: 1,
        delivered: 100,
        delivery_failed: 1,
        cancelled: 11,
        return_requested: 2,
        returned: 2,
      },
    },
    revenue: { total: '245300.00', today: '9850.00', this_month: '81200.50', refunded_total: '4300.00' },
    returns: { total: 6, open: 2 },
    refunds: { pending: 1, pending_amount: '900.00', failed: 1, processed: 8, processed_amount: '4300.00' },
    inventory: { low_stock: 4, out_of_stock: 1 },
    delivery: { partners: 5, partners_online: 3, partners_available: 2, waiting_for_rider: 2, cash_with_riders: '3400.00' },
    stores: { active: 2, accepting_orders: 2, warehouses: 1 },
    customers: { total: 86, active: 84, new_this_month: 12 },
    products: { total: 240, published: 221, unpublished: 19 },
    trend: [seriesRow({ start: '2026-09-28', label: '28 Sep', orders: 4, revenue: '5100.00' }), seriesRow()],
    attention: [
      { code: 'orders_to_prepare', label: 'Orders to prepare', count: 5, link: '/admin/orders?status=confirmed,processing' },
      { code: 'waiting_for_rider', label: 'Packed shipments without a rider', count: 2, link: '/admin/delivery?tab=shipments' },
      { code: 'failed_refunds', label: 'Refunds that failed', count: 1, link: '/admin/refunds?status=failed' },
    ],
    ...overrides,
  }
}

const group = (delivered: number, rate: number | null) => ({
  delivered,
  with_estimate: delivered,
  on_time: delivered,
  on_time_rate: rate,
  average_promised_minutes: delivered ? 42 : null,
  average_actual_minutes: delivered ? 38.4 : null,
})

export function analytics(overrides: Partial<Analytics> = {}): Analytics {
  return {
    period: { from: '2026-08-31', to: '2026-09-29', group_by: 'day', days: 30 },
    totals: {
      orders: 42,
      paid_orders: 36,
      revenue: '81200.50',
      refunded: '1800.00',
      net_revenue: '79400.50',
      average_order_value: '2255.57',
      delivered: 33,
      cancelled: 4,
      cancellation_rate: 9.5,
      payment_methods: { cod: 25, online: 17 },
    },
    series: [seriesRow({ start: '2026-09-28', label: '28 Sep', orders: 4, revenue: '5100.00' }), seriesRow()],
    category_sales: [
      { category: 'Tools', units: 60, sales: '52000.00', share: 64.0 },
      { category: 'Paint', units: 41, sales: '29200.50', share: 36.0 },
    ],
    top_products: [
      { product_id: 1, name: 'Impact Drill 650W', units: 14, orders: 12, sales: '44800.00' },
      { product_id: 2, name: 'Wall Primer 10 L', units: 9, orders: 9, sales: '16200.00' },
    ],
    low_performing_products: [{ product_id: 9, name: 'Dusty Shelf Bracket', slug: 'dusty-shelf-bracket', units: 0 }],
    cancellations: { count: 4, rate: 9.5, value: '6100.00', reasons: [{ reason: 'Ordered by mistake', count: 3 }] },
    returns: {
      count: 3,
      rate: 9.1,
      open: 1,
      received: 2,
      rejected: 0,
      refund_value: '1800.00',
      reasons: [{ code: 'damaged', label: 'Arrived damaged', count: 2 }],
    },
    refunds: { requested: 5, requested_amount: '3900.00', processed: 3, processed_amount: '1800.00', pending: 1, failed: 1 },
    delivery: {
      all: group(33, 93.9),
      fast: group(21, 95.2),
      standard: group(12, 91.7),
      first_attempt_rate: 97.0,
      failed_attempts: 2,
      failure_reasons: [{ code: 'customer_unavailable', label: 'Customer not available', count: 2 }],
      delivered_by_partners: 30,
      fast_window_minutes: 60,
    },
    ...overrides,
  }
}

export function orderRow(overrides: Partial<AdminOrderRow> = {}): AdminOrderRow {
  return {
    order_number: 'OD260929ABCDEF',
    status: 'packed',
    payment_method: 'cod',
    payment_status: 'pending',
    grand_total: '1240.00',
    delivery_type: 'fast',
    estimated_delivery_at: '2026-09-29T07:30:00Z',
    created_at: '2026-09-29T06:45:00Z',
    customer: { id: 7, name: 'Asha Kulkarni', email: 'asha@example.com', phone: '9876543210', is_active: true },
    store_name: 'Kothrud Store',
    item_count: 2,
    item_names: ['Impact Drill 650W'],
    shipments: [{ id: 31, sequence: 1, store_name: 'Kothrud Store', status: 'pending', rider: null }],
    open_return: false,
    refund_status: null,
    ...overrides,
  }
}

export function staffShipment(overrides: Partial<StaffShipment> = {}): StaffShipment {
  return {
    id: 31,
    order_number: 'OD260929ABCDEF',
    order_status: 'packed',
    payment_method: 'cod',
    sequence: 1,
    store_name: 'Kothrud Store',
    status: 'pending',
    status_label: 'Waiting for a rider',
    delivery_type: 'fast',
    distance_km: '2.70',
    estimated_ready_at: '2026-09-29T07:00:00Z',
    estimated_delivery_at: '2026-09-29T07:30:00Z',
    delivery_attempts: 0,
    picked_up_at: null,
    out_for_delivery_at: null,
    delivered_at: null,
    failed_at: null,
    failure_reason: '',
    failure_note: '',
    assigned_partner: null,
    rider: null,
    cod: null,
    proof_available: false,
    can_assign: true,
    can_reassign: false,
    ...overrides,
  }
}

export const assignedShipment = (overrides: Partial<StaffShipment> = {}) =>
  staffShipment({
    status: 'assigned',
    status_label: 'Assigned',
    order_status: 'assigned',
    assigned_partner: 'Ravi Rider',
    rider: {
      assignment_id: 5,
      assignment_status: 'assigned',
      partner_id: 4,
      full_name: 'Ravi Rider',
      phone: '9123456780',
      completed_without_otp: false,
    },
    can_assign: false,
    can_reassign: true,
    ...overrides,
  })

export function adminOrder(overrides: Partial<AdminOrderDetail> = {}): AdminOrderDetail {
  return {
    ...orderDetail(),
    order_number: 'OD260929ABCDEF',
    status: 'packed',
    payment_method: 'cod',
    payment_status: 'pending',
    store_name: 'Kothrud Store',
    customer: { id: 7, name: 'Asha Kulkarni', email: 'asha@example.com', phone: '9876543210', is_active: true },
    staff_shipments: [staffShipment()],
    allowed_actions: [
      { status: 'assigned', label: 'Assigned to delivery partner' },
      { status: 'cancelled', label: 'Cancelled' },
    ],
    can_manage: true,
    ...overrides,
  }
}

export function productRow(overrides: Partial<AdminProductRow> = {}): AdminProductRow {
  return {
    id: 1,
    name: 'Impact Drill 650W',
    slug: 'impact-drill-650w',
    sku: 'DEMO-DRILL',
    brand: { id: 1, name: 'DrillCo', slug: 'drillco' },
    category: { id: 10, name: 'Tools', slug: 'tools' },
    subcategory: { id: 11, name: 'Drills', slug: 'drills' },
    unit: 'piece',
    is_active: true,
    is_published: true,
    is_featured: false,
    is_returnable: true,
    is_deleted: false,
    state: 'live',
    variant_count: 1,
    price_from: '3200.00',
    price_to: '3200.00',
    stock_available: 14,
    image: null,
    updated_at: '2026-09-20T10:00:00Z',
    ...overrides,
  }
}

export function adminProduct(overrides: Partial<AdminProduct> = {}): AdminProduct {
  return {
    ...productRow(),
    short_description: '13 mm impact drill for concrete and wood.',
    description: 'A sturdy drill.',
    tags: [],
    gst_rate: '18.00',
    hsn_code: '8467',
    max_order_quantity: null,
    variants: [
      {
        id: 101,
        sku: 'DEMO-DRILL-STD',
        name: 'Standard',
        attributes: {},
        mrp: '4000.00',
        price: '3200.00',
        is_default: true,
        is_active: true,
        price_approved: true,
        price_source: '',
        sort_order: 0,
        stock_available: 14,
        stock_reserved: 2,
      },
    ],
    specifications: [{ name: 'Power', value: '650 W' }],
    images: [],
    ...overrides,
  }
}

export const adminCategories = [
  {
    id: 10,
    name: 'Tools',
    slug: 'tools',
    parent: null,
    parent_name: null,
    description: '',
    image: null,
    sort_order: 1,
    is_active: true,
    product_count: 12,
    children: [
      {
        id: 11,
        name: 'Drills',
        slug: 'drills',
        parent: 10,
        parent_name: 'Tools',
        description: '',
        image: null,
        sort_order: 0,
        is_active: true,
        product_count: 4,
        children: [],
      },
    ],
  },
  {
    id: 20,
    name: 'Paint',
    slug: 'paint',
    parent: null,
    parent_name: null,
    description: '',
    image: null,
    sort_order: 2,
    is_active: false,
    product_count: 0,
    children: [],
  },
]

export function inventoryRow(overrides: Partial<InventoryRow> = {}): InventoryRow {
  return {
    id: 51,
    store: 1,
    store_code: 'PUN-01',
    store_name: 'Kothrud Store',
    variant: 101,
    sku: 'DEMO-DRILL-STD',
    product_name: 'Impact Drill 650W',
    variant_name: 'Standard',
    available_quantity: 4,
    reserved_quantity: 2,
    low_stock_threshold: 5,
    is_low_stock: true,
    is_active: true,
    updated_at: '2026-09-29T05:00:00Z',
    ...overrides,
  }
}

export function storeRow(overrides: Partial<StoreRow> = {}): StoreRow {
  return {
    id: 1,
    name: 'Kothrud Store',
    code: 'PUN-01',
    kind: 'store',
    kind_label: 'Retail store',
    phone: '02012345678',
    area: 'Kothrud',
    city: 'Pune',
    postal_code: '411038',
    is_active: true,
    accepts_orders: true,
    avg_prep_minutes: 10,
    own_riders: 1,
    has_location: true,
    zone_count: 1,
    open_orders: 5,
    can_edit: 'all',
    ...overrides,
  }
}

export function zone(overrides: Partial<Zone> = {}): Zone {
  return {
    id: 8,
    store: 1,
    store_name: 'Kothrud Store',
    name: 'Kothrud 5 km',
    radius_km: '5.00',
    postal_codes: '411038 411029',
    pin_codes: ['411029', '411038'],
    polygon: null,
    fast_delivery_enabled: true,
    fast_delivery_max_minutes: 45,
    delivery_fee_override: null,
    free_delivery_min_order: null,
    effective_fee: '40.00',
    effective_free_from: '999.00',
    is_active: true,
    ...overrides,
  }
}

export function storeDetail(overrides: Partial<StoreDetail> = {}): StoreDetail {
  return {
    ...storeRow(),
    email: 'kothrud@example.com',
    address_line1: '1 Paud Road',
    address_line2: '',
    state: 'Maharashtra',
    latitude: '18.507400',
    longitude: '73.807700',
    opening_hours: { mon: ['09:00', '21:00'], tue: ['09:00', '21:00'], sun: null },
    prep_minutes_per_item: 1,
    managers: [{ id: 2, name: 'Sunil Manager', email: 'manager@example.com' }],
    zones: [zone()],
    inventory: { stock_records: 120, units_available: 2400, units_reserved: 35, low_stock: 4, out_of_stock: 1 },
    riders: { partners: 3, online: 2, own_riders: 1 },
    ...overrides,
  }
}

export function rider(overrides: Partial<Rider> = {}): Rider {
  return {
    partner_id: 4,
    user_id: 21,
    full_name: 'Ravi Rider',
    email: 'ravi@example.com',
    phone: '9123456780',
    vehicle_type: 'scooter',
    vehicle_number: 'MH12AB1234',
    home_store: 1,
    home_store_name: 'Kothrud Store',
    status: 'available',
    is_verified: true,
    is_active: true,
    active_assignments: 0,
    capacity: 2,
    can_take_jobs: true,
    last_location_at: null,
    cash_in_hand: '1200.00',
    delivered: 40,
    delivered_today: 3,
    failed: 1,
    earnings_today: '120.00',
    earnings_7_days: '830.00',
    earnings_total: '5100.00',
    ...overrides,
  }
}

export function codRow(overrides: Partial<CodRow> = {}): CodRow {
  return {
    assignment_id: 5,
    order_number: 'OD260929ABCDEF',
    store_name: 'Kothrud Store',
    partner_id: 4,
    partner_name: 'Ravi Rider',
    cod_amount_due: '1200.00',
    cod_collected_amount: '1200.00',
    cod_method: 'cash',
    cod_reference: '',
    cod_collected_at: '2026-09-29T07:20:00Z',
    handed_over: false,
    cod_handed_over_at: null,
    handed_over_to: null,
    cod_handover_note: '',
    ...overrides,
  }
}

const rule = {
  description: '',
  discount_type: 'percent' as const,
  value: '10.00',
  max_discount_amount: '400.00',
  min_order_value: '0.00',
  starts_at: '2026-09-01T00:00:00Z',
  ends_at: '2026-10-31T18:29:00Z',
  is_active: true,
  state: 'live' as const,
  products: [],
  categories: [10],
  product_details: [],
  category_details: [{ id: 10, name: 'Tools' }],
}

export function offer(overrides: Partial<Offer> = {}): Offer {
  return { id: 3, name: 'Tools week', priority: 100, summary: '10% off (up to ₹400) on Tools', ...rule, ...overrides }
}

export function coupon(overrides: Partial<Coupon> = {}): Coupon {
  return {
    id: 6,
    code: 'WELCOME50',
    usage_limit: 100,
    per_customer_limit: 1,
    used_count: 12,
    remaining_uses: 88,
    show_in_checkout: true,
    ...rule,
    discount_type: 'fixed',
    value: '50.00',
    max_discount_amount: null,
    min_order_value: '500.00',
    categories: [],
    category_details: [],
    summary: '₹50 off on the whole cart, from ₹500',
    ...overrides,
  }
}

export function customerRow(overrides: Partial<CustomerRow> = {}): CustomerRow {
  return {
    id: 7,
    full_name: 'Asha Kulkarni',
    email: 'asha@example.com',
    phone: '9876543210',
    role: 'customer',
    is_active: true,
    email_verified: true,
    date_joined: '2026-03-02T09:00:00Z',
    last_login: '2026-09-28T18:00:00Z',
    order_count: 9,
    total_spend: '18450.00',
    last_order_at: '2026-09-27T12:00:00Z',
    ...overrides,
  }
}

export function customerDetail(overrides: Partial<CustomerDetail> = {}): CustomerDetail {
  return {
    ...customerRow(),
    deactivated_at: null,
    cancelled_orders: 1,
    returns: 1,
    addresses: [{ area: 'Kothrud', city: 'Pune', postal_code: '411038', is_default: true }],
    managed_stores: [],
    recent_orders: [
      {
        order_number: 'OD260927ZZZZZZ',
        status: 'delivered',
        payment_status: 'paid',
        grand_total: '2400.00',
        store_name: 'Kothrud Store',
        created_at: '2026-09-27T12:00:00Z',
      },
    ],
    ...overrides,
  }
}

export function returnRequest(overrides: Partial<ReturnRequest> = {}): ReturnRequest {
  return {
    return_number: 'RT260929AAAAAA',
    order_number: 'OD260927ZZZZZZ',
    status: 'requested',
    status_label: 'Requested',
    reason: 'damaged',
    reason_label: 'Arrived damaged',
    details: 'The chuck is cracked.',
    refund_amount: '3200.00',
    refund_method: 'original_payment',
    refund_method_label: 'Back to the original payment',
    refund_status: null,
    restocked: false,
    decision_note: '',
    created_at: '2026-09-29T05:00:00Z',
    decided_at: null,
    received_at: null,
    cancelled_at: null,
    can_cancel: true,
    pickup: null,
    items: [
      {
        order_item_id: 1,
        sku: 'DEMO-DRILL-STD',
        product_name: 'Impact Drill 650W',
        variant_name: 'Standard',
        quantity: 1,
        refund_amount: '3200.00',
        image: null,
      },
    ],
    ...overrides,
  }
}

export function refund(overrides: Partial<StaffRefund> = {}): StaffRefund {
  return {
    public_id: '7f2c0000-0000-4000-8000-000000000001',
    order_number: 'OD260927ZZZZZZ',
    payment_provider: 'razorpay',
    customer_name: 'Asha Kulkarni',
    store_name: 'Kothrud Store',
    amount: '900.00',
    status: 'failed',
    reason: 'Order cancelled',
    is_manual: false,
    provider_refund_id: '',
    attempts: 1,
    failure_reason: 'Gateway timeout',
    manual_reference: '',
    created_at: '2026-09-28T10:00:00Z',
    processed_at: null,
    ...overrides,
  }
}

export function conversation(overrides: Partial<SupportDetail> = {}): SupportDetail {
  return {
    id: 12,
    subject: 'Wrong size delivered',
    channel: 'in_app',
    status: 'open',
    status_label: 'Open',
    customer: { id: 7, name: 'Asha Kulkarni', email: 'asha@example.com', phone: '9876543210' },
    order_number: 'OD260927ZZZZZZ',
    store_name: 'Kothrud Store',
    assigned_to: null,
    assigned_to_name: null,
    message_count: 1,
    last_message: 'I got the 10 mm, I ordered 12 mm.',
    waiting_for_reply: true,
    last_message_at: '2026-09-29T06:00:00Z',
    created_at: '2026-09-29T06:00:00Z',
    messages: [
      { id: 1, sender_type: 'customer', sender_name: 'Asha Kulkarni', body: 'I got the 10 mm, I ordered 12 mm.', created_at: '2026-09-29T06:00:00Z' },
    ],
    ...overrides,
  }
}

/** GET routes every dashboard page needs: who is signed in, the session and the live numbers. */
export function staffGet(role: 'admin' | 'manager' = 'admin', extra: Record<string, unknown> = {}) {
  return {
    '/auth/me/': role === 'admin' ? adminUser : managerUser,
    '/admin/session/': role === 'admin' ? adminSession : managerSession,
    '/admin/summary/': summary(role === 'admin' ? {} : { customers: null, products: null }),
    ...extra,
  }
}
