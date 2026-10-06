import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { cartKeys } from '@/features/cart/api'
import type { Paginated } from '@/features/catalog/types'
import { api } from '@/lib/api/client'

import type { AnswerValue, ProjectLanguage, ProjectPlan, ProjectSummary, ProjectType } from './types'

export const projectKeys = {
  types: (language: ProjectLanguage) => ['projects', 'types', language] as const,
  list: ['projects', 'list'] as const,
  plan: (id: number, pin: string) => ['projects', 'plan', id, pin] as const,
  planAll: (id: number) => ['projects', 'plan', id] as const,
}

export function useProjectTypes(language: ProjectLanguage = 'en') {
  return useQuery({
    queryKey: projectKeys.types(language),
    queryFn: async () => (await api.get<{ results: ProjectType[] }>('/ai/project-types/', { params: { language } })).data.results,
    staleTime: 60 * 60_000,
  })
}

export function useProjects() {
  const { status } = useAuth()
  return useQuery({
    queryKey: projectKeys.list,
    queryFn: async () => (await api.get<Paginated<ProjectSummary>>('/ai/projects/', { params: { page_size: 20 } })).data,
    enabled: status === 'authenticated',
  })
}

/** The plan with its kit priced live (tiers, offers, stock, delivery to the PIN when given). */
export function useProject(id: number, pin: string) {
  const { status } = useAuth()
  return useQuery({
    queryKey: projectKeys.plan(id, pin),
    queryFn: async () =>
      (await api.get<ProjectPlan>(`/ai/projects/${id}/`, { params: pin ? { postal_code: pin } : {} })).data,
    enabled: status === 'authenticated' && Number.isFinite(id),
  })
}

export interface StartInput {
  description?: string
  project_type?: string
  language?: ProjectLanguage
  answers?: Record<string, AnswerValue>
}

export function useStartProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: StartInput) => (await api.post<ProjectPlan>('/ai/projects/', input)).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: projectKeys.list }),
  })
}

/** Every change returns the whole plan again; it replaces the cached one for this PIN. */
function usePlanMutation<TVars>(id: number, pin: string, request: (vars: TVars) => Promise<ProjectPlan>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: (plan) => {
      // Copies priced for another PIN are out of date; this one is the answer itself (no refetch).
      void queryClient.invalidateQueries({ queryKey: projectKeys.planAll(id), refetchType: 'none' })
      queryClient.setQueryData(projectKeys.plan(id, pin), plan)
      void queryClient.invalidateQueries({ queryKey: projectKeys.list })
    },
  })
}

const withPin = (pin: string) => (pin ? { postal_code: pin } : {})

export function useAnswerProject(id: number, pin: string) {
  return usePlanMutation(id, pin, async (vars: { answers?: Record<string, AnswerValue | null>; title?: string; language?: ProjectLanguage }) =>
    (await api.patch<ProjectPlan>(`/ai/projects/${id}/`, { ...vars, ...withPin(pin) })).data,
  )
}

export function useChangeItem(id: number, pin: string) {
  return usePlanMutation(id, pin, async (vars: { itemId: number; variant_id?: number; quantity?: number; included?: boolean }) => {
    const { itemId, ...body } = vars
    return (await api.patch<ProjectPlan>(`/ai/projects/${id}/items/${itemId}/`, { ...body, ...withPin(pin) })).data
  })
}

export function useRemoveItem(id: number, pin: string) {
  return usePlanMutation(id, pin, async (itemId: number) => (await api.delete<ProjectPlan>(`/ai/projects/${id}/items/${itemId}/`, { params: withPin(pin) })).data)
}

export function useResetProject(id: number, pin: string) {
  return usePlanMutation(id, pin, async () => (await api.post<ProjectPlan>(`/ai/projects/${id}/reset/`, withPin(pin))).data)
}

/** All ticked lines into the cart, or nothing (the server checks every line first). */
export function useAddProjectToCart(id: number, pin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<ProjectPlan>(`/ai/projects/${id}/add-to-cart/`, withPin(pin))).data,
    onSuccess: (plan) => {
      queryClient.setQueryData(projectKeys.plan(id, pin), plan)
      void queryClient.invalidateQueries({ queryKey: cartKeys.cart })
      void queryClient.invalidateQueries({ queryKey: ['checkout'] })
      void queryClient.invalidateQueries({ queryKey: projectKeys.list })
    },
  })
}

export function useDeleteProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => api.delete(`/ai/projects/${id}/`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: projectKeys.list }),
  })
}
