/** Shapes returned by the catalog API (money and ratings are decimal strings). */

export type StockStatus = 'in_stock' | 'low_stock' | 'out_of_stock'

export interface NamedRef {
  id: number
  name: string
  slug: string
}

export interface ProductSummary {
  id: number
  name: string
  slug: string
  sku: string
  short_description: string
  brand: NamedRef | null
  category: NamedRef
  subcategory: NamedRef | null
  unit: string
  price: string | null
  mrp: string | null
  discount_percent: string | null
  discount_amount: string | null
  stock_status: StockStatus
  fast_delivery: boolean
  variant_count: number
  default_variant_id: number | null
  is_featured: boolean
  rating_avg: string
  rating_count: number
  image: string | null
  image_alt: string
  /** Live automatic offer for this product; the discount itself is applied in the cart. */
  offer: ProductOffer | null
  /** Bulk (quantity) prices exist for this product: from how many units, and the lowest unit price. */
  bulk_pricing?: BulkPricingSummary | null
  /** Search results only: why this product is here when the words alone do not explain it. */
  match_reason?: string
  match_type?: 'keyword' | 'related' | 'semantic'
}

export interface ProductOffer {
  id: number
  name: string
  badge: string
  min_order_value: string
  benefit?: 'discount' | 'free_delivery'
  min_quantity?: number
  /** Festival/campaign label, e.g. "Diwali". */
  campaign?: string
  /** Conditions in words ("Buy 10 or more of an item", "First order only"). */
  conditions?: string[]
}

export interface BulkPricingSummary {
  from_quantity: number | null
  lowest_unit_price: string
}

/** One row of a variant's bulk price table (the first row is the normal price). */
export interface PriceTier {
  min_quantity: number
  /** null for the last tier ("50+"). */
  max_quantity: number | null
  unit_price: string
  saving_percent: string
  is_base: boolean
}

export interface ProductOption {
  slug: string
  name: string
  unit: string
  values: { slug: string; value: string }[]
}

export interface ProductVariant {
  id: number
  sku: string
  name: string
  attributes: Record<string, string | number>
  mrp: string
  price: string
  discount_percent: string
  discount_amount: string
  weight_grams: number | null
  length_mm: number | null
  width_mm: number | null
  height_mm: number | null
  is_default: boolean
  /** Only present when stock is low ("only 3 left"); otherwise null. */
  available_quantity: number | null
  stock_status: StockStatus
  fast_delivery: boolean
  /** Bulk prices (empty when the variant has none). Display only: the cart charges the price. */
  price_tiers?: PriceTier[]
  /** {option_type_slug: value_slug}, e.g. {grade: '53-grade', 'bag-size': '50-kg'}. */
  options?: Record<string, string>
}

export interface ProductSpecification {
  name: string
  key: string
  value: string
  unit: string
  sort_order: number
}

export interface ProductImage {
  id: number
  image: string
  alt_text: string
  variant: number | null
  is_primary: boolean
  sort_order: number
}

export interface ProductDetail extends ProductSummary {
  description: string
  tags: string[]
  gst_rate: string
  hsn_code: string
  max_order_quantity: number
  is_returnable: boolean
  launch_date?: string | null
  variants: ProductVariant[]
  specifications: ProductSpecification[]
  images: ProductImage[]
  /** Option types the variants differ by (Grade, Bag size…); empty for simple products. */
  options?: ProductOption[]
  /** From the department down to the product's most specific category. */
  breadcrumb?: NamedRef[]
}

/** GET /products/{slug}/quote/: what a quantity costs, from the shop's pricing engine (preview). */
export interface PriceQuote {
  product_id: number
  variant_id: number
  sku: string
  options: Record<string, string>
  quantity: number
  mrp: string
  base_unit_price: string
  unit_price: string
  applied_tier: { min_quantity: number } | null
  next_tier: { min_quantity: number; unit_price: string; units_more: number; reachable: boolean } | null
  price_tiers: PriceTier[]
  line_total: string
  bulk_saving: string
  offer_discount: string
  offers: { name: string; badge: string }[]
  total: string
  savings_vs_mrp: string
  stock_status: StockStatus
  within_stock: boolean
  max_order_quantity: number
  note: string
}

export interface Collection {
  id: number
  name: string
  slug: string
  description: string
  rule: 'manual' | 'best_sellers' | 'new_launches' | 'bulk_pricing'
  starts_at: string | null
  ends_at: string | null
  products: ProductSummary[]
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface ProductPage extends Paginated<ProductSummary> {
  search?: {
    query: string
    matched: 'all_terms' | 'some_terms' | 'related'
    /** `hybrid` when related words / meaning were used; absent for plain keyword search. */
    mode?: 'hybrid'
    related_terms?: string[]
  }
}

export interface SubCategory {
  id: number
  name: string
  slug: string
  description: string
  image: string | null
  sort_order: number
  product_count: number | null
  /** Third level (Phase 15), e.g. Cement › Grey Cement. Empty at the deepest level. */
  children?: SubCategory[]
}

export interface Category extends SubCategory {
  parent: number | null
  parent_detail: NamedRef | null
  is_active: boolean
  children: SubCategory[]
  /** 1 = department / top level, 2 = category, 3 = subcategory. */
  level?: number
  breadcrumb?: NamedRef[]
}

export interface Brand {
  id: number
  name: string
  slug: string
  logo: string | null
  description: string
}

export interface FacetOption {
  slug: string
  name: string
  count: number
}

export interface SpecFacet {
  key: string
  name: string
  unit: string
  values: { value: string; count: number }[]
}

export interface ProductFacets {
  total: number
  categories: FacetOption[]
  brands: FacetOption[]
  price: { min: string | null; max: string | null }
  ratings: { min: number; count: number }[]
  discounts: { min: number; count: number }[]
  availability: { in_stock: number; fast_delivery: number }
  specifications: SpecFacet[]
  /** Structured options (Grade, Bag size…) with counts; filters use `opt_<slug>=value-slug`. */
  options?: { slug: string; name: string; values: { slug: string; value: string; count: number }[] }[]
}

export interface Review {
  id: number
  rating: number
  title: string
  body: string
  author: string
  is_verified_purchase: boolean
  created_at: string
}
