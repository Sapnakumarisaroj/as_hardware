import { useState } from 'react'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import {
  useAllZones,
  useCategories,
  useCollectionCrud,
  useCollectionPreview,
  useCollections,
  useFreeDeliveryRuleCrud,
  useFreeDeliveryRules,
  useOptionTypeCrud,
  useOptionTypes,
  usePaymentSettings,
  useProducts,
  useSavePaymentSettings,
} from '@/features/admin/api'
import { flattenCategories } from '@/features/admin/categories'
import { useSession } from '@/features/admin/session'
import type { CollectionRow, CollectionRule, FreeDeliveryRuleRow, OptionTypeRow } from '@/features/admin/types'
import {
  Badge,
  CheckField,
  ConfirmDialog,
  DataTable,
  dateTime,
  errorMessage,
  FormDialog,
  NotAllowed,
  PageHeader,
  Panel,
  SelectField,
  StatusBadge,
  type Column,
} from '@/features/admin/ui'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'


/*
 * Phase 15 commerce settings. These screens only store rules: prices, delivery fees and whether
 * cash on delivery is allowed are calculated by the server (one pricing engine), never here.
 */

const STATE_TEXT: Record<string, string> = {
  live: 'Running',
  scheduled: 'Scheduled',
  expired: 'Ended',
  inactive: 'Switched off',
}

/** ISO instant ↔ the value of <input type="datetime-local"> in the viewer's time zone. */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}
const fromLocalInput = (value: string): string | null => (value ? new Date(value).toISOString() : null)

function Loading({ query, what }: { query: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }; what: string }) {
  if (query.isPending) return <PageSpinner label={`Loading ${what}…`} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title={`Couldn’t load ${what}`} />
  return null
}

/** A category picker over the three-level tree (department › category › subcategory). */
function CategoryChooser({ id, label, chosen, onChange }: { id: string; label: string; chosen: number[]; onChange: (ids: number[]) => void }) {
  const categories = useCategories()
  const flat = flattenCategories(categories.data ?? [])
  return (
    <div>
      <SelectField
        id={id}
        label={label}
        value=""
        onChange={(e) => {
          const value = Number(e.target.value)
          if (value && !chosen.includes(value)) onChange([...chosen, value])
        }}
      >
        <option value="">Choose…</option>
        {flat.map(({ category, path }) => (
          <option key={category.id} value={category.id}>
            {path}
          </option>
        ))}
      </SelectField>
      {chosen.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {chosen.map((categoryId) => (
            <li key={categoryId}>
              <button
                type="button"
                className="rounded-full bg-steel-100 px-2.5 py-1 text-xs font-semibold hover:bg-steel-200"
                onClick={() => onChange(chosen.filter((c) => c !== categoryId))}
              >
                {flat.find((e) => e.category.id === categoryId)?.path ?? `Category ${categoryId}`} <span aria-hidden>×</span>
                {' '}<span className="sr-only">remove</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Find products by name or SKU and keep an ordered list of them. */
function ProductChooser({
  chosen,
  onChange,
  ordered = false,
}: {
  chosen: { id: number; name: string }[]
  onChange: (products: { id: number; name: string }[]) => void
  ordered?: boolean
}) {
  const [term, setTerm] = useState('')
  const [search, setSearch] = useState('')
  const found = useProducts({ q: search, page_size: 8, state: 'live' }, search.length >= 2)
  const move = (index: number, by: number) => {
    const next = [...chosen]
    const [item] = next.splice(index, 1)
    if (!item) return
    next.splice(index + by, 0, item)
    onChange(next)
  }
  return (
    <div>
      <div className="flex items-end gap-2">
        <FormField id="product-find" label="Add a product" className="flex-1" placeholder="Name or SKU" value={term} onChange={(e) => setTerm(e.target.value)} />
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
                disabled={chosen.some((p) => p.id === product.id)}
                onClick={() => onChange([...chosen, { id: product.id, name: product.name }])}
              >
                {product.name} <span className="text-xs text-ink-600">SKU {product.sku}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {chosen.length > 0 && (
        <ol className="mt-3 space-y-1">
          {chosen.map((product, index) => (
            <li key={product.id} className="flex items-center gap-2 rounded-md bg-steel-50 px-2 py-1 text-sm">
              {ordered && <span className="w-5 text-xs text-ink-600">{index + 1}.</span>}
              <span className="min-w-0 flex-1 truncate">{product.name}</span>
              {ordered && (
                <>
                  <button type="button" className="px-1 text-xs font-semibold" disabled={index === 0} onClick={() => move(index, -1)}>
                    Up{' '}<span className="sr-only">{product.name}</span>
                  </button>
                  <button type="button" className="px-1 text-xs font-semibold" disabled={index === chosen.length - 1} onClick={() => move(index, 1)}>
                    Down{' '}<span className="sr-only">{product.name}</span>
                  </button>
                </>
              )}
              <button type="button" className="px-1 text-xs font-semibold text-danger-600" onClick={() => onChange(chosen.filter((p) => p.id !== product.id))}>
                Remove{' '}<span className="sr-only">{product.name}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

// --- Product options -----------------------------------------------------------------------------

interface OptionDraft {
  id?: number
  name: string
  unit: string
  sort_order: string
  is_active: boolean
  categories: number[]
  values: { id?: number; value: string; used_by: number }[]
}

export function AdminOptionTypesPage() {
  usePageMeta('Product options')
  const session = useSession()
  const types = useOptionTypes()
  const { save, remove } = useOptionTypeCrud()
  const toast = useToast()
  const [draft, setDraft] = useState<OptionDraft | null>(null)
  const [problem, setProblem] = useState('')
  const [deleting, setDeleting] = useState<OptionTypeRow | null>(null)
  const canEdit = session.can.manage_catalog

  const open = (row: OptionTypeRow | null) => {
    save.reset()
    setProblem('')
    setDraft({
      id: row?.id,
      name: row?.name ?? '',
      unit: row?.unit ?? '',
      sort_order: String(row?.sort_order ?? 0),
      is_active: row?.is_active ?? true,
      categories: row?.categories ?? [],
      values: row?.values.map((v) => ({ id: v.id, value: v.value, used_by: v.used_by })) ?? [{ value: '', used_by: 0 }],
    })
  }

  const columns: Column<OptionTypeRow>[] = [
    {
      header: 'Option',
      cell: (row) => (
        <>
          <span className="font-semibold">{row.name}</span>
          {row.unit && <span className="ml-1 text-xs text-ink-600">({row.unit})</span>}
        </>
      ),
    },
    { header: 'Values', cell: (row) => row.values.map((v) => v.value).join(', ') || '—' },
    {
      header: 'Used for',
      cell: (row) => (row.category_details.length ? row.category_details.map((c) => c.name).join(', ') : 'Any product'),
    },
    { header: 'Variants', numeric: true, cell: (row) => row.variant_count },
    { header: 'Status', cell: (row) => (row.is_active ? <Badge tone="good">Active</Badge> : <Badge>Inactive</Badge>) },
    ...(canEdit
      ? [
          {
            header: 'Actions',
            cell: (row: OptionTypeRow) => (
              <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
                <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => open(row)}>
                  Edit{' '}<span className="sr-only">{row.name}</span>
                </button>
                <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => setDeleting(row)}>
                  Delete{' '}<span className="sr-only">{row.name}</span>
                </button>
              </span>
            ),
          },
        ]
      : []),
  ]

  return (
    <>
      <PageHeader
        title="Product options"
        description="The ways variants differ (Grade, Bag size, Thickness, Length, Colour…). Customers choose them on the product page; Phase 16 filters use them."
        actions={
          canEdit && (
            <button type="button" className="btn-primary" onClick={() => open(null)}>
              Add option
            </button>
          )
        }
      />
      <Loading query={types} what="options" />
      {types.data &&
        (types.data.length === 0 ? (
          <Panel>
            <p className="py-8 text-center text-sm text-ink-600">No options yet. Add one, then set it on product variants.</p>
          </Panel>
        ) : (
          <DataTable caption="Product options" columns={columns} rows={types.data} rowKey={(row) => row.id} />
        ))}

      <FormDialog
        open={draft !== null}
        title={draft?.id ? 'Edit option' : 'Add option'}
        busy={save.isPending}
        error={save.error}
        problem={problem}
        onClose={() => setDraft(null)}
        onSubmit={() => {
          if (!draft) return
          const values = draft.values.filter((v) => v.value.trim())
          const found = !draft.name.trim()
            ? 'Give the option a name, e.g. Grade.'
            : new Set(values.map((v) => v.value.trim().toLowerCase())).size !== values.length
              ? 'A value is listed twice.'
              : ''
          setProblem(found)
          if (found) return
          save.mutate(
            {
              id: draft.id,
              data: {
                name: draft.name.trim(),
                unit: draft.unit.trim(),
                sort_order: Number(draft.sort_order) || 0,
                is_active: draft.is_active,
                categories: draft.categories,
                value_list: values.map((v) => ({ id: v.id, value: v.value.trim() })),
              },
            },
            {
              onSuccess: () => {
                toast.show('Option saved.')
                setDraft(null)
              },
            },
          )
        }}
      >
        {draft && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <FormField id="option-name" label="Name" required maxLength={60} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              <FormField id="option-unit" label="Unit" maxLength={20} value={draft.unit} onChange={(e) => setDraft({ ...draft, unit: e.target.value })} hint="e.g. kg, mm. Optional." />
              <FormField
                id="option-order"
                label="Position"
                type="number"
                min={0}
                value={draft.sort_order}
                onChange={(e) => setDraft({ ...draft, sort_order: e.target.value })}
                hint="Lower comes first on the product page."
              />
            </div>
            <CategoryChooser
              id="option-categories"
              label="Used for (empty: any product)"
              chosen={draft.categories}
              onChange={(categories) => setDraft({ ...draft, categories })}
            />
            <fieldset className="rounded-md p-3 ring-1 ring-steel-200">
              <legend className="px-1 text-sm font-medium">Values</legend>
              {draft.values.map((value, index) => (
                <div key={value.id ?? `new-${index}`} className="mt-2 flex items-end gap-2">
                  <FormField
                    id={`option-value-${index}`}
                    label={`Value ${index + 1}`}
                    className="flex-1"
                    maxLength={80}
                    value={value.value}
                    onChange={(e) =>
                      setDraft({ ...draft, values: draft.values.map((v, i) => (i === index ? { ...v, value: e.target.value } : v)) })
                    }
                    hint={value.used_by ? `Used by ${value.used_by} variant(s); renaming changes them too.` : undefined}
                  />
                  <button
                    type="button"
                    className="btn-secondary px-2.5 py-1.5"
                    disabled={value.used_by > 0}
                    title={value.used_by > 0 ? 'Still used by variants' : undefined}
                    onClick={() => setDraft({ ...draft, values: draft.values.filter((_, i) => i !== index) })}
                  >
                    Remove{' '}<span className="sr-only">value {index + 1}</span>
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="mt-2 text-sm font-semibold text-amber-600 hover:underline"
                onClick={() => setDraft({ ...draft, values: [...draft.values, { value: '', used_by: 0 }] })}
              >
                Add value
              </button>
            </fieldset>
            <CheckField id="option-active" label="Active" checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} />
          </>
        )}
      </FormDialog>
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.name ?? ''}?`}
        confirmLabel="Delete option"
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
        <p>An option still used by variants can’t be deleted; deactivate it instead.</p>
      </ConfirmDialog>
    </>
  )
}

// --- Curated lists -------------------------------------------------------------------------------

const RULES: [CollectionRule, string, string][] = [
  ['manual', 'Chosen products', 'You pick the products and their order (e.g. Deals of the week).'],
  ['best_sellers', 'Best sellers', 'Most units sold in real orders over the last days.'],
  ['new_launches', 'New launches', 'Products launched (or added) in the last days.'],
  ['bulk_pricing', 'Bulk buying', 'Products that have bulk prices.'],
]
const RULE_TEXT = Object.fromEntries(RULES.map(([rule, text]) => [rule, text]))

interface CollectionDraft {
  id?: number
  name: string
  description: string
  rule: CollectionRule
  window_days: string
  max_items: string
  categories: number[]
  starts_at: string
  ends_at: string
  is_active: boolean
  sort_order: string
  products: { id: number; name: string }[]
}

function Preview({ id }: { id: number }) {
  const preview = useCollectionPreview(id)
  if (preview.isPending) return <p className="text-sm text-ink-600">Loading…</p>
  if (preview.isError) return <p className="text-sm text-danger-600">{errorMessage(preview.error)}</p>
  const data = preview.data
  return (
    <div className="text-sm">
      <p className="mb-2">
        {data.count === 0
          ? 'Nothing to show right now, so customers won’t see this list.'
          : `${data.count} product(s) shown${data.is_live ? '' : ' once the list is running'}.`}
      </p>
      <ol className="list-decimal space-y-0.5 pl-5">
        {data.products.map((p) => (
          <li key={p.id}>
            {p.name} <span className="text-xs text-ink-600">{formatPrice(p.price)}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function AdminCollectionsPage() {
  usePageMeta('Curated lists')
  const session = useSession()
  const collections = useCollections()
  const { save, remove } = useCollectionCrud()
  const toast = useToast()
  const [draft, setDraft] = useState<CollectionDraft | null>(null)
  const [problem, setProblem] = useState('')
  const [previewing, setPreviewing] = useState<CollectionRow | null>(null)
  const [deleting, setDeleting] = useState<CollectionRow | null>(null)
  if (!session.can.manage_offers) return <NotAllowed what="Curated lists" />

  const open = (row: CollectionRow | null) => {
    save.reset()
    setProblem('')
    setDraft({
      id: row?.id,
      name: row?.name ?? '',
      description: row?.description ?? '',
      rule: row?.rule ?? 'manual',
      window_days: String(row?.window_days ?? 30),
      max_items: String(row?.max_items ?? 12),
      categories: row?.categories ?? [],
      starts_at: toLocalInput(row?.starts_at),
      ends_at: toLocalInput(row?.ends_at),
      is_active: row?.is_active ?? true,
      sort_order: String(row?.sort_order ?? 0),
      products: row?.items.map((i) => ({ id: i.product_id, name: i.name })) ?? [],
    })
  }

  const columns: Column<CollectionRow>[] = [
    {
      header: 'List',
      cell: (row) => (
        <>
          <span className="font-semibold">{row.name}</span>
          {row.description && <span className="block text-xs text-ink-600">{row.description}</span>}
        </>
      ),
    },
    {
      header: 'Products from',
      cell: (row) => (row.rule === 'manual' ? `${row.items.length} chosen product(s)` : `${RULE_TEXT[row.rule]} (${row.window_days} days)`),
    },
    {
      header: 'Period',
      cell: (row) => (row.starts_at || row.ends_at ? `${dateTime(row.starts_at) || 'now'} – ${row.ends_at ? dateTime(row.ends_at) : 'no end'}` : 'Always'),
    },
    { header: 'Position', numeric: true, cell: (row) => row.sort_order },
    { header: 'Status', cell: (row) => <StatusBadge status={row.state} text={STATE_TEXT[row.state]} /> },
    {
      header: 'Actions',
      cell: (row) => (
        <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => setPreviewing(row)}>
            Preview{' '}<span className="sr-only">{row.name}</span>
          </button>
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => open(row)}>
            Edit{' '}<span className="sr-only">{row.name}</span>
          </button>
          <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => setDeleting(row)}>
            Delete{' '}<span className="sr-only">{row.name}</span>
          </button>
        </span>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Curated lists"
        description="Product lists for the shop front: Deals of the week, Construction essentials, Bulk buying, New launches, Best sellers. A list with no products is never shown."
        actions={
          <button type="button" className="btn-primary" onClick={() => open(null)}>
            Add list
          </button>
        }
      />
      <Loading query={collections} what="lists" />
      {collections.data &&
        (collections.data.length === 0 ? (
          <Panel>
            <p className="py-8 text-center text-sm text-ink-600">No lists yet.</p>
          </Panel>
        ) : (
          <DataTable caption="Curated lists" columns={columns} rows={collections.data} rowKey={(row) => row.id} />
        ))}

      <FormDialog
        open={draft !== null}
        title={draft?.id ? 'Edit list' : 'Add list'}
        busy={save.isPending}
        error={save.error}
        problem={problem}
        onClose={() => setDraft(null)}
        onSubmit={() => {
          if (!draft) return
          const found = !draft.name.trim()
            ? 'Give the list a name; customers see it.'
            : draft.rule === 'manual' && draft.products.length === 0
              ? 'Choose the products for this list.'
              : draft.starts_at && draft.ends_at && draft.ends_at <= draft.starts_at
                ? 'The end must be after the start.'
                : ''
          setProblem(found)
          if (found) return
          save.mutate(
            {
              id: draft.id,
              data: {
                name: draft.name.trim(),
                description: draft.description.trim(),
                rule: draft.rule,
                window_days: Number(draft.window_days) || 30,
                max_items: Number(draft.max_items) || 12,
                categories: draft.categories,
                starts_at: fromLocalInput(draft.starts_at),
                ends_at: fromLocalInput(draft.ends_at),
                is_active: draft.is_active,
                sort_order: Number(draft.sort_order) || 0,
                product_ids: draft.rule === 'manual' ? draft.products.map((p) => p.id) : [],
              },
            },
            {
              onSuccess: () => {
                toast.show('List saved.')
                setDraft(null)
              },
            },
          )
        }}
      >
        {draft && (
          <>
            <FormField id="list-name" label="Name" required maxLength={120} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <FormField id="list-description" label="Description" maxLength={300} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            <SelectField
              id="list-rule"
              label="Products from"
              value={draft.rule}
              onChange={(e) => setDraft({ ...draft, rule: e.target.value as CollectionRule })}
              hint={RULES.find(([rule]) => rule === draft.rule)?.[2]}
            >
              {RULES.map(([rule, text]) => (
                <option key={rule} value={rule}>
                  {text}
                </option>
              ))}
            </SelectField>
            <div className="grid grid-cols-2 gap-3">
              {(draft.rule === 'best_sellers' || draft.rule === 'new_launches') && (
                <FormField
                  id="list-window"
                  label="Look back (days)"
                  type="number"
                  min={1}
                  max={365}
                  value={draft.window_days}
                  onChange={(e) => setDraft({ ...draft, window_days: e.target.value })}
                />
              )}
              <FormField id="list-max" label="Show at most" type="number" min={1} max={60} value={draft.max_items} onChange={(e) => setDraft({ ...draft, max_items: e.target.value })} />
              <FormField id="list-start" label="Starts" type="datetime-local" value={draft.starts_at} onChange={(e) => setDraft({ ...draft, starts_at: e.target.value })} hint="Empty: now." />
              <FormField id="list-end" label="Ends" type="datetime-local" value={draft.ends_at} onChange={(e) => setDraft({ ...draft, ends_at: e.target.value })} hint="Empty: no end." />
              <FormField
                id="list-order"
                label="Position"
                type="number"
                min={0}
                value={draft.sort_order}
                onChange={(e) => setDraft({ ...draft, sort_order: e.target.value })}
                hint="Lower comes first on the home page."
              />
            </div>
            {draft.rule === 'manual' ? (
              <ProductChooser ordered chosen={draft.products} onChange={(products) => setDraft({ ...draft, products })} />
            ) : (
              <CategoryChooser
                id="list-categories"
                label="Only from these categories (optional)"
                chosen={draft.categories}
                onChange={(categories) => setDraft({ ...draft, categories })}
              />
            )}
            <CheckField id="list-active" label="Switched on" checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} />
          </>
        )}
      </FormDialog>
      <ConfirmDialog
        open={previewing !== null}
        title={`What customers see in ${previewing?.name ?? ''}`}
        confirmLabel="Done"
        onClose={() => setPreviewing(null)}
        onConfirm={() => setPreviewing(null)}
      >
        {previewing && <Preview id={previewing.id} />}
      </ConfirmDialog>
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.name ?? ''}?`}
        confirmLabel="Delete list"
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
        <p>The products themselves are not changed.</p>
      </ConfirmDialog>
    </>
  )
}

// --- Free-delivery rules -------------------------------------------------------------------------

interface RuleDraft {
  id?: number
  name: string
  description: string
  threshold: string
  zones: number[]
  categories: number[]
  products: { id: number; name: string }[]
  starts_at: string
  ends_at: string
  is_active: boolean
}

export function AdminFreeDeliveryPage() {
  usePageMeta('Free delivery')
  const session = useSession()
  const rules = useFreeDeliveryRules()
  const zones = useAllZones()
  const { save, remove } = useFreeDeliveryRuleCrud()
  const toast = useToast()
  const [draft, setDraft] = useState<RuleDraft | null>(null)
  const [problem, setProblem] = useState('')
  const [deleting, setDeleting] = useState<FreeDeliveryRuleRow | null>(null)
  if (!session.can.manage_offers) return <NotAllowed what="Free-delivery rules" />

  const open = (row: FreeDeliveryRuleRow | null) => {
    save.reset()
    setProblem('')
    setDraft({
      id: row?.id,
      name: row?.name ?? '',
      description: row?.description ?? '',
      threshold: row?.threshold ?? '',
      zones: row?.zones ?? [],
      categories: row?.categories ?? [],
      products: row?.product_details.map((p) => ({ id: p.id, name: p.name })) ?? [],
      starts_at: toLocalInput(row?.starts_at ?? new Date().toISOString()),
      ends_at: toLocalInput(row?.ends_at),
      is_active: row?.is_active ?? true,
    })
  }

  const columns: Column<FreeDeliveryRuleRow>[] = [
    { header: 'Rule', cell: (row) => <span className="font-semibold">{row.name}</span> },
    { header: 'In words', cell: (row) => row.summary },
    { header: 'Period', cell: (row) => `${dateTime(row.starts_at)} – ${row.ends_at ? dateTime(row.ends_at) : 'no end'}` },
    { header: 'Status', cell: (row) => <StatusBadge status={row.state} text={STATE_TEXT[row.state]} /> },
    {
      header: 'Actions',
      cell: (row) => (
        <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => open(row)}>
            Edit{' '}<span className="sr-only">{row.name}</span>
          </button>
          <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => setDeleting(row)}>
            Delete{' '}<span className="sr-only">{row.name}</span>
          </button>
        </span>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Free delivery"
        description="Free delivery from an amount, optionally only in some zones, for some products or categories, or for a period. Each zone’s own “free from” amount keeps working too."
        actions={
          <button type="button" className="btn-primary" onClick={() => open(null)}>
            Add rule
          </button>
        }
      />
      <Loading query={rules} what="free-delivery rules" />
      {rules.data &&
        (rules.data.length === 0 ? (
          <Panel>
            <p className="py-8 text-center text-sm text-ink-600">No extra rules. Each zone’s “free delivery from” amount applies.</p>
          </Panel>
        ) : (
          <DataTable caption="Free-delivery rules" columns={columns} rows={rules.data} rowKey={(row) => row.id} />
        ))}

      <FormDialog
        open={draft !== null}
        title={draft?.id ? 'Edit free-delivery rule' : 'Add free-delivery rule'}
        busy={save.isPending}
        error={save.error}
        problem={problem}
        onClose={() => setDraft(null)}
        onSubmit={() => {
          if (!draft) return
          const found = !draft.name.trim()
            ? 'Give the rule a name; customers see it when it applies.'
            : !(Number(draft.threshold) >= 0) || draft.threshold.trim() === ''
              ? 'Enter the amount from which delivery is free.'
              : draft.ends_at && draft.starts_at && draft.ends_at <= draft.starts_at
                ? 'The end must be after the start.'
                : ''
          setProblem(found)
          if (found) return
          save.mutate(
            {
              id: draft.id,
              data: {
                name: draft.name.trim(),
                description: draft.description.trim(),
                threshold: draft.threshold,
                zones: draft.zones,
                categories: draft.categories,
                products: draft.products.map((p) => p.id),
                starts_at: fromLocalInput(draft.starts_at) ?? new Date().toISOString(),
                ends_at: fromLocalInput(draft.ends_at),
                is_active: draft.is_active,
              },
            },
            {
              onSuccess: () => {
                toast.show('Rule saved.')
                setDraft(null)
              },
            },
          )
        }}
      >
        {draft && (
          <>
            <FormField id="fd-name" label="Name" required maxLength={120} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} hint="Shown to customers, e.g. “Free delivery on cement from ₹2,000”." />
            <div className="grid grid-cols-2 gap-3">
              <FormField id="fd-threshold" label="Free from (₹)" required inputMode="decimal" value={draft.threshold} onChange={(e) => setDraft({ ...draft, threshold: e.target.value })} hint="After discounts." />
              <FormField id="fd-start" label="Starts" type="datetime-local" required value={draft.starts_at} onChange={(e) => setDraft({ ...draft, starts_at: e.target.value })} />
              <FormField id="fd-end" label="Ends" type="datetime-local" value={draft.ends_at} onChange={(e) => setDraft({ ...draft, ends_at: e.target.value })} hint="Empty: until switched off." />
            </div>
            <fieldset className="rounded-md p-3 ring-1 ring-steel-200">
              <legend className="px-1 text-sm font-medium">Zones</legend>
              <p className="mb-2 text-xs text-ink-600">None ticked: every zone.</p>
              <div className="grid gap-1 sm:grid-cols-2">
                {(zones.data ?? []).map((zone) => (
                  <CheckField
                    key={zone.id}
                    id={`fd-zone-${zone.id}`}
                    label={`${zone.store_name} · ${zone.name}`}
                    checked={draft.zones.includes(zone.id)}
                    onChange={(checked) =>
                      setDraft({ ...draft, zones: checked ? [...draft.zones, zone.id] : draft.zones.filter((z) => z !== zone.id) })
                    }
                  />
                ))}
              </div>
            </fieldset>
            <fieldset className="space-y-2 rounded-md p-3 ring-1 ring-steel-200">
              <legend className="px-1 text-sm font-medium">Items that count</legend>
              <p className="text-xs text-ink-600">None chosen: the whole order counts.</p>
              <CategoryChooser id="fd-categories" label="Categories" chosen={draft.categories} onChange={(categories) => setDraft({ ...draft, categories })} />
              <ProductChooser chosen={draft.products} onChange={(products) => setDraft({ ...draft, products })} />
            </fieldset>
            <CheckField id="fd-active" label="Switched on" checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} />
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
        <p>Orders already placed keep the delivery fee they were charged.</p>
      </ConfirmDialog>
    </>
  )
}

// --- Cash on delivery ----------------------------------------------------------------------------

export function AdminPaymentSettingsPage() {
  usePageMeta('Cash on delivery')
  const session = useSession()
  const settings = usePaymentSettings()
  const save = useSavePaymentSettings()
  const toast = useToast()
  const [limit, setLimit] = useState<string | null>(null)
  const [noLimit, setNoLimit] = useState<boolean | null>(null)
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const canEdit = session.is_admin

  if (settings.isPending || settings.isError) return <Loading query={settings} what="payment settings" />
  const data = settings.data
  const currentLimit = limit ?? data.cod_max_order_value ?? ''
  const unlimited = noLimit ?? data.cod_max_order_value === null
  const on = enabled ?? data.cod_enabled
  const invalid = !unlimited && !(Number(currentLimit) >= 1)

  return (
    <>
      <PageHeader
        title="Cash on delivery"
        description="When customers may pay in cash at the door. Checkout explains why when cash isn’t possible, and ordering checks it again."
      />
      <Panel title="Shop-wide rules">
        <form
          noValidate
          className="max-w-md space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (invalid) return
            save.mutate(
              { cod_enabled: on, cod_max_order_value: unlimited ? null : currentLimit },
              {
                onSuccess: () => {
                  toast.show('Cash-on-delivery rules saved.')
                  setLimit(null)
                  setNoLimit(null)
                  setEnabled(null)
                },
                onError: (error) => toast.show(errorMessage(error), { tone: 'error' }),
              },
            )
          }}
        >
          <CheckField id="cod-enabled" label="Offer cash on delivery" checked={on} disabled={!canEdit} onChange={setEnabled} />
          <FormField
            id="cod-limit"
            label="Largest order payable in cash (₹)"
            inputMode="decimal"
            value={unlimited ? '' : currentLimit}
            disabled={!canEdit || unlimited || !on}
            onChange={(e) => setLimit(e.target.value)}
            error={invalid && on ? 'Enter an amount of at least ₹1, or tick “No limit”.' : undefined}
            hint="Orders above this total must be paid online."
          />
          <CheckField id="cod-no-limit" label="No limit" checked={unlimited} disabled={!canEdit || !on} onChange={setNoLimit} />
          {canEdit ? (
            <button type="submit" className="btn-primary" disabled={save.isPending || (invalid && on)}>
              Save
            </button>
          ) : (
            <p className="text-sm text-ink-600">Only administrators can change these rules.</p>
          )}
          <p className="text-xs text-ink-600">
            Last changed {dateTime(data.updated_at)}
            {data.updated_by_name ? ` by ${data.updated_by_name}` : ''}.
          </p>
        </form>
      </Panel>
      <Panel title="Stores and zones without cash on delivery" className="mt-4">
        {data.stores_without_cod.length === 0 && data.zones_without_cod.length === 0 ? (
          <p className="text-sm text-ink-600">Every store and zone accepts cash on delivery. Switch it off per store or zone under Stores.</p>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {data.stores_without_cod.map((store) => (
              <li key={`s-${store.id}`}>Store: {store.name}</li>
            ))}
            {data.zones_without_cod.map((zone) => (
              <li key={`z-${zone.id}`}>
                Zone: {zone.store_name} · {zone.name}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  )
}
