import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import type { Paginated } from '@/features/catalog/types'
import { api } from '@/lib/api/client'

import type { CompleteInput, Earnings, FailureCode, Job, RiderProfile } from './types'

export const riderKeys = {
  all: ['rider'] as const,
  me: ['rider', 'me'] as const,
  earnings: ['rider', 'earnings'] as const,
  jobs: (scope: 'active' | 'history', page: number) => ['rider', 'jobs', scope, page] as const,
  job: (id: number) => ['rider', 'job', id] as const,
}

export const JOBS_PAGE_SIZE = 10
const ACTIVE_REFRESH_MS = 30_000 // new jobs arrive while the app is open

function useIsRider(): boolean {
  const { status, user } = useAuth()
  return status === 'authenticated' && user?.role === 'delivery_partner'
}

export function useRiderProfile() {
  const enabled = useIsRider()
  return useQuery({
    queryKey: riderKeys.me,
    queryFn: async () => (await api.get<RiderProfile>('/delivery/me/')).data,
    enabled,
    refetchInterval: ACTIVE_REFRESH_MS,
  })
}

export function useEarnings() {
  const enabled = useIsRider()
  return useQuery({
    queryKey: riderKeys.earnings,
    queryFn: async () => (await api.get<Earnings>('/delivery/earnings/')).data,
    enabled,
  })
}

export function useJobs(scope: 'active' | 'history', page = 1) {
  const enabled = useIsRider()
  return useQuery({
    queryKey: riderKeys.jobs(scope, page),
    queryFn: async () =>
      (await api.get<Paginated<Job>>('/delivery/assignments/', { params: { scope, page, page_size: JOBS_PAGE_SIZE } }))
        .data,
    enabled,
    placeholderData: keepPreviousData,
    refetchInterval: scope === 'active' ? ACTIVE_REFRESH_MS : false,
  })
}

export function useJob(id: number) {
  const enabled = useIsRider()
  return useQuery({
    queryKey: riderKeys.job(id),
    queryFn: async () => (await api.get<Job>(`/delivery/assignments/${id}/`)).data,
    enabled: enabled && Number.isFinite(id),
    refetchInterval: (query) => (query.state.data?.next_actions.length ? ACTIVE_REFRESH_MS : false),
  })
}

export function useSetAvailability() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (status: 'available' | 'offline') =>
      (await api.patch<RiderProfile>('/delivery/me/', { status })).data,
    onSuccess: (profile) => queryClient.setQueryData(riderKeys.me, profile),
  })
}

/** Every step answers with the job as the server now sees it; lists and totals are refreshed. */
function useJobResult() {
  const queryClient = useQueryClient()
  return (job: Job) => {
    queryClient.setQueryData(riderKeys.job(job.id), job)
    void queryClient.invalidateQueries({ queryKey: ['rider', 'jobs'] })
    void queryClient.invalidateQueries({ queryKey: riderKeys.me })
    void queryClient.invalidateQueries({ queryKey: riderKeys.earnings })
  }
}

/** Where the rider is, if the browser knows and is allowed to tell. Never blocks a step. */
function currentPosition(): Promise<{ latitude: string; longitude: string } | Record<string, never>> {
  return new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return resolve({})
    navigator.geolocation.getCurrentPosition(
      (position) =>
        resolve({ latitude: position.coords.latitude.toFixed(6), longitude: position.coords.longitude.toFixed(6) }),
      () => resolve({}),
      { timeout: 4000, maximumAge: 60_000 },
    )
  })
}

type Step = 'accept' | 'pickup' | 'start'

export function useJobStep(id: number) {
  const store = useJobResult()
  return useMutation({
    mutationFn: async (step: Step) =>
      (await api.post<Job>(`/delivery/assignments/${id}/${step}/`, step === 'accept' ? {} : await currentPosition()))
        .data,
    onSuccess: store,
  })
}

export function useRejectJob(id: number) {
  const store = useJobResult()
  return useMutation({
    mutationFn: async (reason: string) => (await api.post<Job>(`/delivery/assignments/${id}/reject/`, { reason })).data,
    onSuccess: store,
  })
}

export function useCompleteJob(id: number) {
  const store = useJobResult()
  return useMutation({
    mutationFn: async (input: CompleteInput) =>
      (await api.post<Job>(`/delivery/assignments/${id}/complete/`, { ...input, ...(await currentPosition()) })).data,
    onSuccess: store,
  })
}

export function useFailJob(id: number) {
  const store = useJobResult()
  return useMutation({
    mutationFn: async ({ reason, note }: { reason: FailureCode; note: string }) =>
      (await api.post<Job>(`/delivery/assignments/${id}/fail/`, { reason, note, ...(await currentPosition()) })).data,
    onSuccess: store,
  })
}

export function useSaveNotes(id: number) {
  const store = useJobResult()
  return useMutation({
    mutationFn: async (notes: string) => (await api.patch<Job>(`/delivery/assignments/${id}/notes/`, { notes })).data,
    onSuccess: store,
  })
}

export function useUploadProof(id: number) {
  const store = useJobResult()
  return useMutation({
    mutationFn: async ({ photo, receivedBy }: { photo: File; receivedBy: string }) => {
      const form = new FormData()
      form.append('photo', photo)
      form.append('received_by', receivedBy)
      return (await api.post<Job>(`/delivery/assignments/${id}/proof/`, form)).data
    },
    onSuccess: store,
  })
}
