import type { ProductSummary } from '@/features/catalog/types'
import type { CompatibilityOption } from '@/features/compatibility/types'
import type { ProjectKit, ProjectLanguage, ProjectQuestion } from '@/features/projects/types'

export interface RecommendationRow {
  product_id: number
  reason: string
  variant_id: number | null
  verdict: string | null
  orders?: number
  saving_each?: string
  product: ProductSummary
}

export interface BundleSummary {
  id: number
  slug: string
  name: string
  kind: string
  kind_label: string
  description: string
  promo_label: string
  savings: { vs_mrp: string; bulk: string; offers: string }
  valid: boolean
  item_count: number
  total: string
  subtotal: string
  product_ids: number[]
}

export interface Recommendations {
  product_id?: number
  personal?: boolean
  groups: Record<string, RecommendationRow[]>
  titles: Record<string, string>
  bundles?: BundleSummary[]
}

export type SmartAction = 'add' | 'replace' | 'remove' | 'set_quantity' | 'apply_bundle' | 'view' | null

export interface SmartSuggestion {
  type: string
  message: string
  action: SmartAction
  priority: number
  product_id?: number | null
  variant_id?: number | null
  quantity?: number
  cart_item_id?: number
  saving?: string
  price?: { unit_price: string; line_total: string } | null
  options?: CompatibilityOption[]
  bundle?: { slug: string; name: string; missing: number[] }
  code?: string
  applicable?: boolean
  budget?: string
  total?: string
  remaining?: string
  over?: boolean
  gap?: string
  product?: ProductSummary | null
}

export interface SmartCart {
  empty: boolean
  summary: { subtotal: string; grand_total: string; bulk_savings: string; offer_discount: string; delivery: ProjectKit['delivery'] } | null
  sections: { key: string; title: string; items: SmartSuggestion[] }[]
  top_actions: SmartSuggestion[]
  titles: Record<string, string>
}

export interface BudgetPlan {
  text: string
  language: ProjectLanguage
  budget: string | null
  complete: boolean
  message?: string
  calculator?: string
  name?: string
  answers?: Record<string, string | number>
  questions?: ProjectQuestion[]
  missing?: string[]
  assumptions?: { key: string; value: string | number; text: string }[]
  verify?: string
  kit?: ProjectKit
  total?: string
  remaining?: string
  within_budget?: boolean
  swapped?: { key: string; label: string; from: string; to: string; saving: string; reason: string }[]
  dropped?: { key: string; label: string; reason: string }[]
  full_kit_total?: string
  full_kit_over_budget?: boolean
  savings?: { vs_mrp: string; bulk: string; offers: string }
  unavailable?: string[]
  cheaper_options?: { key: string; product_id: number; reason: string; product: ProductSummary }[]
  premium_options?: { key: string; product_id: number; reason: string; extra_cost: string; product: ProductSummary }[]
  best_for_budget?: { product_id: number; reason: string; product: ProductSummary }[]
}

export interface BundleDetail {
  id: number
  slug: string
  name: string
  kind: string
  kind_label: string
  description: string
  promo_label: string
  kit: ProjectKit
  savings: { vs_mrp: string; bulk: string; offers: string }
  valid: boolean
}

export interface BundleOverride {
  variant_id?: number
  quantity?: number
  included?: boolean
}
