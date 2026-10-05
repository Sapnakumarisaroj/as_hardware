import { useState } from 'react'

import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import { useCategories, useCouponCrud, useCoupons, useOfferCrud, useOffers, useProducts } from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { Coupon, DiscountRule, Offer, RuleInput } from '@/features/admin/types'
import {
  Badge,
  CheckField,
  ConfirmDialog,
  dateTime,
  errorMessage,
  FilterBar,
  FilterSelect,
  FormDialog,
  ListView,
  NotAllowed,
  PageHeader,
  SearchBox,
  SelectField,
  StatusBadge,
  useListParams,
  type Column,
  type ListParams,
} from '@/features/admin/ui'
import { usePageMeta } from '@/lib/usePageMeta'

type Kind = 'offer' | 'coupon'
type Rule = Offer | Coupon

const STATES: [string, string][] = [
  ['live', 'Running'],
  ['scheduled', 'Scheduled'],
  ['expired', 'Ended'],
  ['inactive', 'Switched off'],
]
const STATE_TEXT: Record<string, string> = Object.fromEntries(STATES)

interface Draft {
  id?: number
  name: string
  code: string
  description: string
  discount_type: 'percent' | 'fixed'
  value: string
  max_discount_amount: string
  min_order_value: string
  starts_at: string
  ends_at: string
  is_active: boolean
  priority: string
  usage_limit: string
  per_customer_limit: string
  show_in_checkout: boolean
  categories: number[]
  products: { id: number; name: string; sku: string }[]
  // Offers only (Phase 15)
  benefit: 'discount' | 'free_delivery'
  min_quantity: string
  first_orders: string
  campaign: string
  offer_usage_limit: string
  offer_per_customer: string
}

/** ISO instant ↔ the value of <input type="datetime-local"> in the viewer's time zone. */
function toLocalInput(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}
const fromLocalInput = (value: string): string | null => (value ? new Date(value).toISOString() : null)

function toDraft(rule: Rule | null): Draft {
  const offer = rule as Offer | null
  const coupon = rule as Coupon | null
  return {
    id: rule?.id,
    name: offer?.name ?? '',
    code: coupon?.code ?? '',
    description: rule?.description ?? '',
    discount_type: rule?.discount_type ?? 'percent',
    value: rule?.value ?? '',
    max_discount_amount: rule?.max_discount_amount ?? '',
    min_order_value: rule && Number(rule.min_order_value) > 0 ? rule.min_order_value : '',
    starts_at: toLocalInput(rule?.starts_at ?? new Date().toISOString()),
    ends_at: toLocalInput(rule?.ends_at ?? null),
    is_active: rule?.is_active ?? true,
    priority: String(offer?.priority ?? 100),
    usage_limit: coupon?.usage_limit ? String(coupon.usage_limit) : '',
    per_customer_limit: String(coupon?.per_customer_limit ?? 1),
    show_in_checkout: coupon?.show_in_checkout ?? false,
    categories: rule?.categories ?? [],
    products: rule?.product_details ?? [],
    benefit: offer?.benefit ?? 'discount',
    min_quantity: offer?.min_quantity ? String(offer.min_quantity) : '',
    first_orders:
      offer?.max_prior_orders !== null && offer?.max_prior_orders !== undefined ? String(offer.max_prior_orders + 1) : '',
    campaign: offer?.campaign ?? '',
    offer_usage_limit: offer?.usage_limit ? String(offer.usage_limit) : '',
    offer_per_customer: offer?.per_customer_limit ? String(offer.per_customer_limit) : '',
  }
}

/** The rule as the customer-facing engine stores it. Discounts themselves are calculated by the server. */
function toInput(draft: Draft, kind: Kind): RuleInput {
  const shared: RuleInput = {
    description: draft.description.trim(),
    discount_type: draft.discount_type,
    value: draft.value,
    max_discount_amount: draft.discount_type === 'percent' && draft.max_discount_amount ? draft.max_discount_amount : null,
    min_order_value: draft.min_order_value || '0',
    starts_at: fromLocalInput(draft.starts_at) ?? new Date().toISOString(),
    ends_at: fromLocalInput(draft.ends_at),
    is_active: draft.is_active,
    categories: draft.categories,
    products: draft.products.map((product) => product.id),
  }
  if (kind === 'offer') {
    const freeDelivery = draft.benefit === 'free_delivery'
    return {
      ...shared,
      ...(freeDelivery ? { discount_type: 'fixed', value: '0', max_discount_amount: null } : {}),
      name: draft.name.trim(),
      priority: Number(draft.priority) || 100,
      benefit: draft.benefit,
      min_quantity: Number(draft.min_quantity) || 0,
      // "First N orders" → at most N−1 earlier orders.
      max_prior_orders: draft.first_orders ? Math.max(Number(draft.first_orders) - 1, 0) : null,
      campaign: draft.campaign.trim(),
      usage_limit: draft.offer_usage_limit ? Number(draft.offer_usage_limit) : null,
      per_customer_limit: draft.offer_per_customer ? Number(draft.offer_per_customer) : null,
    }
  }
  return {
    ...shared,
    code: draft.code.trim().toUpperCase(),
    usage_limit: draft.usage_limit ? Number(draft.usage_limit) : null,
    per_customer_limit: Number(draft.per_customer_limit) || 1,
    show_in_checkout: draft.show_in_checkout,
  }
}

function problem(draft: Draft, kind: Kind): string {
  if (kind === 'offer' && !draft.name.trim()) return 'Give the offer a name; customers see it.'
  if (kind === 'coupon' && !/^[A-Za-z0-9_-]+$/.test(draft.code.trim())) return 'The code may contain letters, digits, “-” and “_”.'
  if (draft.starts_at && draft.ends_at && draft.ends_at <= draft.starts_at) return 'The end must be after the start.'
  if (kind === 'offer' && draft.benefit === 'free_delivery') return ''
  const value = Number(draft.value)
  if (!(value > 0)) return 'Enter the discount.'
  if (draft.discount_type === 'percent' && value > 100) return 'A percentage can’t be more than 100.'
  return ''
}

function Targets({ draft, change }: { draft: Draft; change: (changes: Partial<Draft>) => void }) {
  const categories = useCategories(true)
  const [term, setTerm] = useState('')
  const [search, setSearch] = useState('')
  const found = useProducts({ q: search, page_size: 8, state: 'live' }, search.length >= 2)
  const everything = draft.categories.length === 0 && draft.products.length === 0

  return (
    <fieldset className="rounded-md p-3 ring-1 ring-steel-200">
      <legend className="px-1 text-sm font-medium">Applies to</legend>
      <p className="mb-2 text-xs text-ink-600">
        {everything ? 'The whole cart. Choose categories or products to limit it.' : 'Only the chosen categories and products.'}
      </p>
      <SelectField
        id="rule-category"
        label="Add a category"
        value=""
        onChange={(e) => {
          const id = Number(e.target.value)
          if (id && !draft.categories.includes(id)) change({ categories: [...draft.categories, id] })
        }}
      >
        <option value="">Choose…</option>
        {(categories.data ?? []).map((category) => (
          <option key={category.id} value={category.id}>
            {category.parent_name ? `${category.parent_name} › ${category.name}` : category.name}
          </option>
        ))}
      </SelectField>
      <div className="mt-2 flex items-end gap-2">
        <FormField id="rule-product" label="Add a product" className="flex-1" placeholder="Name or SKU" value={term} onChange={(e) => setTerm(e.target.value)} />
        <button type="button" className="btn-dark" disabled={term.trim().length < 2} onClick={() => setSearch(term.trim())}>
          Find
        </button>
      </div>
      {search && found.data && (
        <ul className="mt-2 max-h-40 divide-y divide-steel-100 overflow-y-auto rounded-md ring-1 ring-steel-200">
          {found.data.results.length === 0 && <li className="px-3 py-2 text-sm text-ink-600">No product matches “{search}”.</li>}
          {found.data.results.map((product) => (
            <li key={product.id}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left text-sm hover:bg-steel-50 disabled:text-steel-400"
                disabled={draft.products.some((p) => p.id === product.id)}
                onClick={() => change({ products: [...draft.products, { id: product.id, name: product.name, sku: product.sku }] })}
              >
                {product.name} <span className="text-xs text-ink-600">SKU {product.sku}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {!everything && (
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {draft.categories.map((id) => {
            const category = categories.data?.find((c) => c.id === id)
            return (
              <li key={`c-${id}`}>
                <button
                  type="button"
                  className="rounded-full bg-steel-100 px-2.5 py-1 text-xs font-semibold hover:bg-steel-200"
                  onClick={() => change({ categories: draft.categories.filter((c) => c !== id) })}
                >
                  {category?.name ?? `Category ${id}`} <span aria-hidden>×</span>
                  {' '}
<span className="sr-only">remove</span>
                </button>
              </li>
            )
          })}
          {draft.products.map((product) => (
            <li key={`p-${product.id}`}>
              <button
                type="button"
                className="rounded-full bg-steel-100 px-2.5 py-1 text-xs font-semibold hover:bg-steel-200"
                onClick={() => change({ products: draft.products.filter((p) => p.id !== product.id) })}
              >
                {product.name} <span aria-hidden>×</span>
                {' '}
<span className="sr-only">remove</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  )
}

function RuleDialog({
  kind,
  draft,
  setDraft,
  busy,
  error,
  onSave,
}: {
  kind: Kind
  draft: Draft | null
  setDraft: (draft: Draft | null) => void
  busy: boolean
  error: unknown
  onSave: (draft: Draft) => void
}) {
  const [shown, setShown] = useState('')
  if (!draft) return null
  const change = (changes: Partial<Draft>) => setDraft({ ...draft, ...changes })

  return (
    <FormDialog
      open
      title={`${draft.id ? 'Edit' : 'Add'} ${kind}`}
      busy={busy}
      problem={shown}
      error={error}
      onClose={() => {
        setShown('')
        setDraft(null)
      }}
      onSubmit={() => {
        const found = problem(draft, kind)
        setShown(found)
        if (!found) onSave(draft)
      }}
    >
      {kind === 'offer' ? (
        <FormField id="rule-name" label="Name" required maxLength={120} value={draft.name} onChange={(e) => change({ name: e.target.value })} hint="Shown to customers, e.g. “Monsoon tool sale”." />
      ) : (
        <FormField
          id="rule-code"
          label="Code"
          required
          maxLength={30}
          value={draft.code}
          onChange={(e) => change({ code: e.target.value.toUpperCase() })}
          hint="What customers type at checkout, e.g. WELCOME50."
        />
      )}
      <FormField id="rule-description" label="Description" maxLength={255} value={draft.description} onChange={(e) => change({ description: e.target.value })} />
      {kind === 'offer' && (
        <div className="grid grid-cols-2 gap-3">
          <SelectField
            id="rule-benefit"
            label="Gives"
            value={draft.benefit}
            onChange={(e) => change({ benefit: e.target.value as Draft['benefit'] })}
          >
            <option value="discount">A discount</option>
            <option value="free_delivery">Free delivery</option>
          </SelectField>
          <FormField
            id="rule-campaign"
            label="Festival / campaign"
            maxLength={60}
            value={draft.campaign}
            onChange={(e) => change({ campaign: e.target.value })}
            hint="Optional label, e.g. Diwali."
          />
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        {(kind === 'coupon' || draft.benefit === 'discount') && (
          <>
            <SelectField
              id="rule-type"
              label="Discount"
              value={draft.discount_type}
              onChange={(e) => change({ discount_type: e.target.value as Draft['discount_type'] })}
            >
              <option value="percent">Percentage</option>
              <option value="fixed">Fixed amount (₹)</option>
            </SelectField>
            <FormField
              id="rule-value"
              label={draft.discount_type === 'percent' ? 'Percent off' : 'Amount off (₹)'}
              required
              inputMode="decimal"
              value={draft.value}
              onChange={(e) => change({ value: e.target.value })}
            />
          </>
        )}
        {(kind === 'coupon' || draft.benefit === 'discount') && draft.discount_type === 'percent' && (
          <FormField
            id="rule-cap"
            label="At most (₹)"
            inputMode="decimal"
            value={draft.max_discount_amount}
            onChange={(e) => change({ max_discount_amount: e.target.value })}
            hint="Empty: no limit."
          />
        )}
        <FormField
          id="rule-min"
          label="Minimum spend (₹)"
          inputMode="decimal"
          value={draft.min_order_value}
          onChange={(e) => change({ min_order_value: e.target.value })}
          hint="Empty: none."
        />
        <FormField id="rule-start" label="Starts" type="datetime-local" required value={draft.starts_at} onChange={(e) => change({ starts_at: e.target.value })} />
        <FormField id="rule-end" label="Ends" type="datetime-local" value={draft.ends_at} onChange={(e) => change({ ends_at: e.target.value })} hint="Empty: until switched off." />
        {kind === 'offer' ? (
          <>
            <FormField
              id="rule-priority"
              label="Priority"
              type="number"
              min={0}
              value={draft.priority}
              onChange={(e) => change({ priority: e.target.value })}
              hint="Lower wins when offers overlap."
            />
            <FormField
              id="rule-min-qty"
              label="Minimum units of an item"
              type="number"
              min={0}
              value={draft.min_quantity}
              onChange={(e) => change({ min_quantity: e.target.value })}
              hint="e.g. 10 for “10+ bags”. Empty: any."
            />
            <FormField
              id="rule-first-orders"
              label="Only a customer’s first … orders"
              type="number"
              min={1}
              value={draft.first_orders}
              onChange={(e) => change({ first_orders: e.target.value })}
              hint="1 = first order only. Empty: everyone."
            />
            <FormField
              id="rule-offer-limit"
              label="Total uses"
              type="number"
              min={1}
              value={draft.offer_usage_limit}
              onChange={(e) => change({ offer_usage_limit: e.target.value })}
              hint="Orders in total. Empty: unlimited."
            />
            <FormField
              id="rule-offer-per-customer"
              label="Uses per customer"
              type="number"
              min={1}
              value={draft.offer_per_customer}
              onChange={(e) => change({ offer_per_customer: e.target.value })}
              hint="Empty: unlimited."
            />
          </>
        ) : (
          <>
            <FormField
              id="rule-limit"
              label="Total uses"
              type="number"
              min={1}
              value={draft.usage_limit}
              onChange={(e) => change({ usage_limit: e.target.value })}
              hint="Empty: unlimited."
            />
            <FormField
              id="rule-per-customer"
              label="Uses per customer"
              type="number"
              min={1}
              value={draft.per_customer_limit}
              onChange={(e) => change({ per_customer_limit: e.target.value })}
            />
          </>
        )}
      </div>
      <Targets draft={draft} change={change} />
      {kind === 'coupon' && (
        <CheckField
          id="rule-checkout"
          label="Show at checkout"
          hint="Listed under “Available coupons”. Leave off for private codes."
          checked={draft.show_in_checkout}
          onChange={(checked) => change({ show_in_checkout: checked })}
        />
      )}
      <CheckField id="rule-active" label="Switched on" checked={draft.is_active} onChange={(checked) => change({ is_active: checked })} />
    </FormDialog>
  )
}

function period(rule: DiscountRule) {
  return (
    <>
      {dateTime(rule.starts_at)}
      <span className="block text-xs text-ink-600">{rule.ends_at ? `until ${dateTime(rule.ends_at)}` : 'no end date'}</span>
    </>
  )
}

type RuleQuery = Parameters<typeof ListView<Rule>>[0]['query']
type RuleCrud = ReturnType<typeof useOfferCrud> | ReturnType<typeof useCouponCrud>

function useRuleFilters() {
  const list = useListParams()
  return { list, filters: { page: list.page, q: list.get('q'), state: list.get('state') } }
}

function Offers() {
  const { list, filters } = useRuleFilters()
  return <Rules kind="offer" list={list} query={useOffers(filters) as RuleQuery} crud={useOfferCrud()} />
}

function Coupons() {
  const { list, filters } = useRuleFilters()
  return <Rules kind="coupon" list={list} query={useCoupons(filters) as RuleQuery} crud={useCouponCrud()} />
}

/** Administrators only: a store manager never gets as far as asking the API. */
function RulesPage({ kind }: { kind: Kind }) {
  const title = kind === 'offer' ? 'Offers' : 'Coupons'
  usePageMeta(title)
  const session = useSession()
  if (!session.can.manage_offers) return <NotAllowed what={title} />
  return kind === 'offer' ? <Offers /> : <Coupons />
}

function Rules({ kind, list, query, crud }: { kind: Kind; list: ListParams; query: RuleQuery; crud: RuleCrud }) {
  const title = kind === 'offer' ? 'Offers' : 'Coupons'
  const toast = useToast()
  const { save, remove } = crud as ReturnType<typeof useOfferCrud>
  const [draft, setDraft] = useState<Draft | null>(null)
  const [deleting, setDeleting] = useState<Rule | null>(null)
  const title_ = (rule: Rule) => (kind === 'offer' ? (rule as Offer).name : (rule as Coupon).code)

  const actions: Column<Rule> = {
    header: 'Actions',
    cell: (rule) => (
      <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
        <button
          type="button"
          className="btn-secondary px-2.5 py-1.5"
          onClick={() => {
            save.reset()
            setDraft(toDraft(rule))
          }}
        >
          Edit{' '}
<span className="sr-only">{title_(rule)}</span>
        </button>
        <button
          type="button"
          className="btn-secondary px-2.5 py-1.5"
          disabled={save.isPending}
          onClick={() =>
            save.mutate(
              { id: rule.id, data: { is_active: !rule.is_active } },
              {
                onSuccess: () => toast.show(`${title_(rule)} switched ${rule.is_active ? 'off' : 'on'}.`),
                onError: (error) => toast.show(errorMessage(error), { tone: 'error' }),
              },
            )
          }
        >
          {rule.is_active ? 'Switch off' : 'Switch on'}
          {' '}
<span className="sr-only">{title_(rule)}</span>
        </button>
        <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => setDeleting(rule)}>
          Delete{' '}
<span className="sr-only">{title_(rule)}</span>
        </button>
      </span>
    ),
  }
  const columns: Column<Rule>[] = [
    {
      header: kind === 'offer' ? 'Offer' : 'Code',
      cell: (rule) => (
        <>
          <span className="font-semibold">{title_(rule)}</span>
          {rule.description && <span className="block text-xs text-ink-600">{rule.description}</span>}
        </>
      ),
    },
    { header: 'Discount', cell: (rule) => rule.summary },
    { header: 'Period', cell: period },
    ...(kind === 'coupon'
      ? ([
          {
            header: 'Used',
            numeric: true,
            cell: (rule) => {
              const coupon = rule as Coupon
              return coupon.usage_limit ? `${coupon.used_count} of ${coupon.usage_limit}` : coupon.used_count
            },
          },
          {
            header: 'Checkout',
            cell: (rule) => ((rule as Coupon).show_in_checkout ? <Badge tone="info">Shown</Badge> : <Badge>Private</Badge>),
          },
        ] satisfies Column<Rule>[])
      : ([
          {
            header: 'Conditions',
            cell: (rule) => {
              const offer = rule as Offer
              const used = offer.usage_limit ? `${offer.used_count ?? 0} of ${offer.usage_limit} used` : ''
              const parts = [...(offer.conditions ?? []), used].filter(Boolean)
              return parts.length ? <span className="text-xs">{parts.join(' · ')}</span> : <span className="text-xs text-ink-600">None</span>
            },
          },
          { header: 'Priority', numeric: true, cell: (rule) => (rule as Offer).priority },
        ] satisfies Column<Rule>[])),
    { header: 'Status', cell: (rule) => <StatusBadge status={rule.state} text={STATE_TEXT[rule.state]} /> },
    actions,
  ]

  return (
    <>
      <PageHeader
        title={title}
        description={
          kind === 'offer'
            ? 'Discounts that apply by themselves. The checkout calculates them; nothing is calculated here.'
            : 'Codes customers enter at checkout. The checkout checks every rule when the code is used.'
        }
        actions={
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              save.reset()
              setDraft(toDraft(null))
            }}
          >
            Add {kind}
          </button>
        }
      />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder={kind === 'offer' ? 'Search offers' : 'Search codes'} />
        <FilterSelect list={list} name="state" label="Status" options={STATES} />
      </FilterBar>
      <ListView query={query} list={list} caption={title} columns={columns} rowKey={(rule) => rule.id} empty={`No ${title.toLowerCase()} yet`} />

      <RuleDialog
        kind={kind}
        draft={draft}
        setDraft={setDraft}
        busy={save.isPending}
        error={save.error}
        onSave={(current) =>
          save.mutate(
            { id: current.id, data: toInput(current, kind) },
            {
              onSuccess: () => {
                toast.show(`${kind === 'offer' ? 'Offer' : 'Coupon'} saved.`)
                setDraft(null)
              },
            },
          )
        }
      />
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting ? title_(deleting) : ''}?`}
        confirmLabel={`Delete ${kind}`}
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
              toast.show(`${title_(deleting)} deleted.`)
              setDeleting(null)
            },
          })
        }}
      >
        <p>
          {kind === 'offer'
            ? 'Orders already placed keep the discount they got.'
            : 'A coupon that has been used can’t be deleted; switch it off instead.'}
        </p>
      </ConfirmDialog>
    </>
  )
}

export const AdminOffersPage = () => <RulesPage kind="offer" />
export const AdminCouponsPage = () => <RulesPage kind="coupon" />
