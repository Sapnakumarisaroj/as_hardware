import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { api } from '@/lib/api/client'

/** Phase 17 wallet: every amount is calculated by the server from the credit ledger. */
export interface Wallet {
  balance: string
  spendable: string
  /** Earned on orders not delivered yet. */
  pending: string
  /** Delivered; usable once the return window ends. */
  eligible: string
  earned: string
  restored: string
  used: string
  expired: string
  reversed: string
  expiring_soon: { amount: string; first_expiry: string | null; within_days: number }
  rules: {
    enabled: boolean
    max_order_share: string
    expiry_days: number
    never_cash: boolean
    referral_reward: string
    referee_reward: string
  }
  referral: { code: string; rewards_on: boolean; joined: number; rewarded: number; used_code: boolean }
}

export type CreditKind = 'cashback' | 'promo' | 'referral' | 'restore' | 'redemption' | 'expiry'
export type CreditStatus = 'pending' | 'eligible' | 'available' | 'expired' | 'reversed' | 'posted'

export interface CreditEntry {
  id: number
  kind: CreditKind
  kind_label: string
  status: CreditStatus
  status_label: string
  /** Positive = credit, negative = used or expired. */
  amount: string
  /** For credits still usable: what is left of them. */
  remaining: string | null
  available_at: string | null
  expires_at: string | null
  order_number: string | null
  reference: string
  description: string
  created_at: string
}

export interface LedgerPage {
  count: number
  next: string | null
  previous: string | null
  results: CreditEntry[]
}

export const loyaltyKeys = {
  wallet: ['loyalty', 'wallet'] as const,
  ledger: (params: Record<string, string>) => ['loyalty', 'ledger', params] as const,
}

export function useWallet() {
  const { status } = useAuth()
  return useQuery({
    queryKey: loyaltyKeys.wallet,
    queryFn: async () => (await api.get<Wallet>('/loyalty/wallet/')).data,
    enabled: status === 'authenticated',
  })
}

export function useLedger(params: Record<string, string>) {
  const { status } = useAuth()
  return useQuery({
    queryKey: loyaltyKeys.ledger(params),
    queryFn: async () => (await api.get<LedgerPage>('/loyalty/ledger/', { params })).data,
    enabled: status === 'authenticated',
    placeholderData: keepPreviousData,
  })
}

export function useClaimReferral() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (code: string) => (await api.post<{ referrer: string }>('/loyalty/referral/', { code })).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: loyaltyKeys.wallet }),
  })
}
