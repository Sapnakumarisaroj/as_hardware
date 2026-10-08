import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { EmptyState, ErrorState, PageSpinner, Spinner } from '@/components/feedback'
import { QuantityStepper } from '@/components/QuantityStepper'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { CompatibilityProblems } from '@/features/compatibility/components'
import { usePincode } from '@/features/delivery/location'
import { Breakdown, StockBadge, TotalRow } from '@/features/projects/components'
import type { KitItem, ProjectKit } from '@/features/projects/types'
import { useAddBundleToCart, useBudgetPlan, useBundlePrice, useBundles } from '@/features/shopping/api'
import { BundleCard } from '@/features/shopping/components'
import type { BudgetPlan, BundleOverride } from '@/features/shopping/types'
import { ApiError } from '@/lib/api/errors'
import { formatPrice, pluralize } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function KitTotals({ kit, label = 'Total' }: { kit: ProjectKit; label?: string }) {
  return (
    <dl className="space-y-1 text-sm">
      <TotalRow label={`Items (${kit.totals.item_count})`} value={formatPrice(kit.totals.subtotal)} />
      {Number(kit.totals.bulk_savings) > 0 && <TotalRow label="Bulk prices saved" value={`−${formatPrice(kit.totals.bulk_savings)}`} tone="good" />}
      {kit.offers.map((offer) => (
        <TotalRow key={offer.name} label={offer.name} value={`−${formatPrice(offer.discount)}`} tone="good" />
      ))}
      <TotalRow label="Delivery" value={Number(kit.totals.delivery_fee) > 0 ? formatPrice(kit.totals.delivery_fee) : 'Free'} />
      <div className="flex justify-between border-t border-steel-100 pt-2 text-base font-bold">
        <dt>{label}</dt>
        <dd>{formatPrice(kit.totals.grand_total)}</dd>
      </div>
    </dl>
  )
}

function ItemLine({ item, children }: { item: KitItem; children?: React.ReactNode }) {
  return (
    <li className={`flex gap-3 rounded-md bg-white p-2 ring-1 ${item.included ? 'ring-steel-200' : 'opacity-70 ring-steel-100'}`}>
      {item.product && <ProductImage src={item.product.image} alt={item.product.image_alt || item.product.name} className="size-14 shrink-0 rounded" />}
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-medium">
          {item.product ? (
            <Link to={`/p/${item.product.slug}`} className="hover:text-amber-700">
              {item.product.name}
            </Link>
          ) : (
            item.label
          )}
          {item.variant?.name && <span className="text-ink-600"> · {item.variant.name}</span>}
        </p>
        {item.status === 'not_found' && <p className="text-xs text-ink-600">Not found in our catalogue.</p>}
        {item.rationale && <p className="text-xs text-ink-600">{item.rationale}</p>}
        <Breakdown steps={item.steps ?? []} />
        <div className="mt-1 flex flex-wrap items-center gap-3">
          {children}
          {item.price && (
            <span>
              {item.quantity} × {formatPrice(item.price.unit_price)}
              {item.price.applied_tier && <span className="ml-1 text-xs text-success-600">bulk price</span>}
            </span>
          )}
          <StockBadge item={item} />
          {item.price && <span className="ml-auto font-semibold">{formatPrice(item.price.line_total)}</span>}
        </div>
      </div>
    </li>
  )
}

// --- /budget ------------------------------------------------------------------------------------------------

export function BudgetPage() {
  usePageMeta('Shop within a budget', 'Tell us the job and your budget; we build a cart from real products that stays within it.')
  const pin = usePincode()
  const plan = useBudgetPlan()
  const [text, setText] = useState('')
  const [budget, setBudget] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})

  function run(nextAnswers = answers) {
    plan.mutate({ text: text.trim(), ...(budget.trim() ? { budget: budget.trim() } : {}), answers: nextAnswers, ...(pin ? { postal_code: pin } : {}) })
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!text.trim()) return
    setAnswers({})
    run({})
  }

  const result = plan.data
  return (
    <div className="container-page py-6">
      <h1 className="text-2xl font-extrabold">Shop within a budget</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-600">
        Describe the job and your budget. We work out the materials, pick real products with bulk prices and offers, and keep the cart within
        your budget, telling you what we swapped or left out.
      </p>
      <form onSubmit={onSubmit} className="mt-5 grid max-w-2xl gap-3 rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200 sm:grid-cols-[1fr_10rem]">
        <div>
          <label htmlFor="budget-text" className="label">
            What do you need?
          </label>
          <input
            id="budget-text"
            className="input"
            value={text}
            maxLength={500}
            onChange={(e) => setText(e.target.value)}
            placeholder="Hardware to fix 3 shelves on a brick wall"
          />
        </div>
        <div>
          <label htmlFor="budget-amount" className="label">
            Budget (₹)
          </label>
          <input id="budget-amount" className="input" inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^\d]/g, ''))} />
        </div>
        <button type="submit" className="btn-primary sm:col-span-2 sm:justify-self-start" disabled={!text.trim() || plan.isPending}>
          {plan.isPending ? 'Planning…' : 'Plan my cart'}
        </button>
      </form>
      {plan.isError && (
        <p role="alert" className="mt-4 text-sm text-danger-600">
          {errorMessage(plan.error, 'Could not plan that. Please try again.')}
        </p>
      )}
      {result && (
        <BudgetResult
          plan={result}
          answers={answers}
          onAnswer={(next) => {
            setAnswers(next)
            run(next)
          }}
        />
      )}
    </div>
  )
}

function BudgetResult({ plan, answers, onAnswer }: { plan: BudgetPlan; answers: Record<string, string>; onAnswer: (a: Record<string, string>) => void }) {
  const [values, setValues] = useState<Record<string, string>>(answers)
  const asked = (plan.questions ?? []).filter((q) => plan.missing?.includes(q.key))
  return (
    <section className="mt-6 space-y-4" aria-label="Budget plan">
      {plan.message && (
        <p role="status" className={`max-w-3xl rounded-lg p-3 text-sm ${plan.within_budget === false ? 'bg-amber-50 ring-1 ring-amber-300' : 'bg-white ring-1 ring-steel-200'}`}>
          {plan.message}
        </p>
      )}
      {asked.length > 0 && (
        <form
          className="max-w-3xl rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200"
          aria-label="A few details"
          onSubmit={(e) => {
            e.preventDefault()
            onAnswer({ ...answers, ...values })
          }}
        >
          <h2 className="font-bold">A few details for the right amounts</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {asked.map((q) =>
              q.kind === 'choice' ? (
                <label key={q.key} className="text-sm">
                  <span className="label">{q.text}</span>
                  <select className="input" value={values[q.key] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [q.key]: e.target.value }))}>
                    <option value="">Choose…</option>
                    {q.choices.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <label key={q.key} className="text-sm">
                  <span className="label">
                    {q.text} {q.unit && `(${q.unit})`}
                  </span>
                  <input className="input" inputMode="decimal" value={values[q.key] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [q.key]: e.target.value }))} />
                </label>
              ),
            )}
          </div>
          <button type="submit" className="btn-primary mt-3">
            Continue
          </button>
        </form>
      )}
      {plan.verify && <p className="max-w-3xl text-sm font-semibold">{plan.verify}</p>}
      {plan.kit && (
        <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
          <div className="space-y-3">
            <CompatibilityProblems problems={plan.kit.compatibility ?? []} />
            <ul className="space-y-2" aria-label="Planned items">
              {plan.kit.items
                .filter((i) => i.included)
                .map((item) => (
                  <ItemLine key={item.material_key} item={item} />
                ))}
            </ul>
            {(plan.swapped ?? []).length > 0 && (
              <div className="text-sm">
                <h2 className="font-bold">Swapped to fit the budget</h2>
                <ul className="mt-1 list-disc pl-5" aria-label="Swapped">
                  {plan.swapped!.map((s) => (
                    <li key={s.key}>
                      {s.from} → {s.to}: {s.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(plan.dropped ?? []).length > 0 && (
              <div className="text-sm">
                <h2 className="font-bold">Left out</h2>
                <ul className="mt-1 list-disc pl-5" aria-label="Left out">
                  {plan.dropped!.map((d) => (
                    <li key={d.key}>
                      {d.label}: {d.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(plan.premium_options ?? []).length > 0 && (
              <div className="text-sm">
                <h2 className="font-bold">Upgrade within your budget</h2>
                <ul className="mt-1 list-disc pl-5">
                  {plan.premium_options!.map((p) => (
                    <li key={p.key}>
                      <Link to={`/p/${p.product.slug}`} className="text-amber-700 underline">
                        {p.product.name}
                      </Link>
                      : {p.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <aside className="h-fit space-y-2 rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200" aria-label="Budget total">
            <KitTotals kit={plan.kit} label="Plan total" />
            <p className="text-sm">
              Budget {formatPrice(plan.budget)} · <span className="font-semibold">{formatPrice(plan.remaining)} left</span>
            </p>
            {plan.full_kit_over_budget && <p className="text-xs text-ink-600">The full kit would cost {formatPrice(plan.full_kit_total)}.</p>}
            <p className="text-xs text-ink-600">Prices include GST and come from today’s catalogue; the cart checks them again.</p>
          </aside>
        </div>
      )}
      {(plan.best_for_budget ?? []).length > 0 && (
        <div>
          <h2 className="text-lg font-bold">Within your budget</h2>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2" aria-label="Within your budget">
            {plan.best_for_budget!.map((row) => (
              <li key={row.product_id} className="rounded bg-white p-2 text-sm ring-1 ring-steel-200">
                <Link to={`/p/${row.product.slug}`} className="font-medium hover:text-amber-700">
                  {row.product.name}
                </Link>{' '}
                · {formatPrice(row.product.price)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

// --- /bundles --------------------------------------------------------------------------------------------------

export function BundlesPage() {
  usePageMeta('Kits and bundles', 'Ready-made kits of real products for common jobs, priced with bulk prices and offers.')
  const bundles = useBundles()
  return (
    <div className="container-page py-6">
      <h1 className="text-2xl font-extrabold">Kits and bundles</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-600">Everything for a common job in one go. Prices, offers and stock are checked live; change any item before adding.</p>
      {bundles.isLoading && <PageSpinner />}
      {bundles.isError && <ErrorState error={bundles.error} onRetry={() => void bundles.refetch()} />}
      {bundles.data && bundles.data.length === 0 && <EmptyState title="No kits right now" />}
      {bundles.data && bundles.data.length > 0 && (
        <ul className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {bundles.data.map((bundle) => (
            <BundleCard key={bundle.id} bundle={bundle} />
          ))}
        </ul>
      )}
    </div>
  )
}

export function BundlePage() {
  const { slug = '' } = useParams()
  const pin = usePincode()
  const navigate = useNavigate()
  const toast = useToast()
  const { status } = useAuth()
  const [overrides, setOverrides] = useState<Record<string, BundleOverride>>({})
  const bundle = useBundlePrice(slug, overrides, pin)
  const add = useAddBundleToCart()
  usePageMeta(bundle.data?.name ?? 'Kit')
  const change = (id: number | string, value: BundleOverride) => setOverrides((o) => ({ ...o, [String(id)]: { ...o[String(id)], ...value } }))

  if (bundle.isLoading) return <PageSpinner />
  if (bundle.isError || !bundle.data) {
    return (
      <div className="container-page py-6">
        <ErrorState error={bundle.error} title="Kit not found" />
      </div>
    )
  }
  const data = bundle.data
  function addAll() {
    if (status !== 'authenticated') {
      void navigate(`/login?next=${encodeURIComponent(`/bundles/${slug}`)}`)
      return
    }
    add.mutate({ slug, overrides }, { onSuccess: (r) => toast.show(`Added ${pluralize(r.added_lines, 'item')} to your cart.`, { action: { label: 'View cart', to: '/cart' } }) })
  }
  return (
    <div className="container-page py-6">
      <Link to="/bundles" className="text-sm text-ink-600 hover:text-amber-700">
        ← All kits
      </Link>
      <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-amber-700">{data.kind_label}</p>
      <h1 className="text-2xl font-extrabold">{data.name}</h1>
      <p className="mt-1 text-sm text-ink-700">{data.description}</p>
      <div className="mt-5 grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-3">
          <CompatibilityProblems problems={data.kit.compatibility ?? []} />
          {bundle.isFetching && <Spinner label="Updating prices…" />}
          <ul className="space-y-2" aria-label="Kit items">
            {data.kit.items.map((item) => (
              <ItemLine key={item.id} item={item}>
                <input
                  type="checkbox"
                  className="size-5 accent-amber-500"
                  checked={item.included}
                  aria-label={`Include ${item.label}`}
                  onChange={(e) => change(item.id, { included: e.target.checked })}
                />
                <QuantityStepper value={item.quantity} max={999} label={`Quantity of ${item.label}`} size="sm" onChange={(quantity) => change(item.id, { quantity })} />
                {item.is_optional && <span className="rounded bg-steel-100 px-1.5 text-xs">Optional</span>}
              </ItemLine>
            ))}
          </ul>
        </div>
        <aside className="h-fit space-y-3 rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200" aria-label="Kit total">
          <KitTotals kit={data.kit} label="Kit total" />
          {Number(data.savings.vs_mrp) > 0 && <p className="text-sm text-success-600">You save {formatPrice(data.savings.vs_mrp)} against MRP.</p>}
          <p className={`text-sm ${data.kit.delivery.available ? 'text-ink-800' : 'text-ink-600'}`}>
            {data.kit.delivery.checked ? data.kit.delivery.message : 'Enter your PIN on the cart page to check delivery.'}
          </p>
          {data.kit.issues.length > 0 && (
            <ul className="space-y-1 text-xs text-danger-600" aria-label="Problems">
              {data.kit.issues.map((issue) => (
                <li key={`${issue.code}-${issue.item_id ?? 'kit'}`}>{issue.message}</li>
              ))}
            </ul>
          )}
          {add.isError && (
            <p role="alert" className="text-xs text-danger-600">
              {errorMessage(add.error, 'Could not add the kit.')}
            </p>
          )}
          <button type="button" className="btn-primary w-full" disabled={!data.kit.can_add_to_cart || add.isPending} onClick={addAll}>
            {add.isPending ? 'Adding…' : `Add ${pluralize(data.kit.included_count, 'item')} to cart`}
          </button>
        </aside>
      </div>
    </div>
  )
}
