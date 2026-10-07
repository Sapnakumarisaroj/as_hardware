import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { Drawer } from '@/components/Drawer'
import { ErrorState, Spinner } from '@/components/feedback'
import { SparkIcon, TrashIcon } from '@/components/icons'
import { useToast } from '@/components/toast'
import {
  useAsk,
  useAssistantStatus,
  useClearConversation,
  useConversation,
  useConversations,
  useDeleteConversation,
} from '@/features/ai/api'
import { MessageBubble, TypingIndicator } from '@/features/ai/components'
import type { AssistantLanguage, ConversationSummary } from '@/features/ai/types'
import { useAuth } from '@/features/auth/context'
import { ApiError } from '@/lib/api/errors'
import { formatDate } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const LANGUAGES: [AssistantLanguage, string][] = [
  ['en', 'English'],
  ['hinglish', 'Hinglish'],
  ['hi', 'हिन्दी'],
]
const MAX_LENGTH = 1000

function ConversationList({
  conversations,
  currentId,
  onPick,
  onNew,
}: {
  conversations: ConversationSummary[]
  currentId: number | null
  onPick: (id: number) => void
  onNew: () => void
}) {
  return (
    <nav aria-label="Your conversations" className="space-y-2">
      <button type="button" onClick={onNew} className="btn-primary w-full">
        <SparkIcon className="size-4" /> New conversation
      </button>
      {conversations.length === 0 ? (
        <p className="px-1 text-xs text-ink-600">Your past conversations will appear here.</p>
      ) : (
        <ul className="space-y-1">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                onClick={() => onPick(conversation.id)}
                aria-current={conversation.id === currentId ? 'true' : undefined}
                className={`w-full rounded-md px-3 py-2 text-left text-sm hover:bg-steel-100 ${conversation.id === currentId ? 'bg-amber-100 font-semibold' : ''}`}
              >
                <span className="line-clamp-1">{conversation.title || 'New conversation'}</span>
                <span className="block text-xs font-normal text-ink-600">
                  {formatDate(conversation.updated_at)} · {conversation.message_count} messages
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  )
}

export function AssistantPage() {
  usePageMeta('AI hardware assistant', 'Ask in English, Hindi or Hinglish and get products from our real catalogue.')
  const { status: authStatus, user } = useAuth()
  const signedIn = authStatus === 'authenticated' && user !== null
  const navigate = useNavigate()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const conversationId = Number(params.get('c')) || null
  // Phase 21: opened from a product page ("Ask the assistant"): "this" means that product
  const productId = Number(params.get('product')) || null

  const assistant = useAssistantStatus()
  const conversations = useConversations()
  const conversation = useConversation(signedIn ? conversationId : null)
  const ask = useAsk()
  const clear = useClearConversation()
  const remove = useDeleteConversation()

  const [text, setText] = useState(() => params.get('ask') ?? '')
  const [language, setLanguage] = useState<AssistantLanguage>('en')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [lastError, setLastError] = useState<{ message: string; text: string } | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)

  const messages = conversation.data?.messages ?? []
  const hasMessages = messages.length > 0 || ask.isPending

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: 'end' })
  }, [messages.length, ask.isPending])

  function open(id: number | null) {
    const next = new URLSearchParams(params)
    if (id) next.set('c', String(id))
    else next.delete('c')
    next.delete('ask')
    setParams(next)
    setHistoryOpen(false)
    setLastError(null)
  }

  function send(message: string) {
    const trimmed = message.trim().slice(0, MAX_LENGTH)
    if (!trimmed || ask.isPending) return
    if (!signedIn) {
      const next = `/ai-assistant?ask=${encodeURIComponent(trimmed)}`
      toast.show('Sign in to chat with the assistant — your question is kept.', { tone: 'info' })
      void navigate(`/login?next=${encodeURIComponent(next)}`)
      return
    }
    setLastError(null)
    setText('')
    ask.mutate(
      { conversationId, message: trimmed, language, productId },
      {
        onSuccess: (result) => {
          if (result.kind === 'new') open(result.conversation.id)
        },
        onError: (error) => {
          setLastError({
            message: error instanceof ApiError ? error.message : 'The assistant could not answer. Please try again.',
            text: trimmed,
          })
          setText(trimmed)
        },
      },
    )
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    send(text)
  }

  const prompts = assistant.data?.suggested_prompts[language] ?? assistant.data?.suggested_prompts.en ?? []
  const greeting = assistant.data?.greeting[language] ?? 'Tell me what you’re fixing, building or looking for.'

  const sidebar = signedIn ? (
    conversations.isPending ? (
      <Spinner label="Loading conversations…" />
    ) : (
      <ConversationList
        conversations={conversations.data?.results ?? []}
        currentId={conversationId}
        onPick={open}
        onNew={() => open(null)}
      />
    )
  ) : (
    <p className="text-sm text-ink-600">
      <Link to={`/login?next=${encodeURIComponent('/ai-assistant')}`} className="font-semibold text-amber-600 hover:underline">
        Sign in
      </Link>{' '}
      to keep your conversations.
    </p>
  )

  return (
    <div className="container-page flex min-h-[calc(100dvh-4rem)] flex-col py-3 md:py-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-extrabold tracking-tight">
            <SparkIcon className="size-5 text-amber-500" /> AI hardware assistant
          </h1>
          <p className="text-xs text-ink-600">
            Recommendations come from our catalogue with live prices and stock.
            {assistant.data?.ai_mode === 'basic' && ' Basic mode: answers use keyword matching.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="assistant-language" className="sr-only">
            Language
          </label>
          <select
            id="assistant-language"
            className="input w-auto py-1.5"
            value={language}
            onChange={(event) => setLanguage(event.target.value as AssistantLanguage)}
          >
            {LANGUAGES.map(([value, name]) => (
              <option key={value} value={value}>
                {name}
              </option>
            ))}
          </select>
          <button type="button" className="btn-secondary px-3 py-1.5 lg:hidden" onClick={() => setHistoryOpen(true)}>
            History
          </button>
          {signedIn && conversationId && messages.length > 0 && (
            <>
              <button
                type="button"
                className="btn-secondary px-3 py-1.5"
                disabled={clear.isPending}
                onClick={() => clear.mutate(conversationId, { onSuccess: () => toast.show('Conversation cleared.') })}
              >
                Clear
              </button>
              <button
                type="button"
                className="btn-secondary px-3 py-1.5 text-danger-600"
                aria-label="Delete conversation"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(conversationId, {
                    onSuccess: () => {
                      toast.show('Conversation deleted.')
                      open(null)
                    },
                  })
                }
              >
                <TrashIcon className="size-4" />
              </button>
            </>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 gap-4">
        <aside className="hidden w-64 shrink-0 lg:block">
          <div className="sticky top-20 rounded-lg bg-white p-3 ring-1 ring-steel-200">{sidebar}</div>
        </aside>
        <Drawer open={historyOpen} onClose={() => setHistoryOpen(false)} title="Conversations">
          {sidebar}
        </Drawer>

        <section aria-label="Conversation" className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 space-y-3 overflow-y-auto rounded-lg bg-steel-100/60 p-3 sm:p-4">
            {conversation.isPending && conversationId ? (
              <div className="flex justify-center py-10">
                <Spinner label="Loading the conversation…" />
              </div>
            ) : conversation.isError ? (
              <ErrorState error={conversation.error} onRetry={() => void conversation.refetch()} title="Couldn’t load the conversation" />
            ) : (
              <>
                {!hasMessages && (
                  <div className="rounded-lg bg-white px-4 py-5 ring-1 ring-steel-200">
                    <p className="text-sm">{greeting}</p>
                    <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-ink-600">Try asking</p>
                    <ul className="mt-2 flex flex-wrap gap-2">
                      {prompts.map((prompt) => (
                        <li key={prompt}>
                          <button
                            type="button"
                            onClick={() => send(prompt)}
                            className="rounded-full bg-amber-100 px-3 py-1.5 text-sm font-medium hover:bg-amber-500/40"
                          >
                            {prompt}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <ol aria-label="Messages" className="space-y-3">
                  {messages.map((message) => (
                    <MessageBubble
                      key={message.id}
                      message={message}
                      signedIn={signedIn}
                      onSuggest={() => input.current?.focus()}
                    />
                  ))}
                  {ask.isPending && (
                    <>
                      <li className="flex justify-end">
                        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-ink-900 px-4 py-2.5 text-sm text-white opacity-80">
                          {ask.variables?.message}
                        </div>
                      </li>
                      <TypingIndicator />
                    </>
                  )}
                </ol>
                {lastError && (
                  <div role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600">
                    {lastError.message}{' '}
                    <button type="button" className="font-semibold underline" onClick={() => send(lastError.text)}>
                      Retry
                    </button>
                  </div>
                )}
                <div ref={bottom} />
              </>
            )}
          </div>

          <form onSubmit={submit} className="sticky bottom-0 mt-3 flex items-end gap-2 bg-steel-50 pb-[env(safe-area-inset-bottom)] pt-1">
            <label htmlFor="assistant-input" className="sr-only">
              Your question
            </label>
            <textarea
              id="assistant-input"
              ref={input}
              className="input min-h-11 flex-1 resize-none py-2.5"
              rows={1}
              maxLength={MAX_LENGTH}
              placeholder={signedIn ? 'Ask about plywood, hinges, locks, tools…' : 'Ask a question — you’ll be asked to sign in'}
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  send(text)
                }
              }}
            />
            <button type="submit" className="btn-primary h-11 px-4" disabled={ask.isPending || !text.trim()}>
              {ask.isPending ? 'Sending…' : 'Send'}
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}
