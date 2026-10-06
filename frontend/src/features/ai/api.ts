import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import type { Paginated } from '@/features/catalog/types'
import { api } from '@/lib/api/client'

import type { AssistantLanguage, AssistantStatus, Conversation, ConversationSummary, Turn } from './types'

export const aiKeys = {
  status: ['ai', 'status'] as const,
  conversations: ['ai', 'conversations'] as const,
  conversation: (id: number) => ['ai', 'conversation', id] as const,
}

export function useAssistantStatus() {
  return useQuery({
    queryKey: aiKeys.status,
    queryFn: async () => (await api.get<AssistantStatus>('/ai/assistant/')).data,
    staleTime: 10 * 60_000,
  })
}

export function useConversations() {
  const { status } = useAuth()
  return useQuery({
    queryKey: aiKeys.conversations,
    queryFn: async () => (await api.get<Paginated<ConversationSummary>>('/ai/conversations/', { params: { page_size: 20 } })).data,
    enabled: status === 'authenticated',
  })
}

export function useConversation(id: number | null) {
  const { status } = useAuth()
  return useQuery({
    queryKey: aiKeys.conversation(id ?? 0),
    queryFn: async () => (await api.get<Conversation>(`/ai/conversations/${id}/`)).data,
    enabled: status === 'authenticated' && id !== null,
  })
}

/** Starts a conversation with the first question, or continues one. The answer comes back with it. */
export function useAsk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { conversationId: number | null; message: string; language?: AssistantLanguage; productId?: number | null }) => {
      const product = input.productId ? { product_id: input.productId } : {}
      if (input.conversationId === null) {
        const { data } = await api.post<Conversation>('/ai/conversations/', { message: input.message, language: input.language, ...product })
        return { kind: 'new' as const, conversation: data }
      }
      const { data } = await api.post<Turn>(`/ai/conversations/${input.conversationId}/messages/`, {
        message: input.message,
        language: input.language,
        ...product,
      })
      return { kind: 'turn' as const, turn: data }
    },
    onSuccess: (result) => {
      if (result.kind === 'new') {
        queryClient.setQueryData(aiKeys.conversation(result.conversation.id), result.conversation)
      } else {
        const { turn } = result
        queryClient.setQueryData<Conversation>(aiKeys.conversation(turn.conversation_id), (current) =>
          current
            ? { ...current, title: turn.title, messages: [...current.messages, turn.user_message, turn.assistant_message] }
            : current,
        )
      }
      void queryClient.invalidateQueries({ queryKey: aiKeys.conversations })
    },
  })
}

export function useClearConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => (await api.post<Conversation>(`/ai/conversations/${id}/clear/`, {})).data,
    onSuccess: (conversation) => {
      queryClient.setQueryData(aiKeys.conversation(conversation.id), conversation)
      void queryClient.invalidateQueries({ queryKey: aiKeys.conversations })
    },
  })
}

export function useDeleteConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => (await api.delete(`/ai/conversations/${id}/`)).data,
    onSuccess: (_data, id) => {
      queryClient.removeQueries({ queryKey: aiKeys.conversation(id) })
      void queryClient.invalidateQueries({ queryKey: aiKeys.conversations })
    },
  })
}
