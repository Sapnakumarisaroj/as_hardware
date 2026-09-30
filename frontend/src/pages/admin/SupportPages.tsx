import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { useToast } from '@/components/toast'
import { useConversation, useConversations, useReply, useUpdateConversation } from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { SupportDetail, SupportRow, SupportStatus } from '@/features/admin/types'
import {
  Badge,
  dateTime,
  errorMessage,
  Facts,
  FilterBar,
  FilterSelect,
  ListView,
  PageHeader,
  Panel,
  SearchBox,
  SelectField,
  StatusBadge,
  TextAreaField,
  useListParams,
  type Column,
} from '@/features/admin/ui'
import { isNotFound } from '@/lib/api/errors'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from '../NotFoundPage'

const STATUSES: [SupportStatus, string][] = [
  ['open', 'Open'],
  ['waiting_customer', 'Waiting for customer'],
  ['resolved', 'Resolved'],
  ['closed', 'Closed'],
]

const COLUMNS: Column<SupportRow>[] = [
  {
    header: 'Conversation',
    cell: (row) => (
      <>
        <Link to={`/admin/support/${row.id}`} className="font-semibold underline-offset-2 hover:underline">
          {row.subject || `Conversation ${row.id}`}
        </Link>
        <span className="block max-w-72 truncate text-xs text-ink-600">{row.last_message}</span>
      </>
    ),
  },
  {
    header: 'Customer',
    cell: (row) => (
      <>
        {row.customer?.name || row.customer?.email || row.customer?.phone || 'Unknown'}
        <span className="block text-xs text-ink-600">{row.customer?.phone}</span>
      </>
    ),
  },
  {
    header: 'Order',
    cell: (row) =>
      row.order_number ? (
        <>
          <Link to={`/admin/orders/${row.order_number}`} className="underline-offset-2 hover:underline">
            {row.order_number}
          </Link>
          <span className="block text-xs text-ink-600">{row.store_name}</span>
        </>
      ) : (
        '—'
      ),
  },
  {
    header: 'Status',
    cell: (row) => (
      <span className="flex flex-wrap justify-end gap-1 md:justify-start">
        <StatusBadge status={row.status} text={row.status_label} />
        {row.waiting_for_reply && <Badge tone="bad">Needs a reply</Badge>}
      </span>
    ),
  },
  { header: 'Handled by', cell: (row) => row.assigned_to_name ?? 'Nobody yet' },
  { header: 'Messages', numeric: true, cell: (row) => row.message_count },
  { header: 'Last message', cell: (row) => dateTime(row.last_message_at ?? row.created_at) },
]

export function AdminSupportPage() {
  usePageMeta('Support')
  const session = useSession()
  const list = useListParams()
  const status = list.get('status') || 'active'
  const conversations = useConversations({
    page: list.page,
    q: list.get('q'),
    status: status === 'all' ? '' : status,
    mine: list.get('mine'),
    store: list.get('store'),
  })
  return (
    <>
      <PageHeader
        title="Support"
        description={session.is_admin ? 'Every customer conversation.' : 'Conversations about orders of your stores.'}
      />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by subject, customer or order" />
        <FilterSelect list={list} name="status" label="Status" all="Open and waiting" options={[...STATUSES, ['all', 'All']]} />
        <FilterSelect list={list} name="mine" label="Handled by" all="Anyone" options={[['true', 'Me']]} />
      </FilterBar>
      <ListView
        query={conversations}
        list={list}
        caption="Support conversations"
        columns={COLUMNS}
        rowKey={(row) => row.id}
        empty="No conversations are waiting"
        emptyHint="New questions from customers appear here."
      />
    </>
  )
}

function Conversation({ conversation }: { conversation: SupportDetail }) {
  const session = useSession()
  const reply = useReply(conversation.id)
  const update = useUpdateConversation(conversation.id)
  const toast = useToast()
  const [body, setBody] = useState('')
  const finished = conversation.status === 'closed'
  const fail = (error: unknown) => toast.show(errorMessage(error), { tone: 'error' })

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div className="space-y-5 lg:col-span-2">
        <Panel title="Messages">
          {conversation.messages.length === 0 ? (
            <p className="text-sm text-ink-600">No messages yet.</p>
          ) : (
            <ol className="space-y-3">
              {conversation.messages.map((message) => {
                const staff = message.sender_type === 'agent'
                const quiet = message.sender_type === 'system' || message.sender_type === 'bot'
                return (
                  <li key={message.id} className={`flex ${staff ? 'justify-end' : 'justify-start'}`}>
                    <div
                      className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${staff ? 'bg-ink-900 text-white' : quiet ? 'bg-steel-50 text-ink-600' : 'bg-steel-100'}`}
                    >
                      <p className={`text-xs font-semibold ${staff ? 'text-steel-200' : 'text-ink-600'}`}>
                        {message.sender_name} · {dateTime(message.created_at)}
                      </p>
                      <p className="mt-0.5 whitespace-pre-wrap break-words">{message.body}</p>
                    </div>
                  </li>
                )
              })}
            </ol>
          )}
        </Panel>

        {finished ? (
          <p className="rounded-md bg-steel-100 px-3 py-2 text-sm">This conversation is closed. Reopen it to reply.</p>
        ) : (
          <Panel title="Reply">
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault()
                if (!body.trim()) return
                reply.mutate(body.trim(), {
                  onSuccess: () => {
                    setBody('')
                    toast.show('Reply sent.')
                  },
                })
              }}
            >
              <TextAreaField id="reply" label="Your reply" rows={4} maxLength={4000} required value={body} onChange={setBody} />
              {reply.isError && (
                <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600">
                  {errorMessage(reply.error)}
                </p>
              )}
              <div className="flex justify-end">
                <button type="submit" className="btn-primary" disabled={reply.isPending || !body.trim()}>
                  {reply.isPending ? 'Sending…' : 'Send reply'}
                </button>
              </div>
            </form>
          </Panel>
        )}
      </div>

      <div className="space-y-5">
        <Panel title="Details">
          <Facts
            items={[
              ['Customer', conversation.customer?.name || '—'],
              ['Email', conversation.customer?.email ? <a href={`mailto:${conversation.customer.email}`}>{conversation.customer.email}</a> : '—'],
              ['Phone', conversation.customer?.phone ? <a href={`tel:${conversation.customer.phone}`}>{conversation.customer.phone}</a> : '—'],
              [
                'Order',
                conversation.order_number ? (
                  <Link to={`/admin/orders/${conversation.order_number}`} className="underline-offset-2 hover:underline">
                    {conversation.order_number}
                  </Link>
                ) : (
                  '—'
                ),
              ],
              ['Store', conversation.store_name ?? '—'],
              ['Came in by', conversation.channel.replace('_', ' ')],
              ['Started', dateTime(conversation.created_at)],
              ['Handled by', conversation.assigned_to_name ?? 'Nobody yet'],
            ]}
          />
        </Panel>
        <Panel title="Handling">
          <SelectField
            id="conversation-status"
            label="Status"
            value={conversation.status}
            disabled={update.isPending}
            onChange={(e) =>
              update.mutate({ status: e.target.value as SupportStatus }, { onSuccess: () => toast.show('Status changed.'), onError: fail })
            }
          >
            {STATUSES.map(([value, name]) => (
              <option key={value} value={value}>
                {name}
              </option>
            ))}
          </SelectField>
          {conversation.assigned_to !== session.user.id && (
            <button
              type="button"
              className="btn-secondary mt-3 w-full"
              disabled={update.isPending}
              onClick={() => update.mutate({ assign_to_me: true }, { onSuccess: () => toast.show('This conversation is yours now.'), onError: fail })}
            >
              I’ll handle this
            </button>
          )}
        </Panel>
      </div>
    </div>
  )
}

export function AdminConversationPage() {
  const { id } = useParams()
  const query = useConversation(id)
  usePageMeta(query.data?.subject || 'Conversation')
  if (query.isPending) return <PageSpinner label="Loading the conversation…" />
  if (isNotFound(query.error)) return <NotFoundPage />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn’t load the conversation" />
  const conversation = query.data
  return (
    <>
      <PageHeader
        title={conversation.subject || `Conversation ${conversation.id}`}
        crumbs={[{ label: 'Support', to: '/admin/support' }]}
        actions={<StatusBadge status={conversation.status} text={conversation.status_label} />}
      />
      <Conversation conversation={conversation} />
    </>
  )
}
