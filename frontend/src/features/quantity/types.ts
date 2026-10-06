import type { BreakdownStep, ProjectKit, ProjectLanguage, ProjectQuestion } from '@/features/projects/types'

export interface QuantityCalculator {
  key: string
  name: string
  summary: string
  examples: string[]
  risky: boolean
}

export interface QuantityStatus {
  calculators: QuantityCalculator[]
  ai: { available: boolean }
  pack_rule: 'lowest_cost' | 'fewest_packs'
  label: string
}

/** A number with the unit it was typed in ("5" + "m"); the server converts it. */
export interface AnswerInput {
  value: string
  unit?: string
}

export interface QuantityOverride {
  variant_id?: number
  quantity?: number
  included?: boolean
}

export interface QuantityMaterial {
  key: string
  label: string
  need: { amount: number; unit: string; unit_label: string }
  is_estimate: boolean
  is_optional: boolean
  steps: BreakdownStep[]
  recommended: string
  covers: number | null
  extra: number | null
  found: boolean
  explanation: string
  item_keys: string[]
}

export interface QuantityResult {
  text: string
  language: ProjectLanguage
  label: string
  understood_by: '' | 'rules' | 'ai' | 'chosen'
  ai: { available: boolean; used: boolean; notice: string }
  calculators: QuantityCalculator[]
  calculator: string | null
  message?: string
  name?: string
  summary?: string
  title?: string
  answers?: Record<string, string | number>
  from_description?: string[]
  from_ai?: string[]
  interpretations?: { key: string; text: string }[]
  questions?: ProjectQuestion[]
  missing?: string[]
  assumptions?: { key: string; value: string | number; text: string }[]
  complete: boolean
  safety?: string[]
  professional?: string
  verify?: string
  not_sold?: string
  estimate_notice?: string
  materials?: QuantityMaterial[]
  kit?: ProjectKit | null
}

export interface QuantityRequest {
  text?: string
  calculator?: string
  answers?: Record<string, string | number | { value: number; unit: string }>
  language?: ProjectLanguage
  overrides?: Record<string, QuantityOverride>
  coupon?: string
  postal_code?: string
}
