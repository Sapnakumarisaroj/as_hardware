import { useState } from 'react'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import {
  useCashbackRuleCrud,
  useCashbackRules,
  useCustomers,
  useGivePromoCredit,
  useLoyaltyLedger,
  useLoyaltySettings,
  useReferrals,
  useSaveLoyaltySettings,
} from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { AdminCreditEntry, CashbackRuleRow } from '@/features/admin/types'
import {
  CheckField,
  ConfirmDialog,
  DataTable,
  dateTime,
  errorMessage,
  FormDialog,
  ListView,
  NotAllowed,
  PageHeader,
  Panel,
  SelectField,
  StatusBadge,
  Tabs,
  type Column,
} from '@/features/admin/ui'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

/*
 * Phase 17 loyalty controls (administrators). The server keeps the ledger: this screen changes rules,
 * gives promotional credit (always a ledger entry with a reason, audited) and shows entries. A balance
 * can't be edited — there is no such field anywhere.
 */

const STATE_TEXT: Record<string, string> = { live: 'Running', scheduled: 'Scheduled', expired: 'Ended', inactive: 'Switched off' }

function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}
const fromLocalInput = (value: string): string | null => (value ? new Date(value).toISOString() : null)

function SettingsPanel() {
  const settings = useLoyaltySettings()
  const save = useSaveLoyaltySettings()
  const toast = useToast()
  const [draft, setDraft] = useState<Record<string, string | boolean> | null>(null)
  if (settings.isPending) return <PageSpinner label="Loading loyalty settings…" />
  if (settings.isError) return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} title="Couldn’t load loyalty settings" />
  const data = settings.data
  const value = (key: keyof typeof data) => (draft?.[key] ?? data[key]) as string | boolean
  const set = (key: string, next: string | boolean) => setDraft({ ...(draft ?? {}), [key]: next })
  const share = Number(value('max_order_share'))
  const invalid = !(share >= 0 && share <= 100) || !(Number(value('expiry_days')) >= 1)
  return (
    <Panel title="Credits">
      <form
        noValidate
        className="grid max-w-2xl gap-3 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (invalid || !draft) return
          save.mutate(draft, {
            onSuccess: () => {
              toast.show('Loyalty settings saved.')
              setDraft(null)
            },
            onError: (error) => toast.show(errorMessage(error), { tone: 'error' }),
          })
        }}
      >
        <div className="sm:col-span-2">
          <CheckField
            id="credits-enabled"
            label="Customers can use credits at checkout"
            checked={Boolean(value('credits_enabled'))}
            onChange={(v) => set('credits_enabled', v)}
            hint="Switching off only stops spending; earned credits stay in the ledger."
          />
        </div>
        <FormField
          id="max-share"
          label="Credits pay at most (%)"
          inputMode="decimal"
          value={String(value('max_order_share'))}
          onChange={(e) => set('max_order_share', e.target.value)}
          hint="Of the goods after offers and coupon."
          error={!(share >= 0 && share <= 100) ? 'Between 0 and 100.' : undefined}
        />
        <FormField
          id="expiry-days"
          label="Each credit lasts (days)"
          inputMode="numeric"
          value={String(value('expiry_days'))}
          onChange={(e) => set('expiry_days', e.target.value)}
          hint="Counted from when it becomes usable."
        />
        <FormField
          id="referral-reward"
          label="Referral reward for the referrer (₹)"
          inputMode="decimal"
          value={String(value('referral_reward'))}
          onChange={(e) => set('referral_reward', e.target.value)}
          hint="0 = off. Paid after the friend’s first delivered order and its return window."
        />
        <FormField
          id="referee-reward"
          label="Welcome reward for the new customer (₹)"
          inputMode="decimal"
          value={String(value('referee_reward'))}
          onChange={(e) => set('referee_reward', e.target.value)}
          hint="0 = off."
        />
        <div className="sm:col-span-2">
          <button type="submit" className="btn-primary" disabled={!draft || invalid || save.isPending}>
            Save
          </button>
          <p className="mt-1 text-xs text-ink-600">
            Last changed {dateTime(data.updated_at)}. Orders keep the rules they were placed with.
          </p>
        </div>
      </form>
    </Panel>
  )
}

interface RuleDraft {
  id?: number
  name: string
  description: string
  reward_type: 'percent' | 'fixed'
  percent: string
  fixed_amount: string
  max_amount: string
  min_order_value: string
  first_order_only: boolean
  starts_at: string
  ends_at: string
  is_active: boolean
  priority: string
}

function CashbackRules() {
  const rules = useCashbackRules()
  const { save, remove } = useCashbackRuleCrud()
  const toast = useToast()
  const [draft, setDraft] = useState<RuleDraft | null>(null)
  const [problem, setProblem] = useState('')
  const [deleting, setDeleting] = useState<CashbackRuleRow | null>(null)

  const open = (row: CashbackRuleRow | null) => {
    save.reset()
    setProblem('')
    setDraft({
      id: row?.id,
      name: row?.name ?? '',
      description: row?.description ?? '',
      reward_type: row?.reward_type ?? 'percent',
      percent: row?.percent ?? '',
      fixed_amount: row?.fixed_amount ?? '',
      max_amount: row?.max_amount ?? '',
      min_order_value: row?.min_order_value ?? '0',
      first_order_only: row?.first_order_only ?? false,
      starts_at: toLocalInput(row?.starts_at ?? new Date().toISOString()),
      ends_at: toLocalInput(row?.ends_at),
      is_active: row?.is_active ?? true,
      priority: String(row?.priority ?? 100),
    })
  }
  const columns: Column<CashbackRuleRow>[] = [
    { header: 'Rule', cell: (row) => <span className="font-semibold">{row.name}</span> },
    {
      header: 'Reward',
      cell: (row) =>
        `${row.summary}${Number(row.min_order_value) > 0 ? ` from ${formatPrice(row.min_order_value)}` : ''}${row.max_amount ? `, up to ${formatPrice(row.max_amount)}` : ''}${row.first_order_only ? ' · first order' : ''}`,
    },
    { header: 'Status', cell: (row) => <StatusBadge status={row.state} text={STATE_TEXT[row.state]} /> },
    {
      header: 'Actions',
      cell: (row) => (
        <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => open(row)}>
            Edit <span className="sr-only">{row.name}</span>
          </button>
          <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => setDeleting(row)}>
            Delete <span className="sr-only">{row.name}</span>
          </button>
        </span>
      ),
    },
  ]
  return (
    <Panel
      title="Cashback rules"
      action={
        <button type="button" className="btn-primary px-2.5 py-1.5" onClick={() => open(null)}>
          Add rule
        </button>
      }
    >
      <p className="mb-3 text-xs text-ink-600">
        Cashback is a share (or a fixed amount) of what the customer pays for eligible items. It is pending until the order
        is delivered and its return window has passed, and shrinks or is reversed with returns and cancellations. The
        best single rule applies (lowest priority number).
      </p>
      {rules.isPending ? (
        <p className="text-sm text-ink-600">Loading…</p>
      ) : rules.isError ? (
        <ErrorState error={rules.error} onRetry={() => void rules.refetch()} title="Couldn’t load cashback rules" />
      ) : rules.data.length === 0 ? (
        <p className="py-6 text-center text-sm text-ink-600">No cashback rules. Orders earn no cashback.</p>
      ) : (
        <DataTable caption="Cashback rules" columns={columns} rows={rules.data} rowKey={(row) => row.id} />
      )}

      <FormDialog
        open={draft !== null}
        title={draft?.id ? 'Edit cashback rule' : 'Add cashback rule'}
        busy={save.isPending}
        error={save.error}
        problem={problem}
        onClose={() => setDraft(null)}
        onSubmit={() => {
          if (!draft) return
          const found = !draft.name.trim()
            ? 'Give the rule a name; customers see it with their cashback.'
            : draft.reward_type === 'percent' && !(Number(draft.percent) > 0 && Number(draft.percent) <= 100)
              ? 'Enter a cashback % between 0 and 100.'
              : draft.reward_type === 'fixed' && !(Number(draft.fixed_amount) > 0)
                ? 'Enter the cashback amount.'
                : ''
          setProblem(found)
          if (found) return
          save.mutate(
            {
              id: draft.id,
              data: {
                name: draft.name.trim(),
                description: draft.description.trim(),
                reward_type: draft.reward_type,
                percent: draft.reward_type === 'percent' ? draft.percent : null,
                fixed_amount: draft.reward_type === 'fixed' ? draft.fixed_amount : null,
                max_amount: draft.max_amount.trim() || null,
                min_order_value: draft.min_order_value.trim() || '0',
                products: [],
                categories: [],
                first_order_only: draft.first_order_only,
                starts_at: fromLocalInput(draft.starts_at) ?? new Date().toISOString(),
                ends_at: fromLocalInput(draft.ends_at),
                is_active: draft.is_active,
                priority: Number(draft.priority) || 100,
              },
            },
            {
              onSuccess: () => {
                toast.show('Cashback rule saved.')
                setDraft(null)
              },
            },
          )
        }}
      >
        {draft && (
          <>
            <FormField id="cb-name" label="Name" required maxLength={120} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <SelectField id="cb-type" label="Reward" value={draft.reward_type} onChange={(e) => setDraft({ ...draft, reward_type: e.target.value as 'percent' | 'fixed' })}>
              <option value="percent">% of eligible items</option>
              <option value="fixed">Fixed amount per order</option>
            </SelectField>
            <div className="grid grid-cols-2 gap-3">
              {draft.reward_type === 'percent' ? (
                <FormField id="cb-percent" label="Cashback %" inputMode="decimal" value={draft.percent} onChange={(e) => setDraft({ ...draft, percent: e.target.value })} />
              ) : (
                <FormField id="cb-fixed" label="Cashback (₹)" inputMode="decimal" value={draft.fixed_amount} onChange={(e) => setDraft({ ...draft, fixed_amount: e.target.value })} />
              )}
              <FormField id="cb-max" label="At most (₹)" inputMode="decimal" value={draft.max_amount} onChange={(e) => setDraft({ ...draft, max_amount: e.target.value })} hint="Empty: no cap." />
              <FormField id="cb-min" label="Order from (₹)" inputMode="decimal" value={draft.min_order_value} onChange={(e) => setDraft({ ...draft, min_order_value: e.target.value })} hint="Eligible items after discounts and credits." />
              <FormField id="cb-priority" label="Priority" inputMode="numeric" value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })} hint="Lower wins." />
              <FormField id="cb-start" label="Starts" type="datetime-local" value={draft.starts_at} onChange={(e) => setDraft({ ...draft, starts_at: e.target.value })} />
              <FormField id="cb-end" label="Ends" type="datetime-local" value={draft.ends_at} onChange={(e) => setDraft({ ...draft, ends_at: e.target.value })} hint="Empty: until switched off." />
            </div>
            <CheckField id="cb-first" label="First order only" checked={draft.first_order_only} onChange={(v) => setDraft({ ...draft, first_order_only: v })} />
            <CheckField id="cb-active" label="Switched on" checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} />
          </>
        )}
      </FormDialog>
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.name ?? ''}?`}
        confirmLabel="Delete rule"
        danger
        busy={remove.isPending}
        error={remove.error}
        onClose={() => {
          remove.reset()
          setDeleting(null)
        }}
        onConfirm={() => {
          if (!deleting) return
          remove.mutate(deleting.id, {
            onSuccess: () => {
              toast.show(`${deleting.name} deleted.`)
              setDeleting(null)
            },
          })
        }}
      >
        <p>Cashback already earned stays in the ledger.</p>
      </ConfirmDialog>
    </Panel>
  )
}

function PromoCredit() {
  const [term, setTerm] = useState('')
  const [search, setSearch] = useState('')
  const [customer, setCustomer] = useState<{ id: number; name: string; email: string } | null>(null)
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)
  const customers = useCustomers({ q: search, role: 'customer', page_size: 8 })
  const give = useGivePromoCredit()
  const toast = useToast()
  const ready = customer && Number(amount) >= 1 && reason.trim().length > 0
  return (
    <Panel title="Give promotional credit">
      <p className="mb-3 text-xs text-ink-600">
        Adds a ledger entry with your reason (shown to the customer) and an audit record. Credit expires like any other
        and is never cash.
      </p>
      <div className="grid max-w-2xl gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          {customer ? (
            <p className="text-sm">
              Customer: <span className="font-semibold">{customer.name}</span> ({customer.email}){' '}
              <button type="button" className="font-semibold text-amber-700 hover:underline" onClick={() => setCustomer(null)}>
                Change
              </button>
            </p>
          ) : (
            <>
              <div className="flex items-end gap-2">
                <FormField id="promo-find" label="Customer" className="flex-1" placeholder="Name, email or phone" value={term} onChange={(e) => setTerm(e.target.value)} />
                <button type="button" className="btn-dark" disabled={term.trim().length < 2} onClick={() => setSearch(term.trim())}>
                  Find
                </button>
              </div>
              {search && customers.data && (
                <ul className="mt-2 divide-y divide-steel-100 rounded-md ring-1 ring-steel-200" aria-label="Matching customers">
                  {customers.data.results.length === 0 && <li className="px-3 py-2 text-sm text-ink-600">No customer matches “{search}”.</li>}
                  {customers.data.results.map((row) => (
                    <li key={row.id}>
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-left text-sm hover:bg-steel-50"
                        onClick={() => setCustomer({ id: row.id, name: row.full_name, email: row.email })}
                      >
                        {row.full_name} <span className="text-xs text-ink-600">{row.email}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
        <FormField id="promo-amount" label="Amount (₹)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <FormField id="promo-reason" label="Reason" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} hint="e.g. “Sorry for the late delivery”." />
        <div className="sm:col-span-2">
          <button type="button" className="btn-primary" disabled={!ready || give.isPending} onClick={() => setConfirming(true)}>
            Give credit
          </button>
        </div>
      </div>
      <ConfirmDialog
        open={confirming}
        title="Give promotional credit?"
        confirmLabel={`Give ${formatPrice(amount || '0')}`}
        busy={give.isPending}
        error={give.error}
        onClose={() => {
          give.reset()
          setConfirming(false)
        }}
        onConfirm={() => {
          if (!customer) return
          give.mutate(
            { user: customer.id, amount, reason: reason.trim() },
            {
              onSuccess: () => {
                toast.show(`${formatPrice(amount)} credit given to ${customer.name}.`)
                setConfirming(false)
                setAmount('')
                setReason('')
              },
            },
          )
        }}
      >
        <p>
          {customer?.name} receives {formatPrice(amount || '0')} credit: “{reason.trim()}”.
        </p>
      </ConfirmDialog>
    </Panel>
  )
}

function Ledger() {
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [kind, setKind] = useState('')
  const [page, setPage] = useState(1)
  const ledger = useLoyaltyLedger({ q: term, kind, page })
  const columns: Column<AdminCreditEntry>[] = [
    { header: 'When', cell: (row) => dateTime(row.created_at) },
    { header: 'Customer', cell: (row) => (row.customer ? `${row.customer.name} (${row.customer.email})` : '') },
    { header: 'Type', cell: (row) => row.kind_label },
    { header: 'Status', cell: (row) => row.status_label },
    { header: 'Amount', numeric: true, cell: (row) => <span className={row.amount.startsWith('-') ? '' : 'text-success-600'}>{row.amount.startsWith('-') ? '−' : '+'}{formatPrice(row.amount.replace('-', ''))}</span> },
    { header: 'Reference', cell: (row) => `${row.order_number ?? row.reference}${row.description ? ` · ${row.description}` : ''}` },
    { header: 'Expires', cell: (row) => (row.expires_at ? dateTime(row.expires_at) : '—') },
  ]
  return (
    <Panel title="Ledger">
      <form
        className="mb-3 flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          setTerm(q.trim())
          setPage(1)
        }}
      >
        <FormField id="ledger-q" label="Search" placeholder="Customer, order number or reference" value={q} onChange={(e) => setQ(e.target.value)} />
        <SelectField id="ledger-kind" label="Type" value={kind} onChange={(e) => { setKind(e.target.value); setPage(1) }}>
          <option value="">All</option>
          <option value="cashback">Cashback</option>
          <option value="promo">Promotional credit</option>
          <option value="referral">Referral reward</option>
          <option value="restore">Credits given back</option>
          <option value="redemption">Used on an order</option>
          <option value="expiry">Expired</option>
        </SelectField>
        <button type="submit" className="btn-dark">
          Search
        </button>
      </form>
      <ListView query={ledger} caption="Loyalty ledger" columns={columns} rowKey={(row) => row.id} empty="No ledger entries yet" page={page} onPage={setPage} />
    </Panel>
  )
}

function Referrals() {
  const referrals = useReferrals()
  if (referrals.isPending) return <p className="text-sm text-ink-600">Loading…</p>
  if (referrals.isError) return <ErrorState error={referrals.error} onRetry={() => void referrals.refetch()} title="Couldn’t load referrals" />
  return (
    <Panel title="Referrals">
      {referrals.data.length === 0 ? (
        <p className="py-6 text-center text-sm text-ink-600">No customer has used a referral code yet.</p>
      ) : (
        <DataTable
          caption="Referrals"
          rows={referrals.data}
          rowKey={(row) => row.id}
          columns={[
            { header: 'Referred by', cell: (row) => `${row.referrer.name} (${row.referrer.email})` },
            { header: 'New customer', cell: (row) => `${row.referee.name} (${row.referee.email})` },
            { header: 'Status', cell: (row) => row.status_label },
            { header: 'First order', cell: (row) => row.order_number ?? '—' },
            { header: 'Joined', cell: (row) => dateTime(row.created_at) },
          ]}
        />
      )}
    </Panel>
  )
}

/** /admin/loyalty — credits, cashback rules, promotional credit, ledger and referrals. */
export function AdminLoyaltyPage() {
  usePageMeta('Loyalty')
  const session = useSession()
  const [tab, setTab] = useState('rules')
  if (!session.is_admin) return <NotAllowed what="Loyalty" />
  return (
    <>
      <PageHeader
        title="Loyalty & cashback"
        description="Credits are shop credit, never cash. Every credit and every use is a ledger entry; balances are always added up from the ledger."
      />
      <Tabs
        label="Loyalty sections"
        current={tab}
        onChange={setTab}
        tabs={[
          ['rules', 'Rules'],
          ['promo', 'Promotional credit'],
          ['ledger', 'Ledger'],
          ['referrals', 'Referrals'],
        ]}
      />
      {tab === 'rules' && (
        <div className="space-y-4">
          <SettingsPanel />
          <CashbackRules />
        </div>
      )}
      {tab === 'promo' && <PromoCredit />}
      {tab === 'ledger' && <Ledger />}
      {tab === 'referrals' && <Referrals />}
    </>
  )
}
