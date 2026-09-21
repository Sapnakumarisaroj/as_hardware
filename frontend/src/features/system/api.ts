import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api/client'

export interface HealthResponse {
  status: 'ok' | 'degraded'
  app: string
  version: string
  database: 'ok' | 'unavailable'
}

export const systemKeys = {
  health: ['system', 'health'] as const,
}

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>('/health/')
  return data
}

export function useHealth() {
  return useQuery({ queryKey: systemKeys.health, queryFn: fetchHealth, refetchInterval: 60_000 })
}
