import type { CompatibilityResult, Verdict } from '@/features/compatibility/types'
/** Shapes of the AI assistant API (/api/ai/…). Product cards carry catalogue rows; nothing is made up here. */

import type { ProductSummary } from '@/features/catalog/types'

export type AssistantLanguage = 'en' | 'hi' | 'hinglish'

export interface AssistantStatus {
  ai_mode: 'basic' | 'llm'
  provider: string
  model: string
  languages: AssistantLanguage[]
  suggested_prompts: Record<AssistantLanguage, string[]>
  greeting: Record<AssistantLanguage, string>
  max_products: number
}

/** A catalogue listing row plus why the assistant picked it. */
export interface RecommendedProduct extends ProductSummary {
  variant_id: number | null
  reason: string
}

export type AssistantAction =
  | { type: 'add_to_cart'; variant_id: number; product_id: number; quantity: number }
  | { type: 'add_all'; label: string; variant_ids: number[] }

export interface AssistantMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
  products: RecommendedProduct[]
  questions: string[]
  actions: AssistantAction[]
  intent: string
  ai_mode: 'basic' | 'llm' | ''
  notice: string
  knowledge: { title: string; text: string; source?: string }[]
  safety: string[]
  estimate: { kind: string; text: string; is_estimate: boolean; calculator_path?: string } | null
  /** Phase 21: the compatibility engine's verdict for a "will this work with that?" question. */
  compatibility?: (Partial<CompatibilityResult> & { verdict: Verdict | null; explained_by_ai?: boolean }) | null
}

export interface ConversationSummary {
  id: number
  kind: string
  language: AssistantLanguage
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface Conversation extends ConversationSummary {
  messages: AssistantMessage[]
}

export interface Turn {
  conversation_id: number
  title: string
  user_message: AssistantMessage
  assistant_message: AssistantMessage
}
