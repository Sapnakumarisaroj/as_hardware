import type { Address } from '@/features/addresses/api'
import type { User } from '@/features/auth/api'
import type { Cart, CartLine } from '@/features/cart/api'
import type { CheckoutPreview } from '@/features/checkout/api'
import type { DeliveryQuote, OrderDelivery } from '@/features/delivery/types'
import type { OrderDetail } from '@/features/orders/types'
import type {
  Category,
  ProductDetail,
  ProductFacets,
  ProductPage,
  ProductSummary,
  ProductVariant,
} from '@/features/catalog/types'

/** API-shaped test data (money as decimal strings, exactly as the backend sends it). */

export const customer: User = {
  id: 7,
  email: 'asha@example.com',
  full_name: 'Asha Kulkarni',
  phone: null,
  role: 'customer',
  email_verified: true,
  avatar: null,
}

export function productSummary(overrides: Partial<ProductSummary> = {}): ProductSummary {
  return {
    id: 1,
    name: 'Impact Drill 650W',
    slug: 'impact-drill-650w',
    sku: 'DEMO-DRILL',
    short_description: '13 mm impact drill for concrete and wood.',
    brand: { id: 1, name: 'DrillCo', slug: 'drillco' },
    category: { id: 10, name: 'Tools', slug: 'tools' },
    subcategory: { id: 11, name: 'Drills', slug: 'drills' },
    unit: 'piece',
    price: '3200.00',
    mrp: '4000.00',
    discount_percent: '20.00',
    discount_amount: '800.00',
    stock_status: 'in_stock',
    fast_delivery: true,
    variant_count: 1,
    default_variant_id: 101,
    is_featured: true,
    rating_avg: '4.50',
    rating_count: 12,
    image: null,
    image_alt: 'Impact Drill 650W',
    offer: null,
    ...overrides,
  }
}

export function variant(overrides: Partial<ProductVariant> = {}): ProductVariant {
  return {
    id: 201,
    sku: 'DEMO-WIRE-15-10',
    name: '1.5 sq mm × 10 m',
    attributes: { size: '1.5 sq mm', length: '10 m' },
    mrp: '500.00',
    price: '400.00',
    discount_percent: '20.00',
    discount_amount: '100.00',
    weight_grams: 450,
    length_mm: null,
    width_mm: null,
    height_mm: null,
    is_default: false,
    available_quantity: null,
    stock_status: 'in_stock',
    fast_delivery: true,
    ...overrides,
  }
}

/** An electrical wire sold in three lengths (each length is its own variant/SKU). */
export function wireDetail(overrides: Partial<ProductDetail> = {}): ProductDetail {
  const variants = [
    variant({ is_default: true }),
    variant({
      id: 202,
      sku: 'DEMO-WIRE-15-50',
      name: '1.5 sq mm × 50 m',
      attributes: { size: '1.5 sq mm', length: '50 m' },
      mrp: '2400.00',
      price: '1899.00',
      discount_percent: '20.88',
      discount_amount: '501.00',
      stock_status: 'low_stock',
      available_quantity: 3,
      fast_delivery: false,
    }),
    variant({
      id: 203,
      sku: 'DEMO-WIRE-15-90',
      name: '1.5 sq mm × 90 m',
      attributes: { size: '1.5 sq mm', length: '90 m' },
      mrp: '4100.00',
      price: '4100.00',
      discount_percent: '0.00',
      discount_amount: '0.00',
      stock_status: 'out_of_stock',
      fast_delivery: false,
    }),
  ]
  return {
    ...productSummary({
      id: 5,
      name: 'FR PVC Insulated Copper Wire',
      slug: 'fr-pvc-copper-wire',
      sku: 'DEMO-WIRE',
      brand: { id: 2, name: 'VoltLine', slug: 'voltline' },
      category: { id: 20, name: 'Electrical', slug: 'electrical' },
      subcategory: { id: 21, name: 'Wires & Cables', slug: 'wires-cables' },
      unit: 'coil',
      price: '400.00',
      mrp: '500.00',
      variant_count: 3,
      default_variant_id: 201,
      rating_avg: '4.00',
      rating_count: 3,
    }),
    description: 'Flame-retardant house wire.',
    tags: ['house wiring'],
    gst_rate: '18.00',
    hsn_code: '8544',
    max_order_quantity: 10,
    is_returnable: true,
    variants,
    specifications: [{ name: 'Conductor', key: 'conductor', value: 'Copper', unit: '', sort_order: 0 }],
    images: [],
    ...overrides,
  }
}

export const categories: Category[] = [
  {
    id: 20,
    name: 'Electrical',
    slug: 'electrical',
    description: '',
    image: null,
    sort_order: 0,
    product_count: 14,
    parent: null,
    parent_detail: null,
    is_active: true,
    children: [
      { id: 21, name: 'Wires & Cables', slug: 'wires-cables', description: '', image: null, sort_order: 0, product_count: 5 },
      { id: 22, name: 'Switches', slug: 'switches', description: '', image: null, sort_order: 1, product_count: 4 },
    ],
  },
  {
    id: 10,
    name: 'Tools',
    slug: 'tools',
    description: '',
    image: null,
    sort_order: 1,
    product_count: 9,
    parent: null,
    parent_detail: null,
    is_active: true,
    children: [{ id: 11, name: 'Drills', slug: 'drills', description: '', image: null, sort_order: 0, product_count: 3 }],
  },
]

type ChildSpec = [id: number, name: string, slug: string, count: number, cover?: string]

function department(id: number, name: string, slug: string, children: ChildSpec[], cover: string | null = null): Category {
  const kids = children.map(([cid, cname, cslug, count, ccover], i) => ({
    id: cid,
    name: cname,
    slug: cslug,
    description: '',
    image: null,
    cover_image: ccover ?? null,
    sort_order: i,
    product_count: count,
  }))
  return {
    id,
    name,
    slug,
    description: '',
    image: null,
    cover_image: cover ?? kids.find((k) => k.cover_image)?.cover_image ?? null,
    sort_order: id,
    product_count: kids.reduce((total, k) => total + k.product_count, 0),
    parent: null,
    parent_detail: null,
    is_active: true,
    children: kids,
  }
}

/** A slice of the shop's approved tree (backend apps/catalog/taxonomy.py) for the four header groups;
 * Workwear has no products, Electrical is not an approved department. */
export const approvedCategories: Category[] = [
  department(101, 'Plywood, MDF & HDHMR', 'plywood-mdf-hdhmr', [
    [111, 'Plywood', 'plywood', 6, '/media/products/plywood.jpg'],
    [112, 'MDF Boards', 'mdf', 2, '/media/products/mdf.jpg'],
  ]),
  department(102, 'Fevicol', 'fevicol', [[121, 'Wood Adhesives', 'fevicol-wood-adhesives', 3, '/media/products/fevicol.jpg']]),
  department(103, 'Hinges, Channels & Handles', 'hinges-channels-handles', [
    [131, 'Hinges', 'hinges', 5, '/media/products/hinge.jpg'],
    [132, 'Drawer Channels', 'drawer-channels', 2],
  ]),
  department(104, 'Door Locks & Hardware', 'door-locks-hardware', [[141, 'Door Locks', 'door-locks', 4, '/media/products/lock.jpg']]),
  department(105, 'Power Tools & Accessories', 'power-tools', [
    [151, 'Drills', 'drills', 3, '/media/products/drill.jpg'],
    [152, 'Drill Bits', 'drill-bits', 2],
  ]),
  department(106, 'General Hardware & Tools', 'general-hardware', [
    [161, 'Screwdrivers', 'screwdrivers', 2, '/media/products/screwdriver.jpg'],
    [162, 'Hammers', 'hammers', 1],
  ]),
  department(107, 'Safety Tools & Workwear', 'safety', [
    [171, 'Gloves', 'gloves', 2],
    [172, 'Workwear', 'workwear', 0],
  ]),
  department(20, 'Electrical', 'electrical', [[21, 'Switches', 'switches', 4]]),
]

export function productPage(results: ProductSummary[], count = results.length): ProductPage {
  return { count, next: null, previous: null, results }
}

export function facets(overrides: Partial<ProductFacets> = {}): ProductFacets {
  return {
    total: 2,
    categories: [
      { slug: 'wires-cables', name: 'Wires & Cables', count: 1 },
      { slug: 'switches', name: 'Switches', count: 1 },
    ],
    brands: [
      { slug: 'voltline', name: 'VoltLine', count: 2 },
      { slug: 'switchly', name: 'Switchly', count: 1 },
    ],
    price: { min: '99.00', max: '4100.00' },
    ratings: [
      { min: 4, count: 1 },
      { min: 3, count: 2 },
    ],
    discounts: [
      { min: 10, count: 2 },
      { min: 25, count: 0 },
      { min: 50, count: 0 },
    ],
    availability: { in_stock: 2, fast_delivery: 1 },
    specifications: [
      {
        key: 'cross_sectional_area',
        name: 'Cross-sectional area',
        unit: 'sq mm',
        values: [
          { value: '1.5', count: 1 },
          { value: '2.5', count: 1 },
        ],
      },
    ],
    ...overrides,
  }
}

export function cartLine(overrides: Partial<CartLine> = {}): CartLine {
  return {
    id: 9,
    variant_id: 201,
    sku: 'DEMO-WIRE-15-10',
    product_id: 5,
    product_name: 'FR PVC Insulated Copper Wire',
    product_slug: 'fr-pvc-copper-wire',
    variant_name: '1.5 sq mm × 10 m',
    quantity: 2,
    unit_price: '400.00',
    unit_mrp: '500.00',
    price_at_add: '400.00',
    price_changed: false,
    line_total: '800.00',
    line_mrp_total: '1000.00',
    discount_percent: '20.00',
    available_quantity: 30,
    in_stock: true,
    purchasable: true,
    brand_name: 'VoltLine',
    attributes: { size: '1.5 sq mm', length: '10 m' },
    max_order_quantity: 10,
    image: null,
    ...overrides,
  }
}

export function address(overrides: Partial<Address> = {}): Address {
  return {
    id: 31,
    name: 'Asha Kulkarni',
    phone: '9876543210',
    address_line1: '12 MG Road',
    address_line2: '',
    area: 'Kothrud',
    landmark: '',
    city: 'Pune',
    state: 'Maharashtra',
    postal_code: '411038',
    country: 'IN',
    latitude: null,
    longitude: null,
    address_type: 'home',
    business_name: '',
    gstin: '',
    is_default: true,
    created_at: '2026-09-20T10:00:00Z',
    updated_at: '2026-09-20T10:00:00Z',
    ...overrides,
  }
}

export const TOTALS_800 = {
  subtotal: '800.00',
  mrp_total: '1000.00',
  discount_total: '0.00',
  offer_discount: '0.00',
  coupon_discount: '0.00',
  delivery_fee: '0.00',
  tax_total: '122.03',
  grand_total: '800.00',
  savings_vs_mrp: '200.00',
}

export const NO_OFFERS = { applied: [], missed: [] }

/** A fast-delivery estimate from one store, as the fulfilment engine returns it. */
export function deliveryQuote(overrides: Partial<DeliveryQuote> = {}): DeliveryQuote {
  return {
    available: true,
    fee: '0.00',
    free_delivery_min_order: '499.00',
    amount_to_free_delivery: '0.00',
    fast_delivery_possible: true,
    eta_minutes: 38,
    message: '⚡ Fast delivery · Delivery in 38 minutes',
    delivery_type: 'fast',
    label: 'Delivery in 38 minutes',
    store_name: 'Demo Store — Kothrud',
    estimated_delivery_at: '2026-09-28T07:08:00Z',
    window_start: '2026-09-28T07:08:00Z',
    window_end: '2026-09-28T07:23:00Z',
    prep_minutes: 10,
    distance_km: 2.7,
    fast_unavailable_reason: '',
    location_precision: 'exact',
    reason_code: '',
    shipments: [
      {
        sequence: 1,
        store_name: 'Demo Store — Kothrud',
        store_area: 'Kothrud',
        line_count: 1,
        delivery_type: 'fast',
        eta_minutes: 38,
        label: 'Delivery in 38 minutes',
        distance_km: 2.7,
      },
    ],
    ...overrides,
  }
}

/** Fast delivery isn't possible right now: the next option is a standard delivery window. */
export function standardQuote(overrides: Partial<DeliveryQuote> = {}): DeliveryQuote {
  return deliveryQuote({
    fast_delivery_possible: false,
    eta_minutes: 1260,
    message: 'Standard delivery · Tomorrow, 10:00 AM – 12:00 PM',
    delivery_type: 'standard',
    label: 'Tomorrow, 10:00 AM – 12:00 PM',
    estimated_delivery_at: '2026-09-29T04:30:00Z',
    window_start: '2026-09-29T04:30:00Z',
    window_end: '2026-09-29T06:30:00Z',
    fast_unavailable_reason: 'No delivery partner is available right now.',
    shipments: [],
    ...overrides,
  })
}

export function undeliverableQuote(overrides: Partial<DeliveryQuote> = {}): DeliveryQuote {
  return deliveryQuote({
    available: false,
    fast_delivery_possible: false,
    eta_minutes: null,
    message: 'We don’t deliver to PIN 411014 yet.',
    delivery_type: null,
    label: '',
    store_name: null,
    estimated_delivery_at: null,
    window_start: null,
    window_end: null,
    prep_minutes: null,
    distance_km: null,
    location_precision: 'pin',
    reason_code: 'out_of_zone',
    shipments: [],
    ...overrides,
  })
}

export function orderDelivery(overrides: Partial<OrderDelivery> = {}): OrderDelivery {
  return {
    type: 'fast',
    type_label: 'Fast delivery',
    fast: true,
    eta_minutes: 38,
    minutes_left: 31,
    estimated_ready_at: '2026-09-24T10:10:00Z',
    estimated_delivery_at: '2026-09-24T10:38:00Z',
    window_start: '2026-09-24T10:38:00Z',
    window_end: '2026-09-24T10:53:00Z',
    label: 'Delivery in 31 minutes',
    ...overrides,
  }
}

/** An order placed before delivery estimates existed. */
export const NO_ESTIMATE: OrderDelivery = {
  type: null,
  type_label: null,
  fast: false,
  eta_minutes: null,
  minutes_left: null,
  estimated_ready_at: null,
  estimated_delivery_at: null,
  window_start: null,
  window_end: null,
  label: '',
}

export function checkoutPreview(overrides: Partial<CheckoutPreview> = {}): CheckoutPreview {
  return {
    cart: cart({ items: [cartLine()], totals: TOTALS_800, can_checkout: true }),
    totals: TOTALS_800,
    address_id: 31,
    coupon: null,
    coupon_error: null,
    delivery: deliveryQuote(),
    offers: NO_OFFERS,
    blocking_issues: [],
    can_place_order: true,
    payment_methods: [
      { value: 'online', label: 'Mock online payment (development — no real money)', test_mode: true },
      { value: 'cod', label: 'Cash on delivery', test_mode: false },
    ],
    ...overrides,
  }
}

export function orderDetail(overrides: Partial<OrderDetail> = {}): OrderDetail {
  return {
    order_number: 'OD260924ABCDEF',
    public_id: '7a1c3b0e-0000-4000-8000-000000000001',
    status: 'confirmed',
    payment_method: 'cod',
    payment_status: 'pending',
    address_snapshot: {
      name: 'Asha Kulkarni',
      phone: '9876543210',
      address_line1: '12 MG Road',
      address_line2: '',
      area: 'Kothrud',
      landmark: '',
      city: 'Pune',
      state: 'Maharashtra',
      postal_code: '411038',
      address_type: 'home',
    },
    store_name: 'Demo Store',
    subtotal: '800.00',
    mrp_total: '1000.00',
    discount_total: '0.00',
    offer_discount: '0.00',
    coupon_discount: '0.00',
    applied_offers: [],
    delivery_fee: '0.00',
    tax_total: '122.03',
    grand_total: '800.00',
    coupon_code: '',
    customer_note: '',
    estimated_delivery_at: '2026-09-24T10:38:00Z',
    eta_minutes: 38,
    delivery_message: '⚡ Delivery in 31 minutes (by about 4:08 PM)',
    delivery: orderDelivery(),
    shipments: [
      {
        sequence: 1,
        store_name: 'Demo Store',
        store_area: 'Kothrud',
        status: 'pending',
        status_label: 'Waiting for a delivery partner',
        delivery_attempts: 0,
        picked_up_at: null,
        out_for_delivery_at: null,
        delivered_at: null,
        rider: null,
        delivery_code: null,
        failure: null,
        proof_available: false,
        received_by: '',
        amount_to_pay: null,
        delivery_type: 'fast',
        distance_km: '2.70',
        prep_minutes: 10,
        eta_minutes: 38,
        estimated_ready_at: '2026-09-24T10:10:00Z',
        estimated_delivery_at: '2026-09-24T10:38:00Z',
        window_start: '2026-09-24T10:38:00Z',
        window_end: '2026-09-24T10:53:00Z',
        item_ids: [1],
      },
    ],
    cancellation_reason: '',
    cancelled_at: null,
    delivered_at: null,
    created_at: '2026-09-24T10:00:00Z',
    can_cancel: true,
    can_retry_payment: false,
    can_return: false,
    return_window_ends_at: null,
    can_reorder: true,
    items: [
      {
        id: 1,
        product: 5,
        product_slug: 'fr-pvc-copper-wire',
        variant: 201,
        product_name: 'FR PVC Insulated Copper Wire',
        variant_name: '1.5 sq mm × 10 m',
        sku: 'DEMO-WIRE-15-10',
        brand_name: 'VoltLine',
        unit: 'coil',
        unit_mrp: '500.00',
        unit_price: '400.00',
        gst_rate: '18.00',
        quantity: 2,
        line_total: '800.00',
        offer_discount: '0.00',
        image: null,
        returnable_quantity: 0,
        returned_quantity: 0,
      },
    ],
    status_history: [
      { from_status: '', to_status: 'pending', note: 'Order placed', created_at: '2026-09-24T10:00:00Z' },
      { from_status: 'pending', to_status: 'confirmed', note: 'Cash on delivery order confirmed', created_at: '2026-09-24T10:00:01Z' },
    ],
    payments: [
      {
        public_id: 'pay-cod-1',
        provider: 'cod',
        method: 'cod',
        amount: '800.00',
        currency: 'INR',
        status: 'pending',
        failure_reason: '',
        captured_at: null,
        created_at: '2026-09-24T10:00:00Z',
        client_payload: {},
      },
    ],
    refunds: [],
    returns: [],
    ...overrides,
  }
}

/** An online order waiting at the mock gateway. */
export function pendingOnlineOrder(overrides: Partial<OrderDetail> = {}): OrderDetail {
  return orderDetail({
    status: 'pending',
    payment_method: 'online',
    payment_status: 'pending',
    delivery_message: 'Complete the payment to confirm your order.',
    status_history: [{ from_status: '', to_status: 'pending', note: 'Order placed', created_at: '2026-09-24T10:00:00Z' }],
    payments: [
      {
        public_id: 'pay-mock-1',
        provider: 'mock',
        method: 'unknown',
        amount: '800.00',
        currency: 'INR',
        status: 'created',
        failure_reason: '',
        captured_at: null,
        created_at: '2026-09-24T10:00:00Z',
        client_payload: { mock: true, notice: 'Development mock payment. No real money is charged.', mock_signature: 'sig-1' },
      },
    ],
    ...overrides,
  })
}

export function cart(overrides: Partial<Cart> = {}): Cart {
  return {
    id: 1,
    items: [],
    totals: {
      subtotal: '0.00',
      mrp_total: '0.00',
      discount_total: '0.00',
      offer_discount: '0.00',
      coupon_discount: '0.00',
      delivery_fee: '0.00',
      tax_total: '0.00',
      grand_total: '0.00',
      savings_vs_mrp: '0.00',
    },
    offers: NO_OFFERS,
    issues: [],
    can_checkout: false,
    ...overrides,
  }
}
