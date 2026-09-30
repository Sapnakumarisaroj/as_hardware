import { useState } from 'react'
import { Link } from 'react-router'

import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import { useRefundAction, useRefunds, useReturnAction, useReturns, type ReturnAction } from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { StaffRefund } from '@/features/admin/types'
import {
  Badge,
  CheckField,
  ConfirmDialog,
  dateTime,
  FilterBar,
  FilterSelect,
  FormDialog,
  ListView,
  PageHeader,
  SearchBox,
  StatusBadge,
  TextAreaField,
  useListParams,
  type Column,
} from '@/features/admin/ui'
import type { ReturnRequest } from '@/features/orders/types'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const orderLink = (number: string) => (
  <Link to={`/admin/orders/${number}`} className="text-xs text-ink-600 underline-offset-2 hover:underline">
    Order {number}
  </Link>
)

function StoreFilter({ list }: { list: ReturnType<typeof useListParams> }) {
  const session = useSession()
  if (session.stores.length < 2) return null
  return <FilterSelect list={list} name="store" label="Store" all="All stores" options={session.stores.map((s) => [String(s.id), s.name])} />
}

// --- Returns -------------------------------------------------------------------------------------

const RETURN_ACTIONS: Record<ReturnAction, { button: string; title: string; done: string }> = {
  approve: { button: 'Approve', title: 'Approve this return?', done: 'approved' },
  reject: { button: 'Reject', title: 'Reject this return?', done: 'rejected' },
  receive: { button: 'Items received', title: 'Items received back?', done: 'received. The refund has been started' },
}

function ReturnDialog({ target, onClose }: { target: { ret: ReturnRequest; action: ReturnAction } | null; onClose: () => void }) {
  const act = useReturnAction()
  const toast = useToast()
  const [note, setNote] = useState('')
  const [restock, setRestock] = useState(true)
  const [seen, setSeen] = useState('')
  const key = target ? `${target.ret.return_number}-${target.action}` : ''
  if (key !== seen) {
    setSeen(key)
    setNote('')
    setRestock(target ? !['damaged', 'defective'].includes(target.ret.reason) : true)
    act.reset()
  }
  if (!target) return null
  const { ret, action } = target
  const text = RETURN_ACTIONS[action]

  return (
    <FormDialog
      open
      title={text.title}
      submitLabel={text.button}
      busy={act.isPending}
      error={act.error}
      onClose={onClose}
      onSubmit={() =>
        act.mutate(
          { number: ret.return_number, action, note: note.trim(), restock },
          {
            onSuccess: () => {
              toast.show(`Return ${ret.return_number} ${text.done}.`)
              onClose()
            },
          },
        )
      }
    >
      <div className="text-sm">
        <p className="font-semibold">
          {ret.return_number} · {ret.reason_label}
        </p>
        <ul className="mt-1 text-ink-600">
          {ret.items.map((item) => (
            <li key={item.order_item_id}>
              {item.quantity} × {item.product_name} {item.variant_name} · {formatPrice(item.refund_amount)}
            </li>
          ))}
        </ul>
        {ret.details && <p className="mt-2 rounded-md bg-steel-50 px-3 py-2">“{ret.details}”</p>}
      </div>
      {action === 'receive' && (
        <>
          <p className="rounded-md bg-amber-100 px-3 py-2 text-sm">
            The refund of <strong>{formatPrice(ret.refund_amount)}</strong> ({ret.refund_method_label.toLowerCase()}) starts when you
            confirm. The amount is what the customer paid for these units; it can’t be changed here.
          </p>
          <CheckField
            id="restock"
            label="Put the items back on sale"
            hint="Leave off for damaged or defective goods."
            checked={restock}
            onChange={setRestock}
          />
        </>
      )}
      <TextAreaField
        id="return-note"
        label={action === 'reject' ? 'Reason (the customer sees it)' : 'Note (optional)'}
        rows={2}
        maxLength={255}
        required={action === 'reject'}
        value={note}
        onChange={setNote}
      />
    </FormDialog>
  )
}

export function AdminReturnsPage() {
  usePageMeta('Returns')
  const list = useListParams()
  const returns = useReturns({ page: list.page, q: list.get('q'), status: list.get('status'), store: list.get('store') })
  const [target, setTarget] = useState<{ ret: ReturnRequest; action: ReturnAction } | null>(null)

  const button = (ret: ReturnRequest, action: ReturnAction, primary = false) => (
    <button
      key={action}
      type="button"
      className={`${primary ? 'btn-primary' : 'btn-secondary'} px-2.5 py-1.5 ${action === 'reject' ? 'text-danger-600' : ''}`}
      onClick={() => setTarget({ ret, action })}
    >
      {RETURN_ACTIONS[action].button}
      {' '}
<span className="sr-only">{ret.return_number}</span>
    </button>
  )

  const columns: Column<ReturnRequest>[] = [
    {
      header: 'Return',
      cell: (ret) => (
        <>
          <span className="font-semibold">{ret.return_number}</span>
          <span className="block">{orderLink(ret.order_number)}</span>
        </>
      ),
    },
    {
      header: 'Items',
      cell: (ret) => (
        <>
          {ret.items.map((item) => `${item.quantity} × ${item.product_name}`).join(', ')}
          <span className="block text-xs text-ink-600">{ret.reason_label}</span>
        </>
      ),
    },
    {
      header: 'Refund',
      numeric: true,
      cell: (ret) => (
        <>
          {formatPrice(ret.refund_amount)}
          <span className="block text-xs text-ink-600">{ret.refund_status ? `Refund ${ret.refund_status}` : ret.refund_method_label}</span>
        </>
      ),
    },
    { header: 'Requested', cell: (ret) => dateTime(ret.created_at) },
    {
      header: 'Status',
      cell: (ret) => (
        <>
          <StatusBadge status={ret.status} text={ret.status_label} />
          {ret.pickup && <span className="mt-1 block text-xs text-ink-600">Pickup: {ret.pickup.status_label.toLowerCase()} · {ret.pickup.rider_name}</span>}
          {ret.decision_note && <span className="mt-1 block text-xs text-ink-600">{ret.decision_note}</span>}
        </>
      ),
    },
    {
      header: 'Actions',
      cell: (ret) => (
        <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
          {ret.status === 'requested' && [button(ret, 'approve', true), button(ret, 'reject')]}
          {ret.status === 'approved' && [button(ret, 'receive', true), button(ret, 'reject')]}
          {!['requested', 'approved'].includes(ret.status) && <span className="text-ink-600">—</span>}
        </span>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Returns"
        description="Approve or reject a request, then confirm when the items are back. The refund is calculated by the system and starts on receipt."
      />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by return, order or customer" />
        <FilterSelect
          list={list}
          name="status"
          label="Status"
          options={[
            ['open', 'Open (to decide or receive)'],
            ['requested', 'Waiting for a decision'],
            ['approved', 'Approved, not received'],
            ['received', 'Received'],
            ['rejected', 'Rejected'],
            ['cancelled', 'Cancelled by the customer'],
          ]}
        />
        <StoreFilter list={list} />
      </FilterBar>
      <ListView query={returns} list={list} caption="Returns" columns={columns} rowKey={(ret) => ret.return_number} empty="No returns yet" />
      <ReturnDialog target={target} onClose={() => setTarget(null)} />
    </>
  )
}

// --- Refunds -------------------------------------------------------------------------------------

function PaidDialog({ refund, onClose }: { refund: StaffRefund | null; onClose: () => void }) {
  const act = useRefundAction()
  const toast = useToast()
  const [reference, setReference] = useState('')
  const [seen, setSeen] = useState('')
  if ((refund?.public_id ?? '') !== seen) {
    setSeen(refund?.public_id ?? '')
    setReference('')
    act.reset()
  }
  if (!refund) return null
  return (
    <FormDialog
      open
      title="Refund paid by hand?"
      submitLabel="Record as paid"
      busy={act.isPending}
      error={act.error}
      onClose={onClose}
      onSubmit={() =>
        act.mutate(
          { id: refund.public_id, action: 'mark-processed', reference: reference.trim() },
          {
            onSuccess: () => {
              toast.show(`Refund for order ${refund.order_number} recorded as paid.`)
              onClose()
            },
          },
        )
      }
    >
      <p className="text-sm">
        <strong>{formatPrice(refund.amount)}</strong> to {refund.customer_name} for order {refund.order_number}. Pay the customer
        first (cash, UPI or bank transfer), then record it here. This can’t be undone.
      </p>
      <FormField
        id="refund-reference"
        label="Reference"
        required
        maxLength={100}
        value={reference}
        onChange={(e) => setReference(e.target.value)}
        hint="UPI or bank reference, or the cash receipt number."
      />
    </FormDialog>
  )
}

export function AdminRefundsPage() {
  usePageMeta('Refunds')
  const list = useListParams()
  const refunds = useRefunds({ page: list.page, q: list.get('q'), status: list.get('status'), store: list.get('store') })
  const act = useRefundAction()
  const toast = useToast()
  const [paying, setPaying] = useState<StaffRefund | null>(null)
  const [retrying, setRetrying] = useState<StaffRefund | null>(null)

  const columns: Column<StaffRefund>[] = [
    {
      header: 'Refund',
      cell: (refund) => (
        <>
          <span className="font-semibold">{refund.customer_name || 'Customer'}</span>
          <span className="block">{orderLink(refund.order_number)}</span>
        </>
      ),
    },
    { header: 'Amount', numeric: true, cell: (refund) => <span className="font-bold">{formatPrice(refund.amount)}</span> },
    {
      header: 'How',
      cell: (refund) => (
        <>
          {refund.is_manual ? 'Paid by the store' : `Back to the payment (${refund.payment_provider})`}
          <span className="block text-xs text-ink-600">{refund.reason}</span>
        </>
      ),
    },
    { header: 'Store', cell: (refund) => refund.store_name ?? '—' },
    {
      header: 'Status',
      cell: (refund) => (
        <>
          <StatusBadge status={refund.status} />
          {refund.status === 'failed' && refund.failure_reason && (
            <span className="mt-1 block text-xs text-danger-600">
              {refund.failure_reason} ({refund.attempts} {refund.attempts === 1 ? 'attempt' : 'attempts'})
            </span>
          )}
          {refund.status === 'processed' && (
            <span className="mt-1 block text-xs text-ink-600">
              {dateTime(refund.processed_at)}
              {(refund.manual_reference || refund.provider_refund_id) && ` · ${refund.manual_reference || refund.provider_refund_id}`}
            </span>
          )}
        </>
      ),
    },
    { header: 'Created', cell: (refund) => dateTime(refund.created_at) },
    {
      header: 'Actions',
      cell: (refund) =>
        refund.status === 'processed' ? (
          <span className="text-ink-600">—</span>
        ) : (
          <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
            {refund.status === 'failed' && !refund.is_manual && (
              <button
                type="button"
                className="btn-primary px-2.5 py-1.5"
                onClick={() => {
                  act.reset()
                  setRetrying(refund)
                }}
              >
                Try again{' '}
<span className="sr-only">refund for order {refund.order_number}</span>
              </button>
            )}
            {(refund.is_manual || refund.status === 'failed') && (
              <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => setPaying(refund)}>
                Paid by hand{' '}
<span className="sr-only">refund for order {refund.order_number}</span>
              </button>
            )}
            {!refund.is_manual && refund.status === 'pending' && <Badge>With the payment provider</Badge>}
          </span>
        ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Refunds"
        description="Refunds are created by cancellations and returns, with the amount already calculated. Here you send a failed one again, or record one paid by hand."
      />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by order, customer or reference" />
        <FilterSelect
          list={list}
          name="status"
          label="Status"
          options={[
            ['pending', 'Waiting'],
            ['failed', 'Failed'],
            ['processed', 'Paid'],
          ]}
        />
        <StoreFilter list={list} />
      </FilterBar>
      <ListView query={refunds} list={list} caption="Refunds" columns={columns} rowKey={(refund) => refund.public_id} empty="No refunds yet" />
      <PaidDialog refund={paying} onClose={() => setPaying(null)} />
      <ConfirmDialog
        open={retrying !== null}
        title="Send this refund again?"
        confirmLabel="Try again"
        busy={act.isPending}
        error={act.error}
        onClose={() => setRetrying(null)}
        onConfirm={() => {
          if (!retrying) return
          act.mutate(
            { id: retrying.public_id, action: 'retry' },
            {
              onSuccess: (refund) => {
                toast.show(refund.status === 'failed' ? 'The refund failed again.' : 'Refund sent.', {
                  tone: refund.status === 'failed' ? 'error' : 'success',
                })
                setRetrying(null)
              },
            },
          )
        }}
      >
        <p>
          {formatPrice(retrying?.amount)} goes back to the customer’s original payment for order {retrying?.order_number}.
        </p>
      </ConfirmDialog>
    </>
  )
}
