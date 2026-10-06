import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import type { Paginated } from '@/features/catalog/types'
import { api } from '@/lib/api/client'

import type { PendingLine, VoiceLanguage, VoiceResult, VoiceSession, VoiceStatus, VoiceTranscript } from './types'

export const voiceKeys = {
  status: ['voice', 'status'] as const,
  sessions: ['voice', 'sessions'] as const,
}

export function useVoiceStatus() {
  return useQuery({
    queryKey: voiceKeys.status,
    queryFn: async () => (await api.get<VoiceStatus>('/ai/voice/')).data,
    staleTime: 10 * 60_000,
  })
}

export interface VoiceCommandInput {
  transcript: string
  language: VoiceLanguage
  conversationId: number | null
  pending: PendingLine[]
  postalCode?: string | null
}

/** Sends what was heard; the answer says what was understood, with prices from the pricing engine. */
export function useVoiceCommand() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: VoiceCommandInput) =>
      (
        await api.post<VoiceResult>('/ai/voice/command/', {
          transcript: input.transcript,
          language: input.language,
          conversation_id: input.conversationId,
          pending: input.pending,
          ...(input.postalCode ? { postal_code: input.postalCode } : {}),
        })
      ).data,
    onSuccess: (result) => {
      if (result.conversation_id !== null) void queryClient.invalidateQueries({ queryKey: voiceKeys.sessions })
    },
  })
}

/** Server speech recognition (only when the shop switched it on): a recording in, words out. */
export function useTranscribe() {
  return useMutation({
    mutationFn: async (input: { audio: Blob; language: VoiceLanguage }) => {
      const form = new FormData()
      const extension = input.audio.type.includes('mp4') ? 'm4a' : input.audio.type.includes('ogg') ? 'ogg' : 'webm'
      form.append('audio', input.audio, `recording.${extension}`)
      form.append('language', input.language)
      return (await api.post<VoiceTranscript>('/ai/voice/transcribe/', form)).data
    },
  })
}

/** Server voice (only when the shop switched it on): the answer as audio. */
export async function fetchServerSpeech(text: string, language: VoiceLanguage): Promise<Blob> {
  const { data } = await api.post<Blob>('/ai/voice/speak/', { text, language }, { responseType: 'blob' })
  return data
}

export function useVoiceSessions() {
  const { status } = useAuth()
  return useQuery({
    queryKey: voiceKeys.sessions,
    queryFn: async () => (await api.get<Paginated<VoiceSession>>('/ai/voice-sessions/', { params: { page_size: 10 } })).data,
    enabled: status === 'authenticated',
  })
}

export function useDeleteVoiceSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number | 'all') =>
      id === 'all' ? api.post('/ai/voice-sessions/clear/', {}) : api.delete(`/ai/voice-sessions/${id}/`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: voiceKeys.sessions }),
  })
}
