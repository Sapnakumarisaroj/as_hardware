import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { api } from '@/lib/api/client'

/* Phase 23: the in-app inbox, each person's own message choices and the administrator's
   notification centre. The server decides who receives what; the browser only shows it. */

export type Channel = 'in_app' | 'email' | 'whatsapp' | 'sms'
export type Language = 'en' | 'hi' | 'hi-latn'

export interface Notification {
  id: number
  event: string
  category: string
  title: string
  body: string
  /** App path to open, or '' when the message has no page. */
  link: string
  is_read: boolean
  read_at: string | null
  created_at: string
}

export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface Preferences {
  email: boolean
  sms: boolean
  whatsapp: boolean
  muted_categories: string[]
  has_email: boolean
  /** Masked, e.g. "98•••••678"; '' when the account has no mobile number. */
  phone: string
  channels: {
    in_app: { available: boolean; always_on: boolean }
    email: { available: boolean }
    whatsapp: { available: boolean; needs_phone: boolean }
    sms: { available: boolean; needs_phone: boolean }
  }
  categories: { key: string; label: string }[]
}

export type PreferencesChange = Partial<Pick<Preferences, 'email' | 'sms' | 'whatsapp' | 'muted_categories'>>

const POLL_MS = 60_000

export const notificationKeys = {
  all: ['notifications'] as const,
  summary: ['notifications', 'summary'] as const,
  list: (params: Record<string, string>) => ['notifications', 'list', params] as const,
  preferences: ['notifications', 'preferences'] as const,
}

/** Unread count for the bell; refreshed every minute and when the window regains focus. */
export function useUnreadCount() {
  const { status } = useAuth()
  return useQuery({
    queryKey: notificationKeys.summary,
    queryFn: async () => (await api.get<{ unread: number }>('/notifications/summary/')).data,
    enabled: status === 'authenticated',
    refetchInterval: POLL_MS,
    retry: false,
  })
}

export function useNotifications(params: Record<string, string>) {
  const { status } = useAuth()
  return useQuery({
    queryKey: notificationKeys.list(params),
    queryFn: async () => (await api.get<Page<Notification>>('/notifications/', { params })).data,
    enabled: status === 'authenticated',
    placeholderData: keepPreviousData,
  })
}

function useInboxChange<T>(run: (input: T) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
  })
}

export const useMarkRead = () => useInboxChange((id: number) => api.post(`/notifications/${id}/read/`))
export const useMarkUnread = () => useInboxChange((id: number) => api.post(`/notifications/${id}/unread/`))
export const useMarkAllRead = () => useInboxChange((_: void) => api.post('/notifications/read-all/', {}))

export function usePreferences() {
  const { status } = useAuth()
  return useQuery({
    queryKey: notificationKeys.preferences,
    queryFn: async () => (await api.get<Preferences>('/notifications/preferences/')).data,
    enabled: status === 'authenticated',
  })
}

export function useSavePreferences() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (change: PreferencesChange) =>
      (await api.patch<Preferences>('/notifications/preferences/', change)).data,
    onSuccess: (data) => queryClient.setQueryData(notificationKeys.preferences, data),
  })
}

// --- Administration ------------------------------------------------------------------------------

export interface EventTemplate {
  id: number
  language: Language
  title: string
  body: string
  provider_template: string
  updated_at: string
}

export interface EventChannel {
  channel: Channel
  enabled: boolean
  default_enabled: boolean
  default_title: string
  default_body: string
  default_provider_template: string
  templates: EventTemplate[]
}

export interface EventSpec {
  key: string
  label: string
  category: string
  category_label: string
  audience: 'customer' | 'rider' | 'staff'
  critical: boolean
  variables: string[]
  secret_variables: string[]
  channels: EventChannel[]
}

export interface ChannelStatus {
  channel: Channel
  enabled: boolean
  provider: string
  configured: boolean
  mock: boolean
  live: boolean
  last_24h: Record<'pending' | 'sent' | 'failed' | 'skipped', number>
  last_sent_at: string | null
  last_error: string
}

export interface LogRow {
  id: number
  created_at: string
  user: number
  user_email: string
  user_name: string
  channel: Channel
  event: string
  language: Language
  title: string
  body: string
  status: 'pending' | 'sent' | 'failed' | 'skipped'
  provider: string
  provider_status: string
  template_name: string
  recipient: string
  attempts: number
  error: string
  sent_at: string | null
  delivered_at: string | null
  read_at: string | null
  can_retry: boolean
}

export interface TemplateInput {
  id?: number
  event: string
  channel: Channel
  language: Language
  title: string
  body: string
  provider_template: string
}

export interface Preview {
  ok: boolean
  problems: Record<string, string[]>
  title: string
  body: string
  parameters?: string[]
}

const adminKeys = {
  events: ['admin', 'notifications', 'events'] as const,
  channels: ['admin', 'notifications', 'channels'] as const,
  log: (params: Record<string, string>) => ['admin', 'notifications', 'log', params] as const,
}

function useIsAdmin(): boolean {
  const { status, user } = useAuth()
  return status === 'authenticated' && user?.role === 'admin'
}

export function useNotificationEvents() {
  const enabled = useIsAdmin()
  return useQuery({
    queryKey: adminKeys.events,
    queryFn: async () => (await api.get<{ results: EventSpec[]; languages: Language[] }>('/admin/notifications/events/')).data,
    enabled,
  })
}

export function useNotificationChannels() {
  const enabled = useIsAdmin()
  return useQuery({
    queryKey: adminKeys.channels,
    queryFn: async () => (await api.get<{ results: ChannelStatus[] }>('/admin/notifications/channels/')).data.results,
    enabled,
  })
}

export function useNotificationLog(params: Record<string, string>) {
  const enabled = useIsAdmin()
  return useQuery({
    queryKey: adminKeys.log(params),
    queryFn: async () => (await api.get<Page<LogRow>>('/admin/notifications/log/', { params })).data,
    enabled,
    placeholderData: keepPreviousData,
  })
}

function useAdminChange<T, R = unknown>(run: (input: T) => Promise<R>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['admin', 'notifications'] }),
  })
}

export const useSwitchChannel = () =>
  useAdminChange(({ channel, enabled }: { channel: Channel; enabled: boolean }) =>
    api.patch(`/admin/notifications/channels/${channel}/`, { enabled }),
  )

export const useSwitchEventChannel = () =>
  useAdminChange(({ event, channel, enabled }: { event: string; channel: Channel; enabled: boolean }) =>
    api.patch(`/admin/notifications/events/${event}/${channel}/`, { enabled }),
  )

export const useSaveTemplate = () =>
  useAdminChange(({ id, ...body }: TemplateInput) =>
    id ? api.patch(`/admin/notifications/templates/${id}/`, body) : api.post('/admin/notifications/templates/', body),
  )

export const useDeleteTemplate = () => useAdminChange((id: number) => api.delete(`/admin/notifications/templates/${id}/`))

export const useRetryNotification = () => useAdminChange((id: number) => api.post(`/admin/notifications/log/${id}/retry/`))

export const useRetryFailed = () =>
  useAdminChange(async (channel: string) => (await api.post<{ retried: number }>('/admin/notifications/log/retry-failed/', channel ? { channel } : {})).data)

export function usePreview() {
  return useMutation({
    mutationFn: async (input: { event: string; channel: Channel; title: string; body: string }) =>
      (await api.post<Preview>('/admin/notifications/preview/', input)).data,
  })
}
