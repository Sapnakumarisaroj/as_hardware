import { useState } from 'react'
import { Link } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { Pagination } from '@/components/Pagination'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import {
  useMarkAllRead,
  useMarkRead,
  useMarkUnread,
  useNotifications,
  usePreferences,
  useSavePreferences,
  type Notification,
  type Preferences,
  type PreferencesChange,
} from '@/features/notifications/api'
import { ApiError } from '@/lib/api/errors'
import { usePageMeta } from '@/lib/usePageMeta'

const PAGE_SIZE = 20

function when(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  })
}

function Row({ note }: { note: Notification }) {
  const read = useMarkRead()
  const unread = useMarkUnread()
  const busy = read.isPending || unread.isPending
  return (
    <li className={`flex gap-3 p-4 ${note.is_read ? '' : 'bg-amber-500/5'}`} data-testid="notification">
      <span
        aria-hidden
        className={`mt-1.5 size-2 shrink-0 rounded-full ${note.is_read ? 'bg-transparent' : 'bg-amber-500'}`}
      />
      <div className="min-w-0 flex-1 text-sm">
        <p className={note.is_read ? 'text-ink-800' : 'font-semibold text-ink-950'}>
          {note.title}
          {!note.is_read && <span className="sr-only"> (unread)</span>}
        </p>
        <p className="mt-0.5 text-ink-800">{note.body}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-600">
          <span>{when(note.created_at)}</span>
          {note.link && (
            <Link
              to={note.link}
              onClick={() => !note.is_read && read.mutate(note.id)}
              className="font-semibold text-amber-700 hover:underline"
            >
              Open
            </Link>
          )}
          <button
            type="button"
            className="font-semibold hover:underline disabled:opacity-50"
            disabled={busy}
            onClick={() => (note.is_read ? unread.mutate(note.id) : read.mutate(note.id))}
          >
            {note.is_read ? 'Mark as unread' : 'Mark as read'}
            <span className="sr-only">: {note.title}</span>
          </button>
        </p>
      </div>
    </li>
  )
}

function Inbox({ categories }: { categories: { key: string; label: string }[] }) {
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(1)
  const params: Record<string, string> = { page: String(page), page_size: String(PAGE_SIZE) }
  if (filter === 'unread') params.unread = '1'
  else if (filter) params.category = filter
  const list = useNotifications(params)
  const markAll = useMarkAllRead()
  const toast = useToast()
  const options: [string, string][] = [['', 'All'], ['unread', 'Unread'], ...categories.map((c): [string, string] => [c.key, c.label])]

  return (
    <section aria-labelledby="inbox-heading" className="mt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="inbox-heading" className="sr-only">
          Messages
        </h2>
        <div className="scrollbar-none -mx-4 flex gap-2 overflow-x-auto px-4" role="group" aria-label="Show">
          {options.map(([value, text]) => (
            <button
              key={value || 'all'}
              type="button"
              aria-pressed={filter === value}
              onClick={() => {
                setFilter(value)
                setPage(1)
              }}
              className={`whitespace-nowrap rounded-full px-3 py-1.5 text-sm ring-1 ${filter === value ? 'bg-ink-900 text-white ring-ink-900' : 'bg-white ring-steel-200 hover:ring-amber-500'}`}
            >
              {text}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="btn-secondary"
          disabled={markAll.isPending}
          onClick={() => markAll.mutate(undefined, { onSuccess: () => toast.show('All messages marked as read.') })}
        >
          Mark all as read
        </button>
      </div>
      {list.isPending ? (
        <p className="mt-4 text-sm text-ink-600">Loading…</p>
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} title="Couldn’t load your messages" />
      ) : list.data.results.length === 0 ? (
        <div className="mt-4">
          <EmptyState title={filter ? 'Nothing here' : 'No messages yet'}>
            {filter ? 'Try another filter.' : 'Order, delivery, refund and support updates will appear here.'}
          </EmptyState>
        </div>
      ) : (
        <>
          <ul className="mt-3 divide-y divide-steel-100 rounded-2xl bg-white shadow-(--shadow-card) ring-1 ring-steel-200" aria-label="Messages">
            {list.data.results.map((note) => (
              <Row key={note.id} note={note} />
            ))}
          </ul>
          <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.count} onChange={setPage} />
        </>
      )}
    </section>
  )
}

function Toggle({
  id,
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  id: string
  label: string
  hint?: string
  checked: boolean
  disabled?: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <div className="flex items-start gap-3 py-2">
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 size-4 accent-amber-500"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <label htmlFor={id} className="text-sm">
        <span className="font-medium">{label}</span>
        {hint && <span className="block text-xs text-ink-600">{hint}</span>}
      </label>
    </div>
  )
}

function Settings({ prefs }: { prefs: Preferences }) {
  const save = useSavePreferences()
  const toast = useToast()
  const change = (values: PreferencesChange, done: string) => save.mutate(values, { onSuccess: () => toast.show(done) })
  const muted = new Set(prefs.muted_categories)
  const { whatsapp, sms, email } = prefs.channels
  const phoneHint = (needsPhone: boolean) =>
    needsPhone ? 'Add a mobile number to your account first.' : `Sent to ${prefs.phone}.`

  return (
    <section aria-labelledby="settings-heading" className="mt-8 rounded-2xl bg-white shadow-(--shadow-card) p-5 ring-1 ring-steel-200">
      <h2 id="settings-heading" className="text-lg font-bold">
        How we contact you
      </h2>
      <p className="mt-1 text-sm text-ink-600">
        Every message is always kept here in the app. Choose where else you want to receive them.
      </p>
      <div className="mt-3 divide-y divide-steel-100">
        <Toggle
          id="pref-email"
          label="Email"
          hint={prefs.has_email ? undefined : 'Your account has no email address.'}
          checked={prefs.email && email.available}
          disabled={!email.available || save.isPending}
          onChange={(value) => change({ email: value }, value ? 'Email messages on.' : 'Email messages off.')}
        />
        {whatsapp.available ? (
          <Toggle
            id="pref-whatsapp"
            label="WhatsApp"
            hint={`${phoneHint(whatsapp.needs_phone)} Order confirmations, delivery updates and your delivery code. Reply STOP on WhatsApp to turn it off.`}
            checked={prefs.whatsapp}
            disabled={(whatsapp.needs_phone && !prefs.whatsapp) || save.isPending}
            onChange={(value) => change({ whatsapp: value }, value ? 'WhatsApp messages on.' : 'WhatsApp messages off.')}
          />
        ) : (
          <p className="py-2 text-sm text-ink-600">WhatsApp messages are not available at the moment.</p>
        )}
        {sms.available && (
          <Toggle
            id="pref-sms"
            label="SMS"
            hint={phoneHint(sms.needs_phone)}
            checked={prefs.sms}
            disabled={(sms.needs_phone && !prefs.sms) || save.isPending}
            onChange={(value) => change({ sms: value }, value ? 'SMS on.' : 'SMS off.')}
          />
        )}
      </div>
      <h3 className="mt-5 text-sm font-bold">Topics</h3>
      <p className="text-xs text-ink-600">
        Turning a topic off stops its email and WhatsApp messages. Payments, refunds, cancellations, failed deliveries and
        delivery codes always reach you.
      </p>
      <div className="mt-1 grid sm:grid-cols-2">
        {prefs.categories.map((category) => (
          <Toggle
            key={category.key}
            id={`topic-${category.key}`}
            label={category.label}
            checked={!muted.has(category.key)}
            disabled={save.isPending}
            onChange={(on) => {
              const next = new Set(muted)
              if (on) next.delete(category.key)
              else next.add(category.key)
              change({ muted_categories: [...next] }, on ? `${category.label}: on.` : `${category.label}: off.`)
            }}
          />
        ))}
      </div>
      {save.isError && (
        <p role="alert" className="mt-3 text-sm text-danger-600">
          {save.error instanceof ApiError ? save.error.message : 'Couldn’t save your choice.'}
        </p>
      )}
    </section>
  )
}

/** /notifications — the inbox (customers, staff and delivery partners) and message settings. */
export function NotificationsPage() {
  usePageMeta('Notifications')
  const { status } = useAuth()
  const prefs = usePreferences()
  if (status === 'loading') return <PageSpinner />
  if (status !== 'authenticated') {
    return (
      <div className="container-page py-10">
        <SignInPrompt message="Sign in to see your messages." next="/notifications" />
      </div>
    )
  }
  return (
    <div className="container-page max-w-3xl py-6">
      <Breadcrumbs items={[{ label: 'My account', to: '/account' }, { label: 'Notifications' }]} />
      <h1 className="mt-3 text-2xl font-bold">Notifications</h1>
      <Inbox categories={prefs.data?.categories ?? []} />
      {prefs.isPending ? null : prefs.isError ? (
        <div className="mt-8">
          <ErrorState error={prefs.error} onRetry={() => prefs.refetch()} title="Couldn’t load your message settings" />
        </div>
      ) : (
        <Settings prefs={prefs.data} />
      )}
    </div>
  )
}
