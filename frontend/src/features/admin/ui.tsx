/* eslint-disable react-refresh/only-export-components */
import { useId, useState, type FormEvent, type ReactNode, type SelectHTMLAttributes } from 'react'
import { Link, useSearchParams } from 'react-router'

import { EmptyState, ErrorState, Spinner } from '@/components/feedback'
import { ChevronRightIcon } from '@/components/icons'
import { Modal } from '@/components/Modal'
import { Pagination } from '@/components/Pagination'
import { ApiError } from '@/lib/api/errors'

import { PAGE_SIZE } from './api'

// --- Text ----------------------------------------------------------------------------------------

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  })
}

export function errorMessage(error: unknown, fallback = 'That didn’t work. Please try again.'): string {
  if (error instanceof ApiError) {
    const fields = Object.entries(error.fieldErrors())
    if (fields.length) return fields.map(([field, messages]) => `${label(field)}: ${messages.join(' ')}`).join(' ')
    return error.message
  }
  return fallback
}

/** "max_discount_amount" → "Max discount amount" */
export function label(code: string): string {
  const text = code.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

// --- Page frame ----------------------------------------------------------------------------------

export interface Crumb {
  label: string
  to?: string
}

export function PageHeader({
  title,
  description,
  crumbs = [],
  actions,
}: {
  title: string
  description?: ReactNode
  crumbs?: Crumb[]
  actions?: ReactNode
}) {
  const trail: Crumb[] = [{ label: 'Dashboard', to: '/admin' }, ...crumbs, { label: title }]
  return (
    <header className="mb-5">
      {(crumbs.length > 0 || title !== 'Dashboard') && (
        <nav aria-label="Breadcrumb" className="mb-2 text-sm text-ink-600">
          <ol className="flex flex-wrap items-center gap-1">
            {trail.map((crumb, index) => (
              <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                {index > 0 && <ChevronRightIcon className="size-3.5 text-steel-400" />}
                {crumb.to && index < trail.length - 1 ? (
                  <Link to={crumb.to} className="hover:text-ink-900 hover:underline">
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="page" className="font-medium text-ink-900">
                    {crumb.label}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">{title}</h1>
          {description && <p className="mt-1 max-w-2xl text-sm text-ink-600">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}

export function Panel({
  title,
  action,
  children,
  className = '',
}: {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  const id = useId()
  return (
    <section aria-labelledby={title ? id : undefined} className={`rounded-lg bg-white p-4 ring-1 ring-steel-200 ${className}`}>
      {title && (
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 id={id} className="text-base font-bold">
            {title}
          </h2>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function StatCard({
  label: name,
  value,
  hint,
  to,
  tone = 'plain',
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  to?: string
  tone?: 'plain' | 'warn'
}) {
  const body = (
    <>
      <dt className="text-sm text-ink-600">{name}</dt>
      <dd className={`mt-1 text-2xl font-extrabold tracking-tight ${tone === 'warn' ? 'text-danger-600' : ''}`}>{value}</dd>
      {hint && <dd className="mt-0.5 text-xs text-ink-600">{hint}</dd>}
    </>
  )
  const frame = 'block rounded-lg bg-white p-4 ring-1 ring-steel-200'
  return to ? (
    <Link to={to} className={`${frame} transition-shadow hover:shadow-md`} aria-label={`${name}: open`}>
      {body}
    </Link>
  ) : (
    <div className={frame}>{body}</div>
  )
}

export function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([name, value]) => (
        <div key={name} className="contents">
          <dt className="text-ink-600">{name}</dt>
          <dd className="font-medium break-words">{value === '' || value === null || value === undefined ? '—' : value}</dd>
        </div>
      ))}
    </dl>
  )
}

// --- Badges --------------------------------------------------------------------------------------

export type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'info'

const TONES: Record<Tone, string> = {
  neutral: 'bg-steel-100 text-ink-800',
  good: 'bg-success-600/10 text-success-600',
  warn: 'bg-amber-100 text-ink-900',
  bad: 'bg-danger-600/10 text-danger-600',
  info: 'bg-ink-900 text-white',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${TONES[tone]}`}>
      {children}
    </span>
  )
}

const STATUS_TONES: Record<string, Tone> = {
  // orders and shipments
  pending: 'warn',
  confirmed: 'info',
  processing: 'info',
  packed: 'info',
  assigned: 'info',
  accepted: 'info',
  picked_up: 'info',
  out_for_delivery: 'info',
  delivered: 'good',
  delivery_failed: 'bad',
  failed: 'bad',
  cancelled: 'neutral',
  return_requested: 'warn',
  returned: 'neutral',
  // payments and refunds
  paid: 'good',
  processed: 'good',
  refunded: 'neutral',
  partially_refunded: 'neutral',
  // returns
  requested: 'warn',
  approved: 'info',
  rejected: 'bad',
  received: 'good',
  // rules, products, riders, support
  live: 'good',
  scheduled: 'info',
  expired: 'neutral',
  inactive: 'neutral',
  draft: 'warn',
  deleted: 'bad',
  available: 'good',
  busy: 'warn',
  offline: 'neutral',
  open: 'warn',
  waiting_customer: 'info',
  resolved: 'good',
  closed: 'neutral',
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  delivery_failed: 'Delivery failed',
  waiting_customer: 'Waiting for customer',
  busy: 'On a delivery',
  draft: 'Not published',
}

export function StatusBadge({ status, text }: { status: string; text?: string }) {
  return <Badge tone={STATUS_TONES[status] ?? 'neutral'}>{text ?? STATUS_LABELS[status] ?? label(status)}</Badge>
}

// --- Lists ---------------------------------------------------------------------------------------

/** Filters and the page number live in the URL, so a list can be bookmarked, shared and reloaded. */
export function useListParams() {
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page')) || 1)

  function get(key: string): string {
    return params.get(key) ?? ''
  }

  /** Changing a filter goes back to page 1. */
  function set(changes: Record<string, string>) {
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        next.delete('page')
        for (const [key, value] of Object.entries(changes)) {
          if (value) next.set(key, value)
          else next.delete(key)
        }
        return next
      },
      { replace: true },
    )
  }

  function setPage(value: number) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (value > 1) next.set('page', String(value))
      else next.delete('page')
      return next
    })
    window.scrollTo(0, 0)
  }

  function clear() {
    setParams(
      (current) => {
        const next = new URLSearchParams()
        const tab = current.get('tab')
        if (tab) next.set('tab', tab)
        return next
      },
      { replace: true },
    )
  }

  return { page, get, set, setPage, clear, hasFilters: [...params.keys()].some((key) => key !== 'page' && key !== 'tab') }
}

export type ListParams = ReturnType<typeof useListParams>

/** The search box asks the server only when submitted, not on every key press. */
export function SearchBox({ list, placeholder, name = 'q' }: { list: ListParams; placeholder: string; name?: string }) {
  const current = list.get(name)
  const [text, setText] = useState(current)
  const [seen, setSeen] = useState(current)
  if (seen !== current) {
    setSeen(current)
    setText(current)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    list.set({ [name]: text.trim() })
  }

  return (
    <form role="search" onSubmit={submit} className="flex min-w-0 flex-1 gap-2 sm:max-w-md">
      <label className="sr-only" htmlFor={`search-${name}`}>
        {placeholder}
      </label>
      <input
        id={`search-${name}`}
        type="search"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={placeholder}
        className="input"
      />
      <button type="submit" className="btn-dark">
        Search
      </button>
    </form>
  )
}

export function FilterSelect({
  list,
  name,
  label: text,
  options,
  all = 'All',
}: {
  list: ListParams
  name: string
  label: string
  options: [string, string][]
  all?: string
}) {
  const id = `filter-${name}`
  return (
    <div>
      <label htmlFor={id} className="sr-only">
        {text}
      </label>
      <select id={id} className="input w-auto" value={list.get(name)} onChange={(e) => list.set({ [name]: e.target.value })}>
        <option value="">
          {text}: {all}
        </option>
        {options.map(([value, name_]) => (
          <option key={value} value={value}>
            {name_}
          </option>
        ))}
      </select>
    </div>
  )
}

export function FilterBar({ list, children }: { list: ListParams; children: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      {children}
      {list.hasFilters && (
        <button
          type="button"
          className="text-sm font-semibold text-ink-600 underline-offset-2 hover:underline"
          onClick={list.clear}
        >
          Clear filters
        </button>
      )}
    </div>
  )
}

export interface Column<T> {
  header: string
  cell: (row: T) => ReactNode
  /** Right-aligned numbers and money. */
  numeric?: boolean
  className?: string
}

/**
 * One table for every screen size: a normal table from `md` up, and one card per row on phones
 * (each value labelled with its column header).
 */
export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
}: {
  caption: string
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
}) {
  return (
    <div className="overflow-x-auto rounded-lg bg-white ring-1 ring-steel-200 max-md:bg-transparent max-md:ring-0">
      <table className="w-full text-left text-sm max-md:block">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-steel-200 bg-steel-50 text-xs uppercase tracking-wide text-ink-600 max-md:sr-only">
          <tr>
            {columns.map((column) => (
              <th key={column.header} scope="col" className={`px-3 py-2.5 font-semibold ${column.numeric ? 'text-right' : ''}`}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="max-md:block max-md:space-y-3">
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className="border-b border-steel-100 last:border-0 max-md:block max-md:rounded-lg max-md:border-0 max-md:bg-white max-md:p-3 max-md:ring-1 max-md:ring-steel-200"
            >
              {columns.map((column) => (
                <td
                  key={column.header}
                  data-label={column.header}
                  className={`px-3 py-2.5 align-top max-md:flex max-md:items-start max-md:justify-between max-md:gap-4 max-md:px-0 max-md:py-1 max-md:text-right max-md:before:shrink-0 max-md:before:text-left max-md:before:text-xs max-md:before:font-semibold max-md:before:text-ink-600 max-md:before:content-[attr(data-label)] ${column.numeric ? 'text-right tabular-nums' : ''} ${column.className ?? ''}`}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface ListQuery<T> {
  isPending: boolean
  isError: boolean
  isFetching: boolean
  error: unknown
  data?: { count: number; results: T[] }
  refetch: () => unknown
}

/** Loading, error, empty and paginated states of a server list, in one place. */
export function ListView<T>({
  query,
  list,
  caption,
  columns,
  rowKey,
  empty,
  emptyHint,
  pageSize = PAGE_SIZE,
  page,
  onPage,
}: {
  query: ListQuery<T>
  list?: ListParams
  caption: string
  columns: Column<T>[]
  rowKey: (row: T) => string | number
  empty: string
  emptyHint?: ReactNode
  pageSize?: number
  page?: number
  onPage?: (page: number) => void
}) {
  if (query.isPending) {
    return (
      <div className="flex justify-center rounded-lg bg-white py-16 ring-1 ring-steel-200">
        <Spinner label={`Loading ${caption.toLowerCase()}…`} />
      </div>
    )
  }
  if (query.isError || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} title={`Couldn’t load ${caption.toLowerCase()}`} />
  }
  const { count, results } = query.data
  if (results.length === 0) {
    return (
      <EmptyState title={list?.hasFilters ? 'Nothing matches these filters' : empty}>
        {list?.hasFilters ? 'Try another search or clear the filters.' : emptyHint}
      </EmptyState>
    )
  }
  const current = page ?? list?.page ?? 1
  const first = (current - 1) * pageSize + 1
  return (
    <div aria-busy={query.isFetching}>
      <p className="mb-2 text-sm text-ink-600" role="status">
        {first.toLocaleString('en-IN')}–{(first + results.length - 1).toLocaleString('en-IN')} of{' '}
        {count.toLocaleString('en-IN')}
      </p>
      <DataTable caption={caption} columns={columns} rows={results} rowKey={rowKey} />
      <Pagination page={current} pageSize={pageSize} total={count} onChange={onPage ?? list?.setPage ?? (() => undefined)} />
    </div>
  )
}

export function Tabs({ tabs, current, onChange, label: name }: { tabs: [string, string][]; current: string; onChange: (tab: string) => void; label: string }) {
  return (
    <div role="tablist" aria-label={name} className="scrollbar-none mb-4 flex gap-1 overflow-x-auto border-b border-steel-200">
      {tabs.map(([value, text]) => (
        <button
          key={value}
          type="button"
          role="tab"
          aria-selected={current === value}
          onClick={() => onChange(value)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm font-semibold whitespace-nowrap ${current === value ? 'border-amber-500 text-ink-900' : 'border-transparent text-ink-600 hover:text-ink-900'}`}
        >
          {text}
        </button>
      ))}
    </div>
  )
}

// --- Dialogs and forms ---------------------------------------------------------------------------

/** Asks before anything that changes money, stock, access or what customers see. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  danger = false,
  busy = false,
  error,
  note,
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  children?: ReactNode
  confirmLabel: string
  danger?: boolean
  busy?: boolean
  error?: unknown
  /** Ask for a note or reason along with the confirmation. */
  note?: { label: string; required?: boolean; placeholder?: string }
  onConfirm: (note: string) => void
  onClose: () => void
}) {
  const [text, setText] = useState('')
  const [wasOpen, setWasOpen] = useState(open)
  if (wasOpen !== open) {
    setWasOpen(open)
    if (open) setText('')
  }
  const id = useId()
  const missing = Boolean(note?.required) && !text.trim()

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className={danger ? 'btn-dark bg-danger-600 hover:bg-danger-600/90' : 'btn-primary'}
            onClick={() => onConfirm(text.trim())}
            disabled={busy || missing}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      }
    >
      <div className="space-y-3 text-sm">
        {children}
        {note && (
          <div>
            <label htmlFor={id} className="label">
              {note.label}
              {note.required && <span className="text-danger-600"> *</span>}
            </label>
            <textarea
              id={id}
              className="input"
              rows={2}
              maxLength={200}
              value={text}
              placeholder={note.placeholder}
              onChange={(event) => setText(event.target.value)}
            />
          </div>
        )}
        {Boolean(error) && (
          <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-danger-600">
            {errorMessage(error)}
          </p>
        )}
      </div>
    </Modal>
  )
}

export function FormDialog({
  open,
  title,
  children,
  submitLabel = 'Save',
  busy = false,
  error,
  problem,
  onSubmit,
  onClose,
}: {
  open: boolean
  title: string
  children: ReactNode
  submitLabel?: string
  busy?: boolean
  error?: unknown
  /** Something the form itself found wrong, before the server was asked. */
  problem?: string
  onSubmit: () => void
  onClose: () => void
}) {
  const id = useId()
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" form={id} className="btn-primary" disabled={busy}>
            {busy ? 'Saving…' : submitLabel}
          </button>
        </div>
      }
    >
      <form
        id={id}
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit()
        }}
      >
        {children}
        {(problem || Boolean(error)) && (
          <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600">
            {problem || errorMessage(error)}
          </p>
        )}
      </form>
    </Modal>
  )
}

export function SelectField({
  id,
  label: text,
  children,
  hint,
  className = '',
  ...select
}: { id: string; label: string; hint?: string } & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className={className}>
      <label htmlFor={id} className="label">
        {text}
        {select.required && <span className="text-danger-600"> *</span>}
      </label>
      <select id={id} name={id} className="input" {...select}>
        {children}
      </select>
      {hint && <p className="mt-1 text-xs text-ink-600">{hint}</p>}
    </div>
  )
}

export function TextAreaField({
  id,
  label: text,
  value,
  onChange,
  rows = 3,
  hint,
  required,
  maxLength,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  rows?: number
  hint?: string
  required?: boolean
  maxLength?: number
}) {
  return (
    <div>
      <label htmlFor={id} className="label">
        {text}
        {required && <span className="text-danger-600"> *</span>}
      </label>
      <textarea
        id={id}
        className="input"
        rows={rows}
        value={value}
        required={required}
        maxLength={maxLength}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint && <p className="mt-1 text-xs text-ink-600">{hint}</p>}
    </div>
  )
}

export function CheckField({
  id,
  label: text,
  checked,
  onChange,
  hint,
  disabled,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  hint?: string
  disabled?: boolean
}) {
  return (
    <div className="flex items-start gap-2">
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 size-4 accent-amber-500"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <label htmlFor={id} className="text-sm">
        <span className="font-medium">{text}</span>
        {hint && <span className="block text-xs text-ink-600">{hint}</span>}
      </label>
    </div>
  )
}

/** Shown in place of a section the signed-in role may not use (the API refuses it as well). */
export function NotAllowed({ what }: { what: string }) {
  return (
    <EmptyState
      title="For administrators only"
      action={
        <Link to="/admin" className="btn-primary">
          Back to the dashboard
        </Link>
      }
    >
      {what} can be managed by an administrator. Ask one if something needs to change.
    </EmptyState>
  )
}
