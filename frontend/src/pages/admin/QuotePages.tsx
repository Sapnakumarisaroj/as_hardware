import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { useToast } from '@/components/toast'
import { useSession } from '@/features/admin/session'
import {
  dateTime,
  Facts,
  FilterBar,
  FilterSelect,
  FormDialog,
  ListView,
  PageHeader,
  Panel,
  SearchBox,
  StatusBadge,
  TextAreaField,
  useListParams,
  type Column,
} from '@/features/admin/ui'
import {
  ADMIN_QUOTES_PAGE_SIZE,
  useAdminQuote,
  useAdminQuotes,
  useRejectQuote,
  useSendQuotation,
  type AdminQuote,
} from '@/features/quotes/api'
import { isNotFound } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from '../NotFoundPage'

const STATUSES: [string, string][] = [
  ['requested', 'Waiting for a quotation'],
  ['quoted', 'Quotation sent'],
  ['accepted', 'Accepted'],
  ['ordered', 'Ordered'],
  ['declined', 'Declined'],
  ['rejected', 'Rejected'],
  ['cancelled', 'Cancelled'],
  ['expired', 'Expired'],
]

const BUYER_TYPES: Record<string, string> = {
  individual: 'Home / individual',
  carpenter: 'Carpenter',
  contractor: 'Contractor',
  interior_designer: 'Interior designer',
  business: 'Business',
}

const COLUMNS: Column<AdminQuote>[] = [
  {
    header: 'Quote',
    cell: (row) => (
      <>
        <Link to={`/admin/quotes/${row.id}`} className="font-semibold underline-offset-2 hover:underline">
          {row.number}
        </Link>
        <span className="block text-xs text-ink-600">{dateTime(row.created_at)}</span>
      </>
    ),
  },
  {
    header: 'Customer',
    cell: (row) => (
      <>
        {row.business_name || row.customer_name || row.customer_email}
        <span className="block text-xs text-ink-600">{BUYER_TYPES[row.buyer_type] ?? row.buyer_type}</span>
      </>
    ),
  },
  { header: 'Lines', numeric: true, cell: (row) => row.items.length },
  { header: 'List price', numeric: true, cell: (row) => formatPrice(row.list_goods_total) },
  { header: 'Quoted', numeric: true, cell: (row) => (row.quoted_goods_total ? formatPrice(row.quoted_goods_total) : '—') },
  { header: 'Status', cell: (row) => <StatusBadge status={row.status} text={row.status_label} /> },
]

export function AdminQuotesPage() {
  usePageMeta('Quotes')
  const list = useListParams()
  const quotes = useAdminQuotes({ page: list.page, status: list.get('status'), q: list.get('q') })
  return (
    <>
      <PageHeader title="Quotes" description="Bulk quote requests from customers. Price every line and send a quotation." />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by quote number or email" />
        <FilterSelect list={list} name="status" label="Status" options={STATUSES} />
      </FilterBar>
      <ListView
        query={quotes}
        list={list}
        caption="Quote requests"
        columns={COLUMNS}
        rowKey={(row) => row.id}
        pageSize={ADMIN_QUOTES_PAGE_SIZE}
        empty="No quote requests yet"
        emptyHint="Customers request quotes from their cart."
      />
    </>
  )
}

/** Unit prices per line (GST inclusive). The server rejects a price above MRP or a missing line. */
function QuotationForm({ quote, onClose }: { quote: AdminQuote; onClose: () => void }) {
  const send = useSendQuotation(quote.id)
  const toast = useToast()
  const [prices, setPrices] = useState<Record<number, string>>(() =>
    Object.fromEntries(quote.items.map((item) => [item.id, item.quoted_unit_price ?? item.list_unit_price])),
  )
  const [days, setDays] = useState('7')
  const [note, setNote] = useState(quote.shop_note)
  const [problem, setProblem] = useState('')

  function submit() {
    const lines = quote.items.map((item) => ({ item_id: item.id, unit_price: (prices[item.id] ?? '').trim() }))
    const bad = quote.items.find((item) => {
      const text = (prices[item.id] ?? '').trim()
      const value = Number(text)
      return !text || !(value > 0) || value > Number(item.unit_mrp)
    })
    if (bad) {
      setProblem(`Enter a price above ₹0 and not above the MRP (${formatPrice(bad.unit_mrp)}) for ${bad.product_name}.`)
      return
    }
    setProblem('')
    send.mutate(
      { lines, valid_days: Number(days) || 7, shop_note: note.trim() },
      {
        onSuccess: () => {
          toast.show(`Quotation ${quote.number} sent to the customer.`)
          onClose()
        },
      },
    )
  }

  return (
    <FormDialog
      open
      title={quote.status === 'quoted' ? 'Revise quotation' : 'Send quotation'}
      submitLabel="Send quotation"
      busy={send.isPending}
      error={send.error}
      problem={problem}
      onSubmit={submit}
      onClose={onClose}
    >
      <ul className="space-y-3">
        {quote.items.map((item) => (
          <li key={item.id} className="grid gap-1 text-sm sm:grid-cols-[1fr_8rem] sm:items-end">
            <div>
              <p className="font-medium">{item.product_name}</p>
              <p className="text-xs text-ink-600">
                {item.sku} · Qty {item.quantity} · List {formatPrice(item.list_unit_price)} · MRP {formatPrice(item.unit_mrp)}
              </p>
            </div>
            <div>
              <label htmlFor={`price-${item.id}`} className="sr-only">
                Unit price for {item.product_name}
              </label>
              <input
                id={`price-${item.id}`}
                inputMode="decimal"
                className="input text-right"
                value={prices[item.id] ?? ''}
                onChange={(e) => setPrices((current) => ({ ...current, [item.id]: e.target.value }))}
              />
            </div>
          </li>
        ))}
      </ul>
      <div>
        <label htmlFor="valid-days" className="label">
          Valid for (days)
        </label>
        <input id="valid-days" type="number" min={1} max={90} className="input w-28" value={days} onChange={(e) => setDays(e.target.value)} />
      </div>
      <TextAreaField id="shop-note" label="Note to the customer" value={note} onChange={setNote} maxLength={1000} />
    </FormDialog>
  )
}

function RejectForm({ quote, onClose }: { quote: AdminQuote; onClose: () => void }) {
  const reject = useRejectQuote(quote.id)
  const toast = useToast()
  const [reason, setReason] = useState('')
  return (
    <FormDialog
      open
      title={`Reject ${quote.number}`}
      submitLabel="Reject request"
      busy={reject.isPending}
      error={reject.error}
      onSubmit={() => {
        if (!reason.trim()) return
        reject.mutate(reason.trim(), {
          onSuccess: () => {
            toast.show('Request rejected.')
            onClose()
          },
        })
      }}
      onClose={onClose}
    >
      <TextAreaField id="reject-reason" label="Reason (shown to the customer)" value={reason} onChange={setReason} required maxLength={255} />
    </FormDialog>
  )
}

export function AdminQuotePage() {
  const { id } = useParams()
  const session = useSession()
  const query = useAdminQuote(id)
  const [dialog, setDialog] = useState<'quote' | 'reject' | null>(null)
  usePageMeta(query.data ? `Quote ${query.data.number}` : 'Quote')
  if (query.isPending) return <PageSpinner label="Loading the quote…" />
  if (isNotFound(query.error)) return <NotFoundPage />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn’t load the quote" />
  const quote = query.data
  const open = quote.status === 'requested' || quote.status === 'quoted'
  const canEdit = session.is_admin && open

  return (
    <>
      <PageHeader
        title={`Quote ${quote.number}`}
        crumbs={[{ label: 'Quotes', to: '/admin/quotes' }]}
        actions={<StatusBadge status={quote.status} text={quote.status_label} />}
      />
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Panel title="Lines">
            <ul className="divide-y divide-steel-100 text-sm">
              {quote.items.map((item) => (
                <li key={item.id} className="flex flex-wrap justify-between gap-2 py-2">
                  <div className="min-w-0">
                    <p className="font-medium">{item.product_name}</p>
                    <p className="text-xs text-ink-600">
                      {item.sku} · Qty {item.quantity}
                      {item.customer_note && ` · “${item.customer_note}”`}
                    </p>
                  </div>
                  <div className="text-right tabular-nums">
                    <p>List {formatPrice(item.list_line_total)}</p>
                    {item.quoted_line_total && <p className="font-semibold">Quoted {formatPrice(item.quoted_line_total)}</p>}
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
          {quote.customer_note && (
            <Panel title="Customer’s note">
              <p className="whitespace-pre-wrap text-sm">{quote.customer_note}</p>
            </Panel>
          )}
        </div>
        <div className="space-y-5">
          <Panel title="Details">
            <Facts
              items={[
                ['Customer', quote.customer_name || '—'],
                ['Email', quote.customer_email ? <a href={`mailto:${quote.customer_email}`}>{quote.customer_email}</a> : '—'],
                ['Phone', quote.customer_phone ? <a href={`tel:${quote.customer_phone}`}>{quote.customer_phone}</a> : '—'],
                ['Buyer type', BUYER_TYPES[quote.buyer_type] ?? quote.buyer_type],
                ['Business', quote.business_name || '—'],
                ['GSTIN', quote.gstin || '—'],
                ['List price', formatPrice(quote.list_goods_total)],
                ['Quoted', quote.quoted_goods_total ? formatPrice(quote.quoted_goods_total) : '—'],
                ['Valid until', quote.valid_until ? dateTime(quote.valid_until) : '—'],
                [
                  'Order',
                  quote.order_number ? (
                    <Link to={`/admin/orders/${quote.order_number}`} className="underline-offset-2 hover:underline">
                      {quote.order_number}
                    </Link>
                  ) : (
                    '—'
                  ),
                ],
              ]}
            />
          </Panel>
          {canEdit && (
            <div className="space-y-2">
              <button type="button" className="btn-primary w-full" onClick={() => setDialog('quote')}>
                {quote.status === 'quoted' ? 'Revise quotation' : 'Send quotation'}
              </button>
              <button type="button" className="btn-secondary w-full" onClick={() => setDialog('reject')}>
                Reject request
              </button>
            </div>
          )}
          {open && !session.is_admin && <p className="text-sm text-ink-600">Only administrators can send quotations.</p>}
          {quote.closed_reason && <p className="text-sm text-ink-600">Reason: {quote.closed_reason}</p>}
        </div>
      </div>
      {dialog === 'quote' && <QuotationForm quote={quote} onClose={() => setDialog(null)} />}
      {dialog === 'reject' && <RejectForm quote={quote} onClose={() => setDialog(null)} />}
    </>
  )
}
