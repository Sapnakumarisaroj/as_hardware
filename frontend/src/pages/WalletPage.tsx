import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { Pagination } from '@/components/Pagination'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { useClaimReferral, useLedger, useWallet, type CreditEntry, type Wallet } from '@/features/loyalty/api'
import { ApiError } from '@/lib/api/errors'
import { formatDate, formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const FILTERS: { label: string; params: Record<string, string> }[] = [
  { label: 'All', params: {} },
  { label: 'Cashback', params: { kind: 'cashback' } },
  { label: 'Used', params: { kind: 'redemption' } },
  { label: 'Given back', params: { kind: 'restore' } },
  { label: 'Pending', params: { status: 'pending' } },
  { label: 'Waiting for return window', params: { status: 'eligible' } },
  { label: 'Expired', params: { kind: 'expiry' } },
  { label: 'Reversed', params: { status: 'reversed' } },
]
const PAGE_SIZE = 20

function Stat({ label, value, hint, tone = 'default' }: { label: string; value: string; hint?: string; tone?: 'default' | 'good' | 'muted' }) {
  const color = tone === 'good' ? 'text-success-600' : tone === 'muted' ? 'text-ink-600' : 'text-ink-950'
  return (
    <div className="rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200">
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-600">{label}</dt>
      <dd className={`mt-1 text-xl font-bold ${color}`}>{formatPrice(value)}</dd>
      {hint && <p className="mt-0.5 text-xs text-ink-600">{hint}</p>}
    </div>
  )
}

function statusText(entry: CreditEntry): string {
  if (entry.status === 'pending') return 'Pending: becomes usable after delivery and the return window'
  if (entry.status === 'eligible')
    return entry.available_at ? `Usable from ${formatDate(entry.available_at)}` : 'Waiting for the return window'
  if (entry.status === 'available' && entry.expires_at) {
    const left = entry.remaining && entry.remaining !== entry.amount ? ` · ${formatPrice(entry.remaining)} left` : ''
    return `Expires ${formatDate(entry.expires_at)}${left}`
  }
  if (entry.status === 'reversed') return 'Reversed (order cancelled or items returned)'
  if (entry.status === 'expired') return 'Expired'
  return ''
}

function History() {
  const [filter, setFilter] = useState(0)
  const [page, setPage] = useState(1)
  const params = { ...FILTERS[filter]!.params, page: String(page), page_size: String(PAGE_SIZE) }
  const ledger = useLedger(params)
  return (
    <section aria-labelledby="history-heading" className="mt-8">
      <h2 id="history-heading" className="text-lg font-bold">
        History
      </h2>
      <div className="scrollbar-none -mx-4 mt-2 flex gap-2 overflow-x-auto px-4" role="group" aria-label="Show">
        {FILTERS.map((option, index) => (
          <button
            key={option.label}
            type="button"
            aria-pressed={filter === index}
            onClick={() => {
              setFilter(index)
              setPage(1)
            }}
            className={`whitespace-nowrap rounded-full px-3 py-1.5 text-sm ring-1 ${filter === index ? 'bg-ink-900 text-white ring-ink-900' : 'bg-white ring-steel-200 hover:ring-amber-500'}`}
          >
            {option.label}
          </button>
        ))}
      </div>
      {ledger.isPending ? (
        <p className="mt-4 text-sm text-ink-600">Loading…</p>
      ) : ledger.isError ? (
        <ErrorState error={ledger.error} onRetry={() => ledger.refetch()} title="Couldn’t load your credit history" />
      ) : ledger.data.results.length === 0 ? (
        <p className="mt-4 text-sm text-ink-600">Nothing here yet.</p>
      ) : (
        <>
          <ul className="mt-3 divide-y divide-steel-100 rounded-2xl bg-white shadow-(--shadow-card) ring-1 ring-steel-200" aria-label="Credit history">
            {ledger.data.results.map((entry) => {
              const credit = !entry.amount.startsWith('-')
              return (
                <li key={entry.id} className="flex items-start justify-between gap-4 p-4" data-testid="ledger-row">
                  <div className="min-w-0 text-sm">
                    <p className="font-semibold text-ink-950">{entry.kind_label}</p>
                    {entry.description && <p className="text-ink-800">{entry.description}</p>}
                    <p className="text-xs text-ink-600">
                      {formatDate(entry.created_at)}
                      {entry.order_number && (
                        <>
                          {' · '}
                          <Link to={`/account/orders/${entry.order_number}`} className="font-semibold text-amber-700 hover:underline">
                            Order {entry.order_number}
                          </Link>
                        </>
                      )}
                    </p>
                    {statusText(entry) && <p className="text-xs text-ink-600">{statusText(entry)}</p>}
                  </div>
                  <p
                    className={`shrink-0 text-sm font-bold ${entry.status === 'reversed' ? 'text-ink-600 line-through' : credit ? 'text-success-600' : 'text-ink-900'}`}
                  >
                    {credit ? '+' : '−'}
                    {formatPrice(entry.amount.replace('-', ''))}
                  </p>
                </li>
              )
            })}
          </ul>
          <Pagination page={page} pageSize={PAGE_SIZE} total={ledger.data.count} onChange={setPage} />
        </>
      )}
    </section>
  )
}

function Referral({ wallet }: { wallet: Wallet }) {
  const [code, setCode] = useState('')
  const claim = useClaimReferral()
  const toast = useToast()
  const { referral, rules } = wallet
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!code.trim()) return
    claim.mutate(code.trim(), {
      onSuccess: () => {
        setCode('')
        toast.show('Referral code saved.')
      },
    })
  }
  return (
    <section aria-labelledby="referral-heading" className="mt-8 rounded-2xl bg-white shadow-(--shadow-card) p-5 ring-1 ring-steel-200">
      <h2 id="referral-heading" className="text-lg font-bold">
        Invite friends
      </h2>
      <p className="mt-1 text-sm text-ink-800">
        Your code: <span className="rounded bg-steel-100 px-2 py-0.5 font-mono font-bold tracking-wider">{referral.code}</span>
      </p>
      <p className="mt-1 text-xs text-ink-600">
        {referral.rewards_on
          ? `When a friend who used your code gets their first order delivered and its return window passes, you receive ${formatPrice(rules.referral_reward)} in credit${Number(rules.referee_reward) > 0 ? ` and they receive ${formatPrice(rules.referee_reward)}` : ''}.`
          : 'Referral rewards are not running at the moment. Friends can still use your code.'}
      </p>
      {referral.joined > 0 && (
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm" aria-label="Your referrals" data-testid="referral-summary">
          <div>
            <dt className="inline text-ink-600">Friends joined: </dt>
            <dd className="inline font-semibold">{referral.joined}</dd>
          </div>
          {referral.waiting > 0 && (
            <div>
              <dt className="inline text-ink-600">Waiting for their first delivery: </dt>
              <dd className="inline font-semibold">{referral.waiting}</dd>
            </div>
          )}
          <div>
            <dt className="inline text-ink-600">Earned you a reward: </dt>
            <dd className="inline font-semibold">{referral.rewarded}</dd>
          </div>
          {Number(referral.credited) > 0 && (
            <div>
              <dt className="inline text-ink-600">Referral credit received: </dt>
              <dd className="inline font-semibold text-success-600">{formatPrice(referral.credited)}</dd>
            </div>
          )}
          {Number(referral.pending) > 0 && (
            <div>
              <dt className="inline text-ink-600">Waiting for the return window: </dt>
              <dd className="inline font-semibold">{formatPrice(referral.pending)}</dd>
            </div>
          )}
        </dl>
      )}
      {!referral.used_code && (
        <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-2" noValidate>
          <div>
            <label htmlFor="referral-code" className="label">
              Joined with a friend’s code?
            </label>
            <input
              id="referral-code"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              maxLength={12}
              className="input w-40 font-mono uppercase"
              autoComplete="off"
            />
          </div>
          <button type="submit" className="btn-secondary" disabled={claim.isPending}>
            Save code
          </button>
          {claim.isError && (
            <p role="alert" className="w-full text-sm text-danger-600">
              {claim.error instanceof ApiError ? claim.error.message : 'Couldn’t save the code.'}
            </p>
          )}
          <p className="w-full text-xs text-ink-600">Only before your first order.</p>
        </form>
      )}
    </section>
  )
}

function welcomeText(welcome: NonNullable<Wallet['welcome']>): string {
  const amount = formatPrice(welcome.amount)
  if (welcome.status === 'offer') return `Get ${amount} credit when your first order is delivered (usable once its return window passes).`
  if (welcome.status === 'eligible')
    return welcome.available_at ? `Your ${amount} welcome reward is usable from ${formatDate(welcome.available_at)}.` : `Your ${amount} welcome reward is waiting for the return window.`
  if (welcome.status === 'available') return `Your ${amount} welcome reward has been credited.`
  if (welcome.status === 'reversed') return `Your ${amount} welcome reward was reversed because the order was returned.`
  if (welcome.status === 'expired') return `Your ${amount} welcome reward has expired.`
  return `Welcome reward: ${amount} (${welcome.status_label}).`
}

/** /account/wallet — balance, pending cashback, totals and history, all from the server's ledger. */
export function WalletPage() {
  usePageMeta('Wallet')
  const { status } = useAuth()
  const wallet = useWallet()
  if (status === 'loading') return <PageSpinner />
  if (status !== 'authenticated') {
    return (
      <div className="container-page py-10">
        <SignInPrompt message="Sign in to see your credits and cashback." next="/account/wallet" />
      </div>
    )
  }
  if (wallet.isPending) return <PageSpinner label="Loading your wallet…" />
  if (wallet.isError) {
    return (
      <div className="container-page py-10">
        <ErrorState error={wallet.error} onRetry={() => wallet.refetch()} title="Couldn’t load your wallet" />
      </div>
    )
  }
  const data = wallet.data
  const waiting = (Number(data.pending) + Number(data.eligible)).toFixed(2)
  const empty = [data.balance, data.pending, data.eligible, data.earned, data.used].every((v) => Number(v) === 0)
  return (
    <div className="container-page max-w-4xl py-6">
      <Breadcrumbs items={[{ label: 'My account', to: '/account' }, { label: 'Wallet' }]} />
      <h1 className="mt-3 text-2xl font-bold">Wallet</h1>

      <div className="mt-4 rounded-lg bg-ink-900 p-5 text-white">
        <p className="text-sm text-steel-200">Credit you can use</p>
        <p className="text-3xl font-extrabold" data-testid="wallet-balance">
          {formatPrice(data.balance)}
        </p>
        {Number(data.expiring_soon.amount) > 0 && data.expiring_soon.first_expiry && (
          <p className="mt-1 text-sm text-amber-500" role="note">
            {formatPrice(data.expiring_soon.amount)} expires within {data.expiring_soon.within_days} days (first on{' '}
            {formatDate(data.expiring_soon.first_expiry)}).
          </p>
        )}
        <p className="mt-2 text-xs text-steel-200">
          {data.rules.enabled
            ? `Pays up to ${Number(data.rules.max_order_share)}% of an order at checkout · each credit lasts ${data.rules.expiry_days} days · not cash, can’t be withdrawn.`
            : 'Using credits at checkout is paused at the moment.'}
        </p>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Pending cashback" value={waiting} hint="Usable after delivery and the return window" />
        <Stat label="Earned" value={data.earned} tone="good" hint="Cashback, rewards and promotional credit" />
        <Stat label="Used" value={data.used} hint="Paid on orders" />
        <Stat label="Given back" value={data.restored} hint="From cancelled or returned items" />
        <Stat label="Expired" value={data.expired} tone="muted" />
        <Stat label="Reversed" value={data.reversed} tone="muted" hint="Cashback of cancelled or returned orders" />
      </dl>

      {data.welcome && (
        <p className="mt-4 rounded-2xl bg-amber-50 p-4 text-sm text-ink-900 ring-1 ring-amber-100" data-testid="welcome-reward">
          {welcomeText(data.welcome)}
        </p>
      )}

      {empty ? (
        <div className="mt-8">
          <EmptyState title="No credits yet" action={<Link to="/products" className="btn-primary">Start shopping</Link>}>
            Cashback from eligible orders, rewards and promotional credit will appear here.
          </EmptyState>
        </div>
      ) : (
        <History />
      )}
      <Referral wallet={data} />
    </div>
  )
}
