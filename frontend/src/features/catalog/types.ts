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
  /** Search results only: why this product is here when the words alone do not explain it. */
  match_reason?: string
  match_type?: 'keyword' | 'related' | 'semantic'
}

export interface ProductOffer {
  id: number
  name: string
  badge: string
  min_order_value: string
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
  variants: ProductVariant[]
  specifications: ProductSpecification[]
  images: ProductImage[]
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
}

export interface Category extends SubCategory {
  parent: number | null
  parent_detail: NamedRef | null
  is_active: boolean
  children: SubCategory[]
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
