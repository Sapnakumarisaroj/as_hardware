import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useIsStaff } from '@/features/admin/api'
import type { SeriesRow } from '@/features/admin/types'
import { api } from '@/lib/api/client'

/* Phase 24: business reports and the business assistant. Every number is calculated by the
   server from the database; the browser only lays it out. */

export type ValueFormat = 'money' | 'count' | 'percent' | 'minutes' | 'number' | 'text'

export interface Kpi {
  key: string
  label: string
  value: string | number | null
  format: ValueFormat
  hint?: string
}

export interface ReportColumn {
  key: string
  label: string
  format: ValueFormat
}

export interface ReportTable {
  key: string
  title: string
  columns: ReportColumn[]
  rows: Record<string, string | number | null>[]
  chart: { type: 'bar' | 'share'; label: string; value: string } | null
}

export interface Report {
  key: string
  title: string
  description: string
  period: { from: string; to: string; days: number; group_by: 'day' | 'week' | 'month' }
  kpis: Kpi[]
  series: SeriesRow[] | null
  tables: ReportTable[]
  notes: string[]
}

export interface ReportInfo {
  key: string
  title: string
  description: string
}

export type ReportParams = { from?: string; to?: string; store?: string; group_by?: string }

function clean(params: ReportParams): Record<string, string> {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v)) as Record<string, string>
}

export function useReportList() {
  const staff = useIsStaff()
  return useQuery({
    queryKey: ['admin', 'reports', 'list'],
    queryFn: async () => (await api.get<{ results: ReportInfo[] }>('/admin/reports/')).data.results,
    enabled: staff,
    staleTime: Infinity,
  })
}

export function useReport(key: string, params: ReportParams) {
  const staff = useIsStaff()
  const sent = clean(params)
  return useQuery({
    queryKey: ['admin', 'reports', key, sent],
    queryFn: async () => (await api.get<Report>(`/admin/reports/${key}/`, { params: sent })).data,
    enabled: staff && Boolean(key),
    placeholderData: keepPreviousData,
  })
}

/** Downloads one table (or 'kpis') as CSV with the signed-in session. */
export async function downloadReport(key: string, table: string, params: ReportParams): Promise<void> {
  const response = await api.get<Blob>(`/admin/reports/${key}/export/`, {
    params: { ...clean(params), table },
    responseType: 'blob',
  })
  if (typeof URL.createObjectURL !== 'function') return
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = `${key}-${table}-${params.from ?? ''}-${params.to ?? ''}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

// --- Business assistant ----------------------------------------------------------------------------

export interface AssistantStatus {
  ai: { provider: string; model: string; available: boolean }
  suggestions: string[]
  topics: { key: string; label: string; report: string }[]
  stores: { id: number; name: string }[]
}

export interface AssistantAnswer {
  question: string
  understood: boolean
  intent: string | null
  intent_label?: string
  report?: string
  period?: { from: string; to: string; label: string }
  store?: string | null
  text: string
  kpis?: Kpi[]
  comparison?: {
    kpi: string
    label: string
    current: string | number | null
    previous: string | number | null
    change_percent: number | null
    format: ValueFormat
    previous_period: { from: string; to: string }
  } | null
  table?: ReportTable | null
  notes?: string[]
  link?: string
  source: 'rules' | 'ai'
  suggestions: string[]
}

export interface HistoryRow {
  id: number
  question: string
  answer: string
  report: string
  period: { from: string | null; to: string | null }
  store: string | null
  source: 'rules' | 'ai'
  created_at: string
}

export function useAssistantStatus() {
  const staff = useIsStaff()
  return useQuery({
    queryKey: ['admin', 'assistant', 'status'],
    queryFn: async () => (await api.get<AssistantStatus>('/admin/assistant/')).data,
    enabled: staff,
  })
}

export function useAssistantHistory() {
  const staff = useIsStaff()
  return useQuery({
    queryKey: ['admin', 'assistant', 'history'],
    queryFn: async () => (await api.get<{ results: HistoryRow[] }>('/admin/assistant/history/')).data.results,
    enabled: staff,
  })
}

export function useAsk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ question, store }: { question: string; store?: string }) =>
      (await api.post<AssistantAnswer>('/admin/assistant/', { question }, { params: store ? { store } : {} })).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['admin', 'assistant', 'history'] }),
  })
}

// --- Formatting ------------------------------------------------------------------------------------

const RUPEES = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 })

export function formatValue(value: string | number | null | undefined, format: ValueFormat): string {
  if (value === null || value === undefined || value === '') return '—'
  switch (format) {
    case 'money':
      return RUPEES.format(Number(value))
    case 'percent':
      return `${value}%`
    case 'minutes':
      return `${Math.round(Number(value))} min`
    case 'count':
      return Number(value).toLocaleString('en-IN')
    default:
      return typeof value === 'number' ? value.toLocaleString('en-IN') : String(value)
  }
}
