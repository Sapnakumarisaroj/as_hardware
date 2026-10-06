import { useState } from 'react'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import { useSession } from '@/features/admin/session'
import {
  Badge,
  ConfirmDialog,
  dateTime,
  FilterBar,
  FilterSelect,
  FormDialog,
  ListView,
  NotAllowed,
  PageHeader,
  Panel,
  SearchBox,
  SelectField,
  StatusBadge,
  Tabs,
  TextAreaField,
  useListParams,
  type Column,
} from '@/features/admin/ui'
import {
  useDeleteTemplate,
  useNotificationChannels,
  useNotificationEvents,
  useNotificationLog,
  usePreview,
  useRetryFailed,
  useRetryNotification,
  useSaveTemplate,
  useSwitchChannel,
  useSwitchEventChannel,
  type Channel,
  type ChannelStatus,
  type EventChannel,
  type EventSpec,
  type Language,
  type LogRow,
  type Preview,
} from '@/features/notifications/api'
import { usePageMeta } from '@/lib/usePageMeta'

const CHANNEL_NAMES: Record<Channel, string> = { in_app: 'In-app', email: 'Email', whatsapp: 'WhatsApp', sms: 'SMS' }
const LANGUAGES: [Language, string][] = [
  ['en', 'English'],
  ['hi', 'Hindi'],
  ['hi-latn', 'Hinglish'],
]
const AUDIENCE = { customer: 'Customers', rider: 'Delivery partners', staff: 'Store staff' }
const STATUS_TEXT = { pending: 'Waiting', sent: 'Sent', failed: 'Failed', skipped: 'Not sent' }

// --- Channels ---------------------------------------------------------------------------------------

function providerBadge(row: ChannelStatus) {
  if (row.channel === 'in_app') return <Badge tone="good">Built in</Badge>
  if (!row.configured) return <Badge tone="warn">Not set up</Badge>
  if (row.mock) return <Badge tone="info">Test mode: nothing really sent</Badge>
  return <Badge tone="good">Live</Badge>
}

function Channels() {
  const channels = useNotificationChannels()
  const switchChannel = useSwitchChannel()
  const toast = useToast()
  const [asking, setAsking] = useState<ChannelStatus | null>(null)
  if (channels.isPending) return <PageSpinner label="Loading channels…" />
  if (channels.isError) return <ErrorState error={channels.error} onRetry={() => void channels.refetch()} title="Couldn’t load channels" />

  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        {channels.data.map((row) => (
          <Panel
            key={row.channel}
            title={CHANNEL_NAMES[row.channel]}
            action={
              row.channel === 'in_app' ? (
                <Badge tone="good">Always on</Badge>
              ) : (
                <button
                  type="button"
                  className={row.enabled ? 'btn-secondary' : 'btn-primary'}
                  aria-label={`${row.enabled ? 'Turn off' : 'Turn on'} ${CHANNEL_NAMES[row.channel]}`}
                  onClick={() => setAsking(row)}
                >
                  {row.enabled ? 'Turn off' : 'Turn on'}
                </button>
              )
            }
          >
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {row.channel !== 'in_app' && <StatusBadge status={row.enabled ? 'live' : 'inactive'} text={row.enabled ? 'On' : 'Off'} />}
              {providerBadge(row)}
              <span className="text-ink-600">Provider: {row.provider}</span>
            </div>
            <dl className="mt-3 grid grid-cols-4 gap-2 text-center text-sm" aria-label={`${CHANNEL_NAMES[row.channel]}, last 24 hours`}>
              {(['sent', 'pending', 'failed', 'skipped'] as const).map((status) => (
                <div key={status} className="rounded-md bg-steel-50 p-2">
                  <dt className="text-xs text-ink-600">{STATUS_TEXT[status]}</dt>
                  <dd className={`font-bold tabular-nums ${status === 'failed' && row.last_24h.failed ? 'text-danger-600' : ''}`}>
                    {row.last_24h[status]}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-xs text-ink-600">Last 24 hours · last sent {dateTime(row.last_sent_at)}</p>
            {row.last_error && <p className="mt-1 text-xs text-danger-600">Last failure: {row.last_error}</p>}
            {row.channel === 'whatsapp' && !row.live && (
              <p className="mt-2 text-xs text-ink-600">
                Real WhatsApp messages need the shop’s own WhatsApp Business account and approved templates (Meta charges per
                conversation). Until then messages are recorded here but not delivered; customers still get them in the app and
                by email.
              </p>
            )}
            {row.channel === 'sms' && !row.live && (
              <p className="mt-2 text-xs text-ink-600">No SMS gateway is connected (they are paid services). SMS stays off.</p>
            )}
          </Panel>
        ))}
      </div>
      <ConfirmDialog
        open={asking !== null}
        title={asking?.enabled ? `Turn ${CHANNEL_NAMES[asking.channel]} off?` : `Turn ${asking ? CHANNEL_NAMES[asking.channel] : ''} on?`}
        confirmLabel={asking?.enabled ? 'Turn off' : 'Turn on'}
        danger={asking?.enabled}
        busy={switchChannel.isPending}
        error={switchChannel.error}
        onClose={() => {
          switchChannel.reset()
          setAsking(null)
        }}
        onConfirm={() =>
          asking &&
          switchChannel.mutate(
            { channel: asking.channel, enabled: !asking.enabled },
            {
              onSuccess: () => {
                toast.show(`${CHANNEL_NAMES[asking.channel]} turned ${asking.enabled ? 'off' : 'on'}.`)
                setAsking(null)
              },
            },
          )
        }
      >
        {asking?.enabled
          ? 'No message will go out on this channel, for any event, until it is turned on again. In-app messages continue.'
          : 'Events switched on for this channel will start using it for customers who allow it.'}
      </ConfirmDialog>
    </>
  )
}

// --- Messages (events and their words) --------------------------------------------------------------

interface Draft {
  event: EventSpec
  channel: EventChannel
  language: Language
}

function wordsFor(draft: Draft) {
  const own = draft.channel.templates.find((t) => t.language === draft.language)
  return {
    id: own?.id,
    title: own?.title ?? draft.channel.default_title,
    body: own?.body ?? draft.channel.default_body,
    provider_template: own?.provider_template ?? draft.channel.default_provider_template,
  }
}

function WordsEditor({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const [language, setLanguage] = useState<Language>(draft.language)
  const start = wordsFor({ ...draft, language })
  const [values, setValues] = useState(start)
  const [shownFor, setShownFor] = useState(language)
  if (shownFor !== language) {
    setShownFor(language)
    setValues(wordsFor({ ...draft, language }))
  }
  const save = useSaveTemplate()
  const remove = useDeleteTemplate()
  const preview = usePreview()
  const [shown, setShown] = useState<Preview | null>(null)
  const toast = useToast()
  const { event, channel } = draft
  const whatsapp = channel.channel === 'whatsapp'

  return (
    <FormDialog
      open
      title={`${event.label} · ${CHANNEL_NAMES[channel.channel]}`}
      busy={save.isPending}
      error={save.error ?? remove.error}
      onClose={onClose}
      onSubmit={() =>
        save.mutate(
          { id: values.id, event: event.key, channel: channel.channel, language, title: values.title, body: values.body, provider_template: whatsapp ? values.provider_template : '' },
          {
            onSuccess: () => {
              toast.show('Words saved.')
              onClose()
            },
          },
        )
      }
    >
      <SelectField id="words-language" label="Language" value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
        {LANGUAGES.map(([value, text]) => (
          <option key={value} value={value}>
            {text}
            {channel.templates.some((t) => t.language === value) ? ' (own words)' : ''}
          </option>
        ))}
      </SelectField>
      <p className="text-xs text-ink-600">
        Customers who chose a language get its words; without them they get the English words.
      </p>
      {channel.channel !== 'whatsapp' && channel.channel !== 'sms' && (
        <FormField id="words-title" label="Title" maxLength={150} value={values.title} onChange={(e) => setValues({ ...values, title: e.target.value })} />
      )}
      <TextAreaField id="words-body" label="Message" rows={4} required maxLength={2000} value={values.body} onChange={(body) => setValues({ ...values, body })} />
      <div className="text-xs text-ink-600">
        <p>Variables you can use (type them with the braces):</p>
        <p className="mt-1 flex flex-wrap gap-1">
          {event.variables.map((name) => (
            <code key={name} className={`rounded px-1.5 py-0.5 ${event.secret_variables.includes(name) ? 'bg-amber-500/20' : 'bg-steel-100'}`}>
              {`{${name}}`}
            </code>
          ))}
        </p>
        {event.secret_variables.length > 0 && (
          <p className="mt-1">The highlighted value is filled in only when the message is sent and is never saved.</p>
        )}
      </div>
      {whatsapp && (
        <FormField
          id="words-provider-template"
          label="Approved WhatsApp template name"
          hint="The template’s name in WhatsApp Manager. Its body must use the same variables in the same order."
          maxLength={80}
          value={values.provider_template}
          onChange={(e) => setValues({ ...values, provider_template: e.target.value })}
        />
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-secondary"
          disabled={preview.isPending}
          onClick={() => preview.mutate({ event: event.key, channel: channel.channel, title: values.title, body: values.body }, { onSuccess: setShown })}
        >
          Preview
        </button>
        {values.id !== undefined && (
          <button
            type="button"
            className="btn-secondary"
            disabled={remove.isPending}
            onClick={() =>
              values.id !== undefined &&
              remove.mutate(values.id, {
                onSuccess: () => {
                  toast.show('Back to the built-in words.')
                  onClose()
                },
              })
            }
          >
            Use the built-in words
          </button>
        )}
      </div>
      {shown && (
        <div className="rounded-md bg-steel-50 p-3 text-sm" aria-live="polite" data-testid="preview">
          {shown.ok ? (
            <>
              {shown.title && <p className="font-semibold">{shown.title}</p>}
              <p className="whitespace-pre-line">{shown.body}</p>
              <p className="mt-1 text-xs text-ink-600">Example values. Customer: Asha.</p>
            </>
          ) : (
            <ul className="list-disc pl-4 text-danger-600">
              {Object.values(shown.problems)
                .flat()
                .map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
            </ul>
          )}
        </div>
      )}
    </FormDialog>
  )
}

function Messages() {
  const events = useNotificationEvents()
  const switchEvent = useSwitchEventChannel()
  const toast = useToast()
  const [editing, setEditing] = useState<Draft | null>(null)
  const [audience, setAudience] = useState<'' | EventSpec['audience']>('')
  if (events.isPending) return <PageSpinner label="Loading messages…" />
  if (events.isError) return <ErrorState error={events.error} onRetry={() => void events.refetch()} title="Couldn’t load messages" />
  const rows = events.data.results.filter((e) => !audience || e.audience === audience)

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label htmlFor="audience" className="sr-only">
          For
        </label>
        <select id="audience" className="input w-auto" value={audience} onChange={(e) => setAudience(e.target.value as typeof audience)}>
          <option value="">For: everyone</option>
          {Object.entries(AUDIENCE).map(([value, text]) => (
            <option key={value} value={value}>
              For: {text}
            </option>
          ))}
        </select>
        <p className="text-sm text-ink-600">
          Tick a channel to send the event there. Customers’ own choices (email, WhatsApp opt-in, topics) still apply.
        </p>
      </div>
      <ul className="space-y-3" aria-label="Events">
        {rows.map((event) => (
          <li key={event.key} className="rounded-lg bg-white p-4 ring-1 ring-steel-200" data-testid={`event-${event.key}`}>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-semibold">{event.label}</h3>
              <Badge>{AUDIENCE[event.audience]}</Badge>
              <Badge>{event.category_label}</Badge>
              {event.critical && <Badge tone="warn">Always delivered</Badge>}
            </div>
            <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
              {event.channels.map((channel) => (
                <li key={channel.channel} className="flex items-center gap-2 text-sm">
                  <input
                    id={`ev-${event.key}-${channel.channel}`}
                    type="checkbox"
                    className="size-4 accent-amber-500"
                    checked={channel.enabled}
                    disabled={switchEvent.isPending}
                    onChange={(e) =>
                      switchEvent.mutate(
                        { event: event.key, channel: channel.channel, enabled: e.target.checked },
                        { onSuccess: () => toast.show(`${event.label}: ${CHANNEL_NAMES[channel.channel]} ${e.target.checked ? 'on' : 'off'}.`) },
                      )
                    }
                  />
                  <label htmlFor={`ev-${event.key}-${channel.channel}`}>{CHANNEL_NAMES[channel.channel]}</label>
                  <button
                    type="button"
                    className="text-xs font-semibold text-amber-600 hover:underline"
                    aria-label={`${channel.templates.length ? 'Own words' : 'Words'} for ${event.label} by ${CHANNEL_NAMES[channel.channel]}`}
                    onClick={() => setEditing({ event, channel, language: 'en' })}
                  >
                    {channel.templates.length ? 'Own words' : 'Words'}
                  </button>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      {switchEvent.isError && (
        <p role="alert" className="mt-3 text-sm text-danger-600">
          That change wasn’t saved. Please try again.
        </p>
      )}
      {editing && <WordsEditor draft={editing} onClose={() => setEditing(null)} />}
    </>
  )
}

// --- Delivery log ------------------------------------------------------------------------------------

function Log() {
  const list = useListParams()
  const filters: Record<string, string> = { page: String(list.page) }
  for (const key of ['status', 'channel', 'event', 'q']) if (list.get(key)) filters[key] = list.get(key)
  const log = useNotificationLog(filters)
  const events = useNotificationEvents()
  const retry = useRetryNotification()
  const retryFailed = useRetryFailed()
  const toast = useToast()
  const [askAll, setAskAll] = useState(false)

  const columns: Column<LogRow>[] = [
    { header: 'When', cell: (row) => dateTime(row.created_at) },
    {
      header: 'To',
      cell: (row) => (
        <>
          <span className="font-medium">{row.user_name || row.user_email}</span>
          <span className="block text-xs text-ink-600">{row.recipient || row.user_email}</span>
        </>
      ),
    },
    {
      header: 'Message',
      cell: (row) => (
        <>
          <span className="font-medium">{row.title}</span>
          <span className="block text-xs text-ink-600">
            {row.event}
            {row.template_name && ` · template ${row.template_name}`}
          </span>
        </>
      ),
    },
    { header: 'Channel', cell: (row) => CHANNEL_NAMES[row.channel] },
    {
      header: 'Status',
      cell: (row) => (
        <>
          <StatusBadge status={row.status === 'sent' ? 'delivered' : row.status === 'skipped' ? 'inactive' : row.status} text={STATUS_TEXT[row.status]} />
          {row.provider_status && row.provider_status !== 'sent' && <span className="block text-xs text-ink-600">{row.provider_status}</span>}
          {row.error && <span className="block max-w-56 text-xs text-danger-600">{row.error}</span>}
        </>
      ),
    },
    { header: 'Tries', numeric: true, cell: (row) => row.attempts },
    {
      header: '',
      cell: (row) =>
        row.can_retry ? (
          <button
            type="button"
            className="btn-secondary"
            disabled={retry.isPending}
            onClick={() => retry.mutate(row.id, { onSuccess: () => toast.show('Sending again.') })}
          >
            Send again
          </button>
        ) : null,
    },
  ]

  return (
    <>
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Email, order number or title" />
        <FilterSelect list={list} name="status" label="Status" options={Object.entries(STATUS_TEXT)} />
        <FilterSelect list={list} name="channel" label="Channel" options={Object.entries(CHANNEL_NAMES)} />
        <FilterSelect list={list} name="event" label="Event" options={(events.data?.results ?? []).map((e): [string, string] => [e.key, e.label])} />
        <button type="button" className="btn-secondary ml-auto" onClick={() => setAskAll(true)}>
          Send all failed again
        </button>
      </FilterBar>
      {retry.isError && (
        <p role="alert" className="mb-3 text-sm text-danger-600">
          That message can’t be sent again.
        </p>
      )}
      <ListView query={log} list={list} caption="Delivery log" columns={columns} rowKey={(row) => row.id} empty="No messages yet" />
      <ConfirmDialog
        open={askAll}
        title="Send failed messages again?"
        confirmLabel="Send again"
        busy={retryFailed.isPending}
        error={retryFailed.error}
        onClose={() => setAskAll(false)}
        onConfirm={() =>
          retryFailed.mutate(list.get('channel'), {
            onSuccess: (data) => {
              toast.show(`${data.retried} message(s) queued again.`)
              setAskAll(false)
            },
          })
        }
      >
        Up to 200 failed email, WhatsApp and SMS messages{list.get('channel') ? ` (${CHANNEL_NAMES[list.get('channel') as Channel]})` : ''} are
        tried again. Fix the cause first (for example the provider settings) or they will fail again.
      </ConfirmDialog>
    </>
  )
}

/** /admin/notifications — channels and providers, which events go where and with which words, delivery log. */
export function AdminNotificationsPage() {
  usePageMeta('Notifications')
  const session = useSession()
  const list = useListParams()
  const tab = list.get('tab') || 'channels'
  if (!session.is_admin) return <NotAllowed what="Notifications" />
  return (
    <>
      <PageHeader title="Notifications" description="What customers, delivery partners and staff are told, on which channel, and whether it arrived." />
      <Tabs
        label="Notification settings"
        current={tab}
        onChange={(value) => list.set({ tab: value === 'channels' ? '' : value, status: '', channel: '', event: '', q: '' })}
        tabs={[
          ['channels', 'Channels'],
          ['messages', 'Messages'],
          ['log', 'Delivery log'],
        ]}
      />
      {tab === 'channels' && <Channels />}
      {tab === 'messages' && <Messages />}
      {tab === 'log' && <Log />}
    </>
  )
}
