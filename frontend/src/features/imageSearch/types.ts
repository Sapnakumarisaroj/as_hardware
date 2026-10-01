/** Shapes of the photo search API (Phase 14). Products are ordinary catalogue cards from the server. */

import type { RecommendedProduct } from '@/features/ai/types'

export interface ImageSearchStatus {
  enabled: boolean
  available: boolean
  provider: string
  model: string
  calibrated: boolean
  max_bytes: number
  max_megabytes: number
  accepted_types: string[]
}

export type ImageSearchOutcome = 'identified' | 'uncertain' | 'not_hardware' | 'no_match' | 'unavailable'

export interface Identification {
  label: string
  confidence: number
  percent: number
  level: 'high' | 'medium' | 'low'
  /** True when the percentage is a real probability (CLIP); false for an AI model's own estimate. */
  calibrated: boolean
  description: string
}

export interface ImageProduct extends RecommendedProduct {
  match_label?: string
  match_confidence?: number
}

export interface ImageSearchResult {
  /** Saved search id (signed-in customers only). */
  id: number | null
  status: ImageSearchOutcome
  status_text: string
  explanation: string
  identification: Identification | null
  alternatives: { label: string; confidence: number; percent: number; search: string }[]
  search_query: string
  notice: string
  ai: { mode: 'vision' | 'unavailable'; provider: string; model: string; calibrated?: boolean }
  image: { format?: string; width?: number; height?: number; bytes?: number; fingerprint?: string }
  products: ImageProduct[]
  created_at?: string
}

export interface ImageSearchHistoryRow {
  id: number
  title: string
  status: ImageSearchOutcome
  label: string
  percent: number | null
  product_count: number
  created_at: string
}
