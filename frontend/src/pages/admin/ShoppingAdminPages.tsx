import { useState } from 'react'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import { useAdminBundles, useBundleCrud, useCategories, useProducts, useRecommendationRuleCrud, useRecommendationRules } from '@/features/admin/api'
import { flattenCategories } from '@/features/admin/categories'
import { useSession } from '@/features/admin/session'
import type { BundleKind, BundleRow, RecommendationRuleRow } from '@/features/admin/types'
import { CheckField, ConfirmDialog, DataTable, FormDialog, NotAllowed, PageHeader, Panel, SelectField, StatusBadge, type Column } from '@/features/admin/ui'
import { usePageMeta } from '@/lib/usePageMeta'

const KINDS: [BundleKind, string][] = [
  ['diy_repair', 'DIY repair kit'],
  ['plumbing', 'Plumbing kit'],
  ['electrical', 'Electrical kit'],
  ['painting', 'Painting kit'],
  ['drilling', 'Drilling kit'],
  ['tiling', 'Tile / fixing kit'],
  ['construction', 'Basic construction kit'],
  ['custom', 'Custom kit'],
]
function Loading({ query, what }: { query: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }; what: string }) {
  if (query.isPending) return <PageSpinner label={`Loading ${what}…`} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title={`Couldn’t load ${what}`} />
  return null
}

const STATE_TEXT = { inactive: 'Off', scheduled: 'Scheduled', expired: 'Ended', live: 'Live' }

interface ItemDraft {
  product: number
  name: string
  quantity: string
  note: string
  is_optional: boolean
}

interface BundleDraft {
  id?: number
  name: string
  kind: BundleKind
  description: string
  promo_label: string
  priority: string
  is_active: boolean
  items: ItemDraft[]
}

function ItemEditor({ items, onChange }: { items: ItemDraft[]; onChange: (items: ItemDraft[]) => void }) {
  const [term, setTerm] = useState('')
  const [search, setSearch] = useState('')
  const found = useProducts({ q: search, page_size: 8, state: 'live' }, search.length >= 2)
  const set = (index: number, change: Partial<ItemDraft>) => onChange(items.map((item, i) => (i === index ? { ...item, ...change } : item)))
  return (
    <div>
      <p className="label">Products in the bundle</p>
      {items.length > 0 && (
        <ul className="mb-2 space-y-2" aria-label="Bundle items">
          {items.map((item, index) => (
            <li key={item.product} className="grid items-end gap-2 rounded-md bg-steel-50 p-2 sm:grid-cols-[1fr_5rem_1fr_auto_auto]">
              <span className="text-sm font-semibold">{item.name}</span>
              <FormField id={`item-${item.product}-qty`} label="Quantity" type="number" min={1} max={999} value={item.quantity} onChange={(e) => set(index, { quantity: e.target.value })} />
              <FormField id={`item-${item.product}-note`} label="Note" maxLength={120} value={item.note} onChange={(e) => set(index, { note: e.target.value })} />
              <CheckField id={`item-${item.product}-optional`} label="Optional" checked={item.is_optional} onChange={(v) => set(index, { is_optional: v })} />
              <button type="button" className="text-sm font-semibold text-danger-600 hover:underline" onClick={() => onChange(items.filter((_, i) => i !== index))}>
                Remove <span className="sr-only">{item.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-end gap-2">
        <FormField id="bundle-product-find" label="Add a product" className="flex-1" placeholder="Name or SKU" value={term} onChange={(e) => setTerm(e.target.value)} />
        <button type="button" className="btn-dark" disabled={term.trim().length < 2} onClick={() => setSearch(term.trim())}>
          Find
        </button>
      </div>
      {search && found.data && (
        <ul className="mt-2 max-h-40 divide-y divide-steel-100 overflow-y-auto rounded-md ring-1 ring-steel-200" aria-label="Matching products">
          {found.data.results.length === 0 && <li className="px-3 py-2 text-sm text-ink-600">No product matches “{search}”.</li>}
          {found.data.results
            .filter((p) => !items.some((i) => i.product === p.id))
            .map((product) => (
              <li key={product.id}>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left text-sm hover:bg-steel-50"
                  onClick={() => onChange([...items, { product: product.id, name: product.name, quantity: '1', note: '', is_optional: false }])}
                >
                  Add {product.name}
                </button>
              </li>
            ))}
        </ul>
      )}
    </div>
  )
}

export function AdminBundlesPage() {
  usePageMeta('Bundles')
  const session = useSession()
  const bundles = useAdminBundles()
  const { save, remove } = useBundleCrud()
  const toast = useToast()
  const [draft, setDraft] = useState<BundleDraft | null>(null)
  const [problem, setProblem] = useState('')
  const [deleting, setDeleting] = useState<BundleRow | null>(null)
  if (!session.can.manage_catalog) return <NotAllowed what="Bundles" />

  const open = (row: BundleRow | null) => {
    save.reset()
    setProblem('')
    setDraft({
      id: row?.id,
      name: row?.name ?? '',
      kind: row?.kind ?? 'custom',
      description: row?.description ?? '',
      promo_label: row?.promo_label ?? '',
      priority: String(row?.priority ?? 100),
      is_active: row?.is_active ?? true,
      items: row?.items.map((i) => ({ product: i.product, name: i.name, quantity: String(i.quantity), note: i.note, is_optional: i.is_optional })) ?? [],
    })
  }

  const columns: Column<BundleRow>[] = [
    {
      header: 'Bundle',
      cell: (row) => (
        <>
          <span className="font-semibold">{row.name}</span>
          <span className="block text-xs text-ink-600">{KINDS.find(([k]) => k === row.kind)?.[1]}</span>
        </>
      ),
    },
    { header: 'Items', cell: (row) => `${row.items.length} product(s)${row.items.some((i) => !i.live) ? ' · some not on sale' : ''}` },
    { header: 'Priority', numeric: true, cell: (row) => row.priority },
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
    <>
      <PageHeader
        title="Bundles"
        description="Kits of real products for common jobs. Customers see them priced live (bulk prices, offers, stock, delivery) and can change items before adding. Every change is recorded in the audit log."
        actions={
          <button type="button" className="btn-primary" onClick={() => open(null)}>
            Add bundle
          </button>
        }
      />
      <Loading query={bundles} what="bundles" />
      {bundles.data &&
        (bundles.data.length === 0 ? (
          <Panel>
            <p className="py-8 text-center text-sm text-ink-600">No bundles yet.</p>
          </Panel>
        ) : (
          <DataTable caption="Bundles" columns={columns} rows={bundles.data} rowKey={(row) => row.id} />
        ))}
      <FormDialog
        open={draft !== null}
        title={draft?.id ? 'Edit bundle' : 'Add bundle'}
        busy={save.isPending}
        error={save.error}
        problem={problem}
        onClose={() => setDraft(null)}
        onSubmit={() => {
          if (!draft) return
          const found = !draft.name.trim() ? 'Give the bundle a name.' : draft.items.length === 0 ? 'Add the products of this bundle.' : ''
          setProblem(found)
          if (found) return
          save.mutate(
            {
              id: draft.id,
              data: {
                name: draft.name.trim(),
                kind: draft.kind,
                description: draft.description.trim(),
                promo_label: draft.promo_label.trim(),
                priority: Number(draft.priority) || 100,
                is_active: draft.is_active,
                item_rows: draft.items.map((i) => ({ product: i.product, quantity: Math.max(1, Number(i.quantity) || 1), note: i.note.trim(), is_optional: i.is_optional })),
              },
            },
            {
              onSuccess: () => {
                toast.show('Bundle saved.')
                setDraft(null)
              },
            },
          )
        }}
      >
        {draft && (
          <>
            <FormField id="bundle-name" label="Name" required maxLength={120} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <SelectField id="bundle-kind" label="Type" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as BundleKind })}>
              {KINDS.map(([value, text]) => (
                <option key={value} value={value}>
                  {text}
                </option>
              ))}
            </SelectField>
            <FormField id="bundle-description" label="Description" maxLength={300} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            <div className="grid grid-cols-2 gap-3">
              <FormField id="bundle-promo" label="Badge (optional)" maxLength={40} value={draft.promo_label} onChange={(e) => setDraft({ ...draft, promo_label: e.target.value })} />
              <FormField id="bundle-priority" label="Priority" type="number" min={0} value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })} hint="Lower comes first." />
            </div>
            <ItemEditor items={draft.items} onChange={(items) => setDraft({ ...draft, items })} />
            <CheckField id="bundle-active" label="Switched on" checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} />
          </>
        )}
      </FormDialog>
      <ConfirmDialog
        open={deleting !== null}
        title="Delete bundle?"
        confirmLabel="Delete"
        danger
        busy={remove.isPending}
        error={remove.error}
        onClose={() => setDeleting(null)}
        onConfirm={() =>
          deleting &&
          remove.mutate(deleting.id, {
            onSuccess: () => {
              toast.show('Bundle deleted.')
              setDeleting(null)
            },
          })
        }
      >
        {deleting?.name} will no longer be shown to customers.
      </ConfirmDialog>
    </>
  )
}

interface RuleDraft {
  id?: number
  source_category: string
  target_category: string
  label: string
  priority: string
  is_active: boolean
}

export function AdminRecommendationRulesPage() {
  usePageMeta('Recommendations')
  const session = useSession()
  const rules = useRecommendationRules()
  const categories = useCategories()
  const flat = flattenCategories(categories.data ?? [])
  const { save, remove } = useRecommendationRuleCrud()
  const toast = useToast()
  const [draft, setDraft] = useState<RuleDraft | null>(null)
  const [problem, setProblem] = useState('')
  if (!session.can.manage_catalog) return <NotAllowed what="Recommendations" />

  const open = (row: RecommendationRuleRow | null) => {
    save.reset()
    setProblem('')
    setDraft({
      id: row?.id,
      source_category: String(row?.source_category ?? ''),
      target_category: String(row?.target_category ?? ''),
      label: row?.label ?? '',
      priority: String(row?.priority ?? 100),
      is_active: row?.is_active ?? true,
    })
  }

  const columns: Column<RecommendationRuleRow>[] = [
    { header: 'When looking at', cell: (row) => row.source_name },
    { header: 'Suggest from', cell: (row) => row.target_name },
    { header: 'Reason shown', cell: (row) => row.label || '—' },
    { header: 'Priority', numeric: true, cell: (row) => row.priority },
    { header: 'Status', cell: (row) => <StatusBadge status={row.is_active ? 'live' : 'inactive'} text={row.is_active ? 'On' : 'Off'} /> },
    {
      header: 'Actions',
      cell: (row) => (
        <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => open(row)}>
            Edit <span className="sr-only">rule {row.id}</span>
          </button>
          <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => remove.mutate(row.id, { onSuccess: () => toast.show('Rule deleted.') })}>
            Delete <span className="sr-only">rule {row.id}</span>
          </button>
        </span>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Recommendations"
        description="“Complete the project” rules: customers looking at a product in one category see popular, in-stock products of another (e.g. Wall Paints → Painting Tools). Product-to-product links (needed with it, compatible, alternatives) are set on each product. Every change is audited."
        actions={
          <button type="button" className="btn-primary" onClick={() => open(null)}>
            Add rule
          </button>
        }
      />
      <Loading query={rules} what="rules" />
      {rules.data && rules.data.length > 0 && <DataTable caption="Recommendation rules" columns={columns} rows={rules.data} rowKey={(row) => row.id} />}
      {rules.data && rules.data.length === 0 && (
        <Panel>
          <p className="py-8 text-center text-sm text-ink-600">No rules yet.</p>
        </Panel>
      )}
      <FormDialog
        open={draft !== null}
        title={draft?.id ? 'Edit rule' : 'Add rule'}
        busy={save.isPending}
        error={save.error}
        problem={problem}
        onClose={() => setDraft(null)}
        onSubmit={() => {
          if (!draft) return
          const found = !draft.source_category || !draft.target_category ? 'Choose both categories.' : draft.source_category === draft.target_category ? 'Choose two different categories.' : ''
          setProblem(found)
          if (found) return
          save.mutate(
            {
              id: draft.id,
              data: {
                source_category: Number(draft.source_category),
                target_category: Number(draft.target_category),
                label: draft.label.trim(),
                priority: Number(draft.priority) || 100,
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
            {(['source_category', 'target_category'] as const).map((field) => (
              <SelectField
                key={field}
                id={`rule-${field}`}
                label={field === 'source_category' ? 'When looking at a product in' : 'Suggest popular products from'}
                value={draft[field]}
                onChange={(e) => setDraft({ ...draft, [field]: e.target.value })}
              >
                <option value="">Choose…</option>
                {flat.map(({ category, path }) => (
                  <option key={category.id} value={category.id}>
                    {path}
                  </option>
                ))}
              </SelectField>
            ))}
            <FormField id="rule-label" label="Reason shown to customers" maxLength={60} value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
            <FormField id="rule-priority" label="Priority" type="number" min={0} value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })} hint="Lower comes first." />
            <CheckField id="rule-active" label="Switched on" checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} />
          </>
        )}
      </FormDialog>
    </>
  )
}
