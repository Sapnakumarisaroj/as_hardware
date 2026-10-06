import type { ProductSummary } from '@/features/catalog/types'

export type Verdict = 'COMPATIBLE' | 'POSSIBLY_COMPATIBLE' | 'NOT_COMPATIBLE' | 'INSUFFICIENT_INFORMATION'

export interface CompatibilityCheckItem {
  name: string
  status: 'pass' | 'fail' | 'missing' | 'warn'
  detail: string
}

export interface CompatibilityOption {
  product_id: number
  variant_id: number | null
  verdict: Verdict
  reason: string
  product?: ProductSummary | null
}

export interface CompatibilityResult {
  verdict: Verdict
  reason: string
  product_a: { id: number; name: string; slug: string; kind: string | null; card?: ProductSummary | null }
  product_b: { id: number; name: string; slug: string; kind: string | null; card?: ProductSummary | null }
  variant_a: number | null
  variant_b: number | null
  checks: CompatibilityCheckItem[]
  matching_variants: { a: number | null; b: number | null; label: string }[]
  sources: string[]
  options: CompatibilityOption[]
}

/** A pair of lines (project kit, quantity result, cart) that may not work together. */
export interface CompatibilityProblem extends CompatibilityResult {
  keys?: (number | string)[]
  cart_item_ids?: number[]
  message: string
}

export interface AccessoryRow {
  product_id: number
  variant_id?: number | null
  note: string
  source: 'shop' | 'rules'
  verdict: Verdict | null
  reason: string
  product: ProductSummary
}

export interface ProductCompatibility {
  product_id: number
  kind: string | null
  groups: { required: AccessoryRow[]; compatible: AccessoryRow[]; accessories: AccessoryRow[]; alternatives: AccessoryRow[] }
}
