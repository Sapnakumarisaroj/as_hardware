import type { User } from '@/features/auth/api'
import type { Cart } from '@/features/cart/api'
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

export function cart(overrides: Partial<Cart> = {}): Cart {
  return {
    id: 1,
    items: [],
    totals: {
      subtotal: '0.00',
      mrp_total: '0.00',
      discount_total: '0.00',
      delivery_fee: '0.00',
      tax_total: '0.00',
      grand_total: '0.00',
      savings_vs_mrp: '0.00',
    },
    issues: [],
    can_checkout: false,
    ...overrides,
  }
}
