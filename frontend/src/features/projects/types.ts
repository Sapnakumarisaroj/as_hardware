import type { RecommendedProduct } from '@/features/ai/types'

export type ProjectLanguage = 'en' | 'hi' | 'hinglish'
export type ProjectStatus = 'draft' | 'ready' | 'ordered' | 'archived'
export type AnswerValue = string | number

export interface ProjectQuestion {
  key: string
  kind: 'number' | 'choice'
  text: string
  unit: string
  min: number
  max: number
  choices: { value: string; label: string }[]
  default: AnswerValue | null
}

export interface ProjectType {
  key: string
  name: string
  summary: string
  first_question: ProjectQuestion | null
}

export interface KitLinePrice {
  unit_price: string
  base_unit_price: string
  applied_tier: { min_quantity: number } | null
  next_tier: { min_quantity: number; unit_price: string; units_more: number } | null
  line_total: string
  bulk_saving: string
  offer_discount: string
}

export type KitProblem = '' | 'not_found' | 'unavailable' | 'too_many' | 'short_stock'

export interface KitItem {
  id: number
  material_key: string
  label: string
  rationale: string
  note: string
  status: 'found' | 'not_found'
  need: { amount: number | null; unit: string }
  pack_amount: number | null
  size_known: boolean
  suggested: { variant_id: number | null; quantity: number | null }
  alternatives: RecommendedProduct[]
  added_by_customer: boolean
  is_optional: boolean
  is_estimate: boolean
  included: boolean
  customer_set: boolean
  quantity: number
  unit: string
  product_id: number | null
  product: RecommendedProduct | null
  variant: { id: number; sku: string; name: string; options: { type: string; value: string }[]; price: string; mrp: string } | null
  problem: KitProblem
  stock_available: number
  price: KitLinePrice | null
}

export interface ProjectKit {
  items: KitItem[]
  postal_code: string
  totals: {
    item_count: number
    mrp_total: string
    subtotal: string
    bulk_savings: string
    offer_discount: string
    delivery_fee: string
    tax_included: string
    grand_total: string
    savings_vs_mrp: string
  }
  offers: { name: string; discount: string }[]
  offers_in_reach: { name: string; description: string; min_order_value: string }[]
  delivery: {
    checked: boolean
    available: boolean
    message: string
    label: string
    delivery_type: 'fast' | 'standard' | null
    eta_minutes: number | null
    fee: string
    free_delivery_reason: string
    amount_to_free_delivery: string
    free_delivery_hint: string
    shipments: { sequence: number; store_name: string; label: string }[]
  }
  issues: { item_id: number | null; code: string; message: string }[]
  can_add_to_cart: boolean
  not_found_count: number
  included_count: number
}

export interface ProjectPlan {
  id: number
  title: string
  project_type: string
  type_name: string
  status: ProjectStatus
  description: string
  language: ProjectLanguage
  summary: string
  answers: Record<string, AnswerValue>
  from_description: string[]
  questions: ProjectQuestion[]
  missing: string[]
  assumptions: { key: string; value: AnswerValue; text: string }[]
  complete: boolean
  safety: string[]
  professional: string
  not_sold: string
  estimate_notice: string
  created_at: string
  updated_at: string
  kit: ProjectKit | null
  added?: { added_lines: number; added_units: number }
}

export interface ProjectSummary {
  id: number
  title: string
  project_type: string
  type_name: string
  status: ProjectStatus
  item_count: number
  created_at: string
  updated_at: string
}
