import { Link, useParams, useSearchParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { Pagination } from '@/components/Pagination'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import {
  QUOTES_PAGE_SIZE,
  quoteErrorMessage as message,
  useAcceptQuote,
  useCloseQuote,
  useQuote,
  useQuotes,
  type Quote,
} from '@/features/quotes/api'
import { QuoteStatusBadge } from '@/features/quotes/components'
import { isNotFound } from '@/lib/api/errors'
import { formatDate, formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

function Gate({ message: text, next }: { message: string; next: string }) {
  const { status } = useAuth()
  if (status === 'loading') return <PageSpinner />
  return (
    <div className="container-page py-10">
      <SignInPrompt message={text} next={next} />
    </div>
  )
}

export function QuotesPage() {
  usePageMeta('Your quotes')
  const { status } = useAuth()
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page')) || 1)
  const quotes = useQuotes(page)
  if (status !== 'authenticated') return <Gate message="Sign in to see your quotes." next="/account/quotes" />

  let body
  if (quotes.isPending) body = <PageSpinner label="Loading quotes…" />
  else if (quotes.isError) body = <ErrorState error={quotes.error} onRetry={() => quotes.refetch()} title="Couldn’t load your quotes" />
  else if (!quotes.data.results.length)
    body = (
      <EmptyState
        title="No quote requests yet"
        action={
          <Link to="/cart" className="btn-primary">
            Go to your cart
          </Link>
        }
      >
        Buying in bulk for a project? Add the items to your cart and choose “Request a bulk quote”.
      </EmptyState>
    )
  else
    body = (
      <>
        <ul className="space-y-3" aria-busy={quotes.isFetching}>
          {quotes.data.results.map((quote) => (
            <li key={quote.id}>
              <Link
                to={`/account/quotes/${quote.id}`}
                className="block rounded-2xl bg-white p-4 text-sm shadow-(--shadow-card) ring-1 ring-steel-200 hover:ring-amber-500"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-semibold">{quote.number}</p>
                  <QuoteStatusBadge quote={quote} />
                </div>
                <p className="truncate text-ink-800">{quote.items.map((i) => i.product_name).join(', ')}</p>
                <p className="text-ink-600">
                  {formatDate(quote.created_at)} · {quote.items.length} {quote.items.length === 1 ? 'item' : 'items'}
                  {quote.quoted_goods_total && (
                    <>
                      {' '}
                      · Quoted <span className="font-semibold text-ink-900">{formatPrice(quote.quoted_goods_total)}</span>
                    </>
                  )}
                </p>
              </Link>
            </li>
          ))}
        </ul>
        <Pagination
          page={page}
          pageSize={QUOTES_PAGE_SIZE}
          total={quotes.data.count}
          onChange={(p) => setParams(p > 1 ? { page: String(p) } : {})}
        />
      </>
    )

  return (
    <div className="container-page max-w-3xl py-8">
      <Breadcrumbs items={[{ label: 'Account', to: '/account' }, { label: 'Quotes' }]} />
      <h1 className="mb-4 mt-2 text-2xl font-bold">Your quotes</h1>
      {body}
    </div>
  )
}

function QuoteActions({ quote }: { quote: Quote }) {
  const accept = useAcceptQuote(quote.id)
  const close = useCloseQuote(quote.id)
  const toast = useToast()
  const error = accept.error ?? close.error
  const closeLabel = quote.status === 'requested' ? 'Cancel request' : 'Decline quotation'

  return (
    <div className="space-y-2">
      {quote.can_checkout && (
        <Link to={`/checkout?quote=${quote.id}`} className="btn-primary block w-full text-center">
          Check out this quotation
        </Link>
      )}
      {quote.can_accept && (
        <button
          type="button"
          disabled={accept.isPending}
          onClick={() => accept.mutate(undefined, { onSuccess: () => toast.show('Quotation accepted') })}
          className="btn-primary w-full"
        >
          {accept.isPending ? 'Accepting…' : 'Accept quotation'}
        </button>
      )}
      {quote.can_close && (
        <button
          type="button"
          disabled={close.isPending}
          onClick={() => {
            if (window.confirm(`${closeLabel} ${quote.number}?`)) close.mutate('')
          }}
          className="btn-secondary w-full"
        >
          {closeLabel}
        </button>
      )}
      {error && (
        <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600">
          {message(error, 'That didn’t work. Please try again.')}
        </p>
      )}
    </div>
  )
}

function StatusNote({ quote }: { quote: Quote }) {
  const box = 'rounded-lg p-4 text-sm'
  switch (quote.status) {
    case 'requested':
      return <p className={`${box} bg-steel-100`}>The shop is preparing your quotation. We’ll notify you when it’s ready.</p>
    case 'quoted':
      return (
        <p className={`${box} bg-amber-100`}>
          Your quotation is ready{quote.valid_until && <> and valid until {formatDate(quote.valid_until)}</>}. Accept it to
          order at these prices.
        </p>
      )
    case 'accepted':
      return (
        <p className={`${box} bg-success-600/10`}>
          Accepted. Check out before {quote.valid_until ? formatDate(quote.valid_until) : 'it expires'}; stock and delivery
          are checked at checkout.
        </p>
      )
    case 'ordered':
      return (
        <p className={`${box} bg-success-600/10`}>
          Ordered as{' '}
          <Link to={`/account/orders/${quote.order_number}`} className="font-semibold underline">
            {quote.order_number}
          </Link>
          .
        </p>
      )
    default:
      return (
        <p className={`${box} bg-steel-100`}>
          {quote.status_label}
          {quote.closed_reason && ` — ${quote.closed_reason}`}
        </p>
      )
  }
}

export function QuotePage() {
  const { id = '' } = useParams()
  const { status } = useAuth()
  const query = useQuote(id)
  usePageMeta(query.data ? `Quote ${query.data.number}` : 'Quote')
  if (status !== 'authenticated') return <Gate message="Sign in to see this quote." next={`/account/quotes/${id}`} />
  if (query.isPending) return <PageSpinner label="Loading quote…" />
  if (query.isError) {
    if (isNotFound(query.error)) return <NotFoundPage />
    return (
      <div className="container-page py-10">
        <ErrorState error={query.error} onRetry={() => query.refetch()} title="Couldn’t load this quote" />
      </div>
    )
  }
  const quote = query.data
  const priced = quote.quoted_goods_total !== null

  return (
    <div className="container-page max-w-5xl py-6">
      <Breadcrumbs items={[{ label: 'Account', to: '/account' }, { label: 'Quotes', to: '/account/quotes' }, { label: quote.number }]} />
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Quote {quote.number}</h1>
          <p className="text-sm text-ink-600">Requested on {formatDate(quote.created_at)}</p>
        </div>
        <QuoteStatusBadge quote={quote} />
      </div>
      <div className="mt-4">
        <StatusNote quote={quote} />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_20rem]">
        <section aria-labelledby="quote-items" className="rounded-2xl bg-white p-5 shadow-(--shadow-card) ring-1 ring-steel-200">
          <h2 id="quote-items" className="mb-2 text-base font-bold">
            Items
          </h2>
          <ul className="divide-y divide-steel-100 text-sm">
            {quote.items.map((item) => (
              <li key={item.id} className="flex flex-wrap items-start justify-between gap-2 py-3">
                <div className="min-w-0 flex-1">
                  <Link to={`/p/${item.product_slug}`} className="font-medium hover:underline">
                    {item.product_name}
                  </Link>
                  <p className="text-xs text-ink-600">
                    {item.variant_name && `${item.variant_name} · `}
                    {item.sku} · Qty {item.quantity}
                  </p>
                  {item.customer_note && <p className="text-xs text-ink-600">Your note: {item.customer_note}</p>}
                </div>
                <div className="text-right">
                  {item.quoted_unit_price ? (
                    <>
                      <p className="font-semibold">{formatPrice(item.quoted_line_total)}</p>
                      <p className="text-xs text-ink-600">
                        {formatPrice(item.quoted_unit_price)} each
                        {item.quoted_unit_price !== item.list_unit_price && (
                          <span className="ml-1 line-through">{formatPrice(item.list_unit_price)}</span>
                        )}
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-ink-600">List price {formatPrice(item.list_unit_price)} each</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>

        <div className="space-y-5">
          <section className="rounded-2xl bg-white p-5 text-sm shadow-(--shadow-card) ring-1 ring-steel-200">
            <dl className="space-y-1">
              <div className="flex justify-between gap-4">
                <dt>List price</dt>
                <dd className={priced ? 'text-ink-600 line-through' : 'font-semibold'}>{formatPrice(quote.list_goods_total)}</dd>
              </div>
              {priced && (
                <div className="flex justify-between gap-4 text-base font-bold">
                  <dt>Quoted price</dt>
                  <dd>{formatPrice(quote.quoted_goods_total)}</dd>
                </div>
              )}
            </dl>
            <p className="mt-2 text-xs text-ink-600">
              Prices include GST. Delivery charges and any store credit are worked out at checkout.
            </p>
            {quote.shop_note && <p className="mt-3 rounded-md bg-steel-50 p-3">From the shop: {quote.shop_note}</p>}
            {quote.customer_note && <p className="mt-2 text-xs text-ink-600">Your note: {quote.customer_note}</p>}
            {(quote.business_name || quote.gstin) && (
              <p className="mt-2 text-xs text-ink-600">
                For {quote.business_name}
                {quote.gstin && ` · GSTIN ${quote.gstin}`}
              </p>
            )}
          </section>
          <QuoteActions quote={quote} />
        </div>
      </div>
    </div>
  )
}
