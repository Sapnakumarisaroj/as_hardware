/** Shapes of the voice shopping API (/api/ai/voice/…). Prices and products come from the server. */

import type { RecommendedProduct } from '@/features/ai/types'

export type VoiceLanguage = 'en' | 'hi' | 'hinglish'

export interface VoiceLanguageOption {
  code: VoiceLanguage
  label: string
  /** What the browser listens for (BCP 47), e.g. hi-IN. */
  speech: string
  /** The voice that reads the answer. */
  voice: string
}

export interface ServerSpeech {
  provider: string
  model: string
  enabled: boolean
  available: boolean
}

export interface VoiceStatus {
  languages: VoiceLanguageOption[]
  examples: Record<VoiceLanguage, string[]>
  browser_recognition: boolean
  server_recognition: ServerSpeech
  server_voice: ServerSpeech
  max_audio_bytes: number
  max_audio_seconds: number
  max_lines: number
  max_speak_chars: number
}

export type VoiceIntent = 'add_to_cart' | 'set_quantity' | 'confirm' | 'cancel' | 'navigate' | 'search' | 'ask' | 'unclear' | 'quantity'

export type VoiceLineStatus = 'ready' | 'not_found' | 'too_many' | 'short_stock' | 'unavailable' | 'whole_number'

export interface VoiceQuote {
  quantity: number
  sku: string
  options: Record<string, string>
  mrp: string
  base_unit_price: string
  unit_price: string
  applied_tier: { min_quantity: number } | null
  next_tier: { min_quantity: number; unit_price: string; units_more: number; reachable: boolean } | null
  line_total: string
  bulk_saving: string
  offer_discount: string
  offers: { name: string; badge: string }[]
  total: string
  stock_status: string
  within_stock: boolean
  max_order_quantity: number
}

export interface VoiceLine {
  heard: string
  query: string
  quantity: number | null
  quantity_given: boolean
  spoken_unit: string
  status: VoiceLineStatus
  match: 'exact' | 'closest' | ''
  message: string
  note: string
  product_id: number | null
  variant_id: number | null
  product_name: string
  unit: string
  filters: { param: string; value: string; label: string }[]
  quote: VoiceQuote | null
  product: RecommendedProduct | null
  alternatives: RecommendedProduct[]
}

export interface VoiceResult {
  conversation_id: number | null
  transcript: string
  language: VoiceLanguage
  intent: VoiceIntent
  reply: string
  speech: string
  lines: VoiceLine[]
  products: RecommendedProduct[]
  navigate: { page: string; path: string } | null
  search_path: string
  needs_confirmation: boolean
  add_now: boolean
  ai_mode: string
  questions: string[]
  notice: string
  /** Phase 20: a quantity request ("500 sq ft plastering"), worked out by Quantity AI. */
  quantity?: { calculator: string; title: string; complete: boolean; path: string } | null
}

/** A line shown and waiting for "yes" (sent back so the server can price it again). */
export interface PendingLine {
  product_id: number
  variant_id: number
  quantity: number
  name: string
}

export interface VoiceTranscript {
  text: string
  language: string
  confidence: number | null
  duration: number | null
  empty: boolean
}

export interface VoiceSession {
  id: number
  title: string
  language: VoiceLanguage
  turns: number
  created_at: string
  updated_at: string
}
