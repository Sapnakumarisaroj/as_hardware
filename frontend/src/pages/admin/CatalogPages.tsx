import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import {
  useAddProductImage,
  useBrandCrud,
  useBrands,
  useCategories,
  useCategoryCrud,
  useChangeProductImage,
  useDeleteProduct,
  useProduct,
  useProducts,
  usePublishProduct,
  useRestoreProduct,
  useSaveProduct,
} from '@/features/admin/api'
import { flattenCategories } from '@/features/admin/categories'
import { useSession } from '@/features/admin/session'
import type { AdminBrand, AdminCategory, AdminProduct, AdminProductRow, ProductInput, RelationKind, VariantInput } from '@/features/admin/types'
import { useOptionTypes } from '@/features/admin/api'
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
  Panel,
  SearchBox,
  SelectField,
  StatusBadge,
  TextAreaField,
  useListParams,
  type Column,
} from '@/features/admin/ui'
import { isNotFound } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from '../NotFoundPage'

// --- Product list --------------------------------------------------------------------------------

function priceRange(product: AdminProductRow): string {
  if (!product.price_from) return '—'
  if (product.price_from === product.price_to) return formatPrice(product.price_from)
  return `${formatPrice(product.price_from)} – ${formatPrice(product.price_to)}`
}

export function AdminProductsPage() {
  usePageMeta('Products')
  const session = useSession()
  const list = useListParams()
  const toast = useToast()
  const categories = useCategories(true)
  const products = useProducts({
    page: list.page,
    q: list.get('q'),
    state: list.get('state'),
    category: list.get('category'),
    stock: list.get('stock'),
    ordering: list.get('ordering'),
  })
  const remove = useDeleteProduct()
  const restore = useRestoreProduct()
  const publish = usePublishProduct()
  const [deleting, setDeleting] = useState<AdminProductRow | null>(null)
  const canEdit = session.can.manage_catalog

  const columns: Column<AdminProductRow>[] = [
    {
      header: 'Product',
      cell: (product) => (
        <span className="flex items-center justify-end gap-3 md:justify-start">
          {product.image ? (
            <img src={product.image} alt="" className="size-10 shrink-0 rounded object-cover ring-1 ring-steel-200" loading="lazy" />
          ) : (
            <span aria-hidden className="size-10 shrink-0 rounded bg-steel-100" />
          )}
          <span>
            <Link to={`/admin/products/${product.id}`} className="font-semibold underline-offset-2 hover:underline">
              {product.name}
            </Link>
            <span className="block text-xs text-ink-600">
              SKU {product.sku}
              {product.brand && ` · ${product.brand.name}`}
            </span>
          </span>
        </span>
      ),
    },
    {
      header: 'Category',
      cell: (product) => [product.category?.name, product.subcategory?.name].filter(Boolean).join(' › ') || '—',
    },
    {
      header: 'Price',
      numeric: true,
      cell: (product) => (
        <>
          {priceRange(product)}
          <span className="block text-xs text-ink-600">
            {product.variant_count} {product.variant_count === 1 ? 'variant' : 'variants'}
          </span>
        </>
      ),
    },
    {
      header: 'Stock',
      numeric: true,
      cell: (product) =>
        product.stock_available > 0 ? product.stock_available.toLocaleString('en-IN') : <Badge tone="bad">Out of stock</Badge>,
    },
    {
      header: 'Status',
      cell: (product) => (
        <span className="flex flex-wrap justify-end gap-1 md:justify-start">
          <StatusBadge status={product.state} text={product.state === 'live' ? 'On sale' : undefined} />
          {!product.is_returnable && <Badge>No returns</Badge>}
          {product.is_featured && <Badge tone="info">Featured</Badge>}
        </span>
      ),
    },
    ...(canEdit
      ? [
          {
            header: 'Actions',
            cell: (product: AdminProductRow) =>
              product.is_deleted ? (
                <button
                  type="button"
                  className="btn-secondary px-2.5 py-1.5"
                  disabled={restore.isPending}
                  onClick={() =>
                    restore.mutate(product.id, {
                      onSuccess: () => toast.show(`${product.name} restored. It is not published yet.`),
                      onError: (error) => toast.show(errorMessage(error), { tone: 'error' }),
                    })
                  }
                >
                  Restore{' '}
<span className="sr-only">{product.name}</span>
                </button>
              ) : (
                <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
                  <button
                    type="button"
                    className="btn-secondary px-2.5 py-1.5"
                    disabled={publish.isPending}
                    onClick={() =>
                      publish.mutate(
                        { id: product.id, is_published: !product.is_published },
                        {
                          onSuccess: () =>
                            toast.show(product.is_published ? `${product.name} is no longer on sale.` : `${product.name} is on sale.`),
                          onError: (error) => toast.show(errorMessage(error), { tone: 'error' }),
                        },
                      )
                    }
                  >
                    {product.is_published ? 'Unpublish' : 'Publish'}
                    {' '}
<span className="sr-only">{product.name}</span>
                  </button>
                  <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => setDeleting(product)}>
                    Delete{' '}
<span className="sr-only">{product.name}</span>
                  </button>
                </span>
              ),
          } satisfies Column<AdminProductRow>,
        ]
      : []),
  ]

  return (
    <>
      <PageHeader
        title="Products"
        description={canEdit ? undefined : 'You can look up products here. Changes are made by an administrator.'}
        actions={
          canEdit && (
            <Link to="/admin/products/new" className="btn-primary">
              Add product
            </Link>
          )
        }
      />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by name or SKU" />
        <FilterSelect
          list={list}
          name="state"
          label="Status"
          all="Not deleted"
          options={[
            ['live', 'On sale'],
            ['draft', 'Not published'],
            ['inactive', 'Inactive'],
            ['deleted', 'Deleted'],
          ]}
        />
        <FilterSelect
          list={list}
          name="category"
          label="Category"
          options={(categories.data ?? []).map((c) => [String(c.id), c.parent_name ? `${c.parent_name} › ${c.name}` : c.name])}
        />
        <FilterSelect list={list} name="stock" label="Stock" options={[['in', 'In stock'], ['out', 'Out of stock']]} />
      </FilterBar>
      <ListView
        query={products}
        list={list}
        caption="Products"
        columns={columns}
        rowKey={(product) => product.id}
        empty="No products yet"
        emptyHint={canEdit ? 'Add the first product to start selling.' : undefined}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.name ?? ''}?`}
        confirmLabel="Delete product"
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
              toast.show(`${deleting.name} deleted. You can restore it from “Deleted”.`)
              setDeleting(null)
            },
          })
        }}
      >
        <p>Customers will no longer see this product. Past orders keep their details, and you can restore the product later.</p>
      </ConfirmDialog>
    </>
  )
}

// --- Product form --------------------------------------------------------------------------------

const UNITS = ['piece', 'pack', 'box', 'kg', 'g', 'litre', 'ml', 'metre', 'sqft', 'bag', 'set', 'pair', 'roll']
const EMPTY_VARIANT: VariantInput = { sku: '', name: '', mrp: '', price: '', is_default: false, is_active: true }

function blank(): ProductInput {
  return {
    name: '',
    sku: '',
    brand: null,
    category: null,
    subcategory: null,
    short_description: '',
    description: '',
    unit: 'piece',
    gst_rate: '18.00',
    hsn_code: '',
    is_active: true,
    is_published: false,
    is_featured: false,
    is_returnable: true,
    variants: [{ ...EMPTY_VARIANT, is_default: true }],
    specifications: [],
    launch_date: null,
    quick_answer: '',
    uses: '',
    installation_steps: '',
    faqs: [],
    accessories: [],
  }
}

function fromProduct(product: AdminProduct): ProductInput {
  return {
    name: product.name,
    sku: product.sku,
    brand: product.brand?.id ?? null,
    category: product.category?.id ?? null,
    subcategory: product.subcategory?.id ?? null,
    short_description: product.short_description,
    description: product.description,
    unit: product.unit,
    gst_rate: product.gst_rate,
    hsn_code: product.hsn_code,
    is_active: product.is_active,
    is_published: product.is_published,
    is_featured: product.is_featured,
    is_returnable: product.is_returnable,
    variants: product.variants.map((v) => ({
      id: v.id,
      sku: v.sku,
      name: v.name,
      mrp: v.mrp,
      price: v.price,
      is_default: v.is_default,
      is_active: v.is_active,
      price_tiers: (v.price_tiers ?? []).map((t) => ({ min_quantity: String(t.min_quantity), unit_price: t.unit_price })),
      options: (v.options ?? []).map((o) => ({ option_type: o.option_type, value: o.value })),
    })),
    specifications: product.specifications.map((s) => ({ name: s.name, value: s.value })),
    launch_date: product.launch_date ?? null,
    quick_answer: product.quick_answer ?? '',
    uses: product.uses ?? '',
    installation_steps: product.installation_steps ?? '',
    faqs: product.faqs ?? [],
    accessories: (product.accessories ?? []).map((a) => ({ product: a.id, note: a.note, kind: a.kind ?? 'accessory' })),
  }
}

/** Bulk-price checks the browser can point out at once; the server checks them all again. */
function tierProblems(variant: VariantInput, name: string): string[] {
  const found: string[] = []
  const rows = (variant.price_tiers ?? []).filter((t) => t.min_quantity !== '' || t.unit_price !== '')
  const sorted = [...rows].sort((a, b) => Number(a.min_quantity) - Number(b.min_quantity))
  let previous = Number(variant.price)
  const seen = new Set<number>()
  for (const tier of sorted) {
    const quantity = Number(tier.min_quantity)
    const price = Number(tier.unit_price)
    if (!Number.isInteger(quantity) || quantity < 2) {
      found.push(`${name}: bulk prices start from 2 units.`)
      continue
    }
    if (seen.has(quantity)) found.push(`${name}: two bulk prices start at ${quantity} units.`)
    seen.add(quantity)
    if (!(price > 0)) found.push(`${name}: enter the ${quantity}+ price.`)
    else if (price > Number(variant.mrp)) found.push(`${name}: the ${quantity}+ price is above the MRP.`)
    else if (price >= previous) found.push(`${name}: the ${quantity}+ price must be lower than the price for fewer units.`)
    previous = price
  }
  return found
}

/** Problems the browser can point out before asking the server (which checks everything again). */
function problems(form: ProductInput): string[] {
  const found: string[] = []
  if (!form.name.trim()) found.push('Give the product a name.')
  if (!form.sku.trim()) found.push('Give the product a SKU.')
  if (form.category === null) found.push('Choose a category.')
  const active = form.variants.filter((v) => v.is_active)
  if (active.length === 0) found.push('At least one variant must be active.')
  form.variants.forEach((variant, index) => {
    const name = variant.sku || `Variant ${index + 1}`
    if (!variant.sku.trim()) found.push(`Variant ${index + 1}: give it a SKU.`)
    if (!(Number(variant.price) > 0)) found.push(`${name}: enter the selling price.`)
    if (!(Number(variant.mrp) > 0)) found.push(`${name}: enter the MRP.`)
    if (Number(variant.price) > Number(variant.mrp)) found.push(`${name}: the selling price can’t be higher than the MRP.`)
    found.push(...tierProblems(variant, name))
  })
  const skus = form.variants.map((v) => v.sku.trim().toUpperCase()).filter(Boolean)
  if (new Set(skus).size !== skus.length) found.push('Two variants have the same SKU.')
  form.specifications.forEach((spec, index) => {
    if (!spec.name.trim() || !spec.value.trim()) found.push(`Specification ${index + 1}: fill in both name and value.`)
  })
  ;(form.faqs ?? []).forEach((faq, index) => {
    if (!faq.question.trim() || !faq.answer.trim()) found.push(`Question ${index + 1}: fill in both question and answer.`)
  })
  return found
}

/**
 * Phase 16 product-page content: quick answer, uses, steps, questions and linked accessories. Each block
 * appears on the product page only when filled in. Accessories are chosen from the shop's products.
 */
const RELATION_KINDS: [RelationKind, string][] = [
  ['accessory', 'Goes well with'],
  ['compatible', 'Compatible (verified)'],
  ['required', 'Required with it'],
  ['alternative', 'Alternative'],
  ['incompatible', 'Not compatible'],
]

function ProductPageContent({
  form,
  set,
  productId,
  names,
  onName,
}: {
  form: ProductInput
  set: <K extends keyof ProductInput>(key: K, value: ProductInput[K]) => void
  productId: number | null
  names: Record<number, string>
  onName: (id: number, name: string) => void
}) {
  const [term, setTerm] = useState('')
  const results = useProducts({ q: term.trim(), page_size: 8 }, term.trim().length >= 2)
  const faqs = form.faqs ?? []
  const accessories = form.accessories ?? []
  const chosen = new Set(accessories.map((a) => a.product))
  return (
    <Panel title="Product page">
      <div className="grid gap-3">
        <FormField
          id="quick_answer"
          label="Quick answer"
          value={form.quick_answer ?? ''}
          onChange={(e) => set('quick_answer', e.target.value)}
          maxLength={300}
          hint="One line shown under the name, e.g. “For RCC slabs, beams and columns”."
        />
        <TextAreaField id="uses" label="Recommended uses (one per line)" rows={3} value={form.uses ?? ''} onChange={(v) => set('uses', v)} />
        <TextAreaField
          id="installation_steps"
          label="How to install / use (one step per line)"
          rows={4}
          value={form.installation_steps ?? ''}
          onChange={(v) => set('installation_steps', v)}
        />
        <fieldset>
          <legend className="label">Questions & answers</legend>
          <ul className="space-y-2">
            {faqs.map((faq, index) => (
              <li key={index} className="grid gap-2 rounded-md bg-steel-50 p-2 sm:grid-cols-[1fr_1.5fr_auto]">
                <FormField
                  id={`faq-${index}-q`}
                  label={`Question ${index + 1}`}
                  value={faq.question}
                  onChange={(e) => set('faqs', faqs.map((f, i) => (i === index ? { ...f, question: e.target.value } : f)))}
                />
                <FormField
                  id={`faq-${index}-a`}
                  label={`Answer ${index + 1}`}
                  value={faq.answer}
                  onChange={(e) => set('faqs', faqs.map((f, i) => (i === index ? { ...f, answer: e.target.value } : f)))}
                />
                <button
                  type="button"
                  className="self-end text-sm font-semibold text-danger-600 hover:underline"
                  onClick={() => set('faqs', faqs.filter((_, i) => i !== index))}
                >
                  Remove <span className="sr-only">question {index + 1}</span>
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="btn-secondary mt-2 px-2.5 py-1.5" onClick={() => set('faqs', [...faqs, { question: '', answer: '' }])}>
            Add a question
          </button>
        </fieldset>
        <fieldset>
          <legend className="label">Linked products (accessories and compatibility)</legend>
          <p className="mb-2 text-xs text-ink-600">
            “Compatible”, “Required” and “Not compatible” are used by the compatibility checker; every change is recorded in the audit log.
          </p>
          {accessories.length > 0 && (
            <ul className="mb-2 space-y-2" aria-label="Chosen accessories">
              {accessories.map((accessory, index) => (
                <li key={accessory.product} className="flex flex-wrap items-end gap-2 rounded-md bg-steel-50 p-2">
                  <span className="min-w-40 flex-1 text-sm font-semibold">{names[accessory.product] ?? `Product ${accessory.product}`}</span>
                  <label className="text-sm">
                    <span className="label">Link type</span>
                    <select
                      className="input"
                      aria-label={`Link type for ${names[accessory.product] ?? `product ${accessory.product}`}`}
                      value={accessory.kind ?? 'accessory'}
                      onChange={(e) => set('accessories', accessories.map((a, i) => (i === index ? { ...a, kind: e.target.value as RelationKind } : a)))}
                    >
                      {RELATION_KINDS.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <FormField
                    id={`accessory-${accessory.product}-note`}
                    label="Why it goes with it"
                    value={accessory.note}
                    maxLength={120}
                    onChange={(e) => set('accessories', accessories.map((a, i) => (i === index ? { ...a, note: e.target.value } : a)))}
                  />
                  <button
                    type="button"
                    className="text-sm font-semibold text-danger-600 hover:underline"
                    onClick={() => set('accessories', accessories.filter((_, i) => i !== index))}
                  >
                    Remove <span className="sr-only">{names[accessory.product]}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <FormField
            id="accessory-search"
            label="Find a product to add"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            hint="Type at least 2 letters of the name or SKU."
          />
          {term.trim().length >= 2 && (
            <ul className="mt-1 divide-y divide-steel-100 rounded-md ring-1 ring-steel-200" aria-label="Matching products">
              {(results.data?.results ?? [])
                .filter((row) => row.id !== productId && !chosen.has(row.id))
                .map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      className="w-full px-3 py-2 text-left text-sm hover:bg-steel-50"
                      onClick={() => {
                        onName(row.id, row.name)
                        set('accessories', [...accessories, { product: row.id, note: '', kind: 'accessory' }])
                        setTerm('')
                      }}
                    >
                      Add {row.name} <span className="text-xs text-ink-600">({row.sku})</span>
                    </button>
                  </li>
                ))}
            </ul>
          )}
        </fieldset>
      </div>
    </Panel>
  )
}

function Images({ product }: { product: AdminProduct }) {
  const add = useAddProductImage(product.id)
  const change = useChangeProductImage(product.id)
  const toast = useToast()
  const input = useRef<HTMLInputElement>(null)
  const busy = add.isPending || change.isPending
  const fail = (error: unknown) => toast.show(errorMessage(error), { tone: 'error' })

  return (
    <Panel title="Pictures">
      {product.images.length === 0 ? (
        <p className="text-sm text-ink-600">No pictures yet. Products with pictures sell better.</p>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {product.images.map((image, index) => (
            <li key={image.id} className="rounded-md p-2 ring-1 ring-steel-200">
              <img src={image.image} alt={image.alt_text || `Picture ${index + 1} of ${product.name}`} className="aspect-square w-full rounded object-cover" />
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                {image.is_primary ? (
                  <Badge tone="good">Main picture</Badge>
                ) : (
                  <button
                    type="button"
                    className="font-semibold underline-offset-2 hover:underline"
                    disabled={busy}
                    onClick={() => change.mutate({ image: image.id, is_primary: true }, { onError: fail })}
                  >
                    Make main{' '}
<span className="sr-only">picture {index + 1}</span>
                  </button>
                )}
                <button
                  type="button"
                  className="ml-auto font-semibold text-danger-600 underline-offset-2 hover:underline"
                  disabled={busy}
                  onClick={() =>
                    change.mutate({ image: image.id, remove: true }, { onSuccess: () => toast.show('Picture removed.'), onError: fail })
                  }
                >
                  Remove{' '}
<span className="sr-only">picture {index + 1}</span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3">
        <label htmlFor="new-picture" className="label">
          Add a picture
        </label>
        <input
          ref={input}
          id="new-picture"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          disabled={busy}
          className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-ink-900 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (!file) return
            add.mutate(
              { file, alt_text: product.name },
              {
                onSuccess: () => toast.show('Picture added.'),
                onError: fail,
                onSettled: () => {
                  if (input.current) input.current.value = ''
                },
              },
            )
          }}
        />
        <p className="mt-1 text-xs text-ink-600">JPG, PNG or WebP, up to 12 pictures. {add.isPending && 'Uploading…'}</p>
      </div>
    </Panel>
  )
}

function ProductForm({ product }: { product: AdminProduct | null }) {
  const navigate = useNavigate()
  const toast = useToast()
  const categories = useCategories()
  const brands = useBrands({ page_size: 100, is_active: 'true' })
  const save = useSaveProduct(product?.id)
  const [form, setForm] = useState<ProductInput>(() => (product ? fromProduct(product) : blank()))
  const [shown, setShown] = useState<string[]>([])
  const [accessoryNames, setAccessoryNames] = useState<Record<number, string>>(() =>
    Object.fromEntries((product?.accessories ?? []).map((a) => [a.id, a.name])),
  )
  const set = <K extends keyof ProductInput>(key: K, value: ProductInput[K]) => setForm((current) => ({ ...current, [key]: value }))
  const flat = flattenCategories(categories.data ?? [])
  const subcategories = flat.find((entry) => entry.category.id === form.category)?.category.children ?? []
  const optionTypes = useOptionTypes()
  // Option types offered for this product: shop-wide ones, or ones whose categories include the
  // product's category, subcategory or anything above them. The server checks this again.
  const lineage = new Set<number>()
  for (const id of [form.category, form.subcategory]) {
    let entry = flat.find((e) => e.category.id === id)
    while (entry) {
      lineage.add(entry.category.id)
      const parent = entry.category.parent
      entry = parent ? flat.find((e) => e.category.id === parent) : undefined
    }
  }
  const usableOptions = (optionTypes.data ?? []).filter(
    (t) => t.is_active && (t.categories.length === 0 || t.categories.some((id) => lineage.has(id))),
  )

  function setVariant(index: number, changes: Partial<VariantInput>) {
    setForm((current) => ({
      ...current,
      variants: current.variants.map((variant, i) => {
        if (i === index) return { ...variant, ...changes }
        return changes.is_default ? { ...variant, is_default: false } : variant
      }),
    }))
  }

  function submit() {
    const found = problems(form)
    setShown(found)
    if (found.length > 0) return
    save.mutate(
      {
        ...form,
        name: form.name.trim(),
        sku: form.sku.trim(),
        variants: form.variants.map((v) => ({
          ...v,
          sku: v.sku.trim(),
          name: v.name.trim(),
          price_tiers: (v.price_tiers ?? []).filter((t) => t.min_quantity !== '' || t.unit_price !== ''),
          options: (v.options ?? []).filter((o) => o.value.trim() !== '').map((o) => ({ ...o, value: o.value.trim() })),
        })),
        specifications: form.specifications.map((s) => ({ name: s.name.trim(), value: s.value.trim() })),
        quick_answer: (form.quick_answer ?? '').trim(),
        faqs: (form.faqs ?? []).map((f) => ({ question: f.question.trim(), answer: f.answer.trim() })),
        accessories: (form.accessories ?? []).map((a) => ({ product: a.product, note: a.note.trim(), kind: a.kind ?? 'accessory' })),
      },
      {
        onSuccess: (saved) => {
          toast.show(product ? 'Product saved.' : 'Product added. You can add pictures now.')
          if (!product) void navigate(`/admin/products/${saved.id}`, { replace: true })
        },
      },
    )
  }

  return (
    <form
      noValidate
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <Panel title="Product">
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField id="name" label="Name" required value={form.name} onChange={(e) => set('name', e.target.value)} maxLength={200} />
          <FormField
            id="sku"
            label="Product SKU"
            required
            value={form.sku}
            onChange={(e) => set('sku', e.target.value)}
            maxLength={64}
            hint="The model code. Each variant has its own SKU below."
          />
          <SelectField
            id="category"
            label="Category"
            required
            value={form.category ?? ''}
            onChange={(e) => setForm((c) => ({ ...c, category: Number(e.target.value) || null, subcategory: null }))}
          >
            <option value="">Choose…</option>
            {flat
              .filter((entry) => entry.level < 3)
              .map(({ category, path }) => (
                <option key={category.id} value={category.id}>
                  {path}
                  {category.is_active ? '' : ' (inactive)'}
                </option>
              ))}
          </SelectField>
          <SelectField
            id="subcategory"
            label="Subcategory"
            value={form.subcategory ?? ''}
            disabled={subcategories.length === 0}
            onChange={(e) => set('subcategory', Number(e.target.value) || null)}
          >
            <option value="">{subcategories.length === 0 ? 'None available' : 'None'}</option>
            {subcategories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </SelectField>
          <SelectField id="brand" label="Brand" value={form.brand ?? ''} onChange={(e) => set('brand', Number(e.target.value) || null)}>
            <option value="">No brand</option>
            {(brands.data?.results ?? []).map((brand) => (
              <option key={brand.id} value={brand.id}>
                {brand.name}
              </option>
            ))}
          </SelectField>
          <SelectField id="unit" label="Sold by" value={form.unit} onChange={(e) => set('unit', e.target.value)}>
            {[...new Set([form.unit, ...UNITS])].map((unit) => (
              <option key={unit} value={unit}>
                {unit}
              </option>
            ))}
          </SelectField>
          <FormField
            id="gst_rate"
            label="GST %"
            inputMode="decimal"
            value={form.gst_rate}
            onChange={(e) => set('gst_rate', e.target.value)}
            hint="Prices include GST."
          />
          <FormField id="hsn_code" label="HSN code" value={form.hsn_code} onChange={(e) => set('hsn_code', e.target.value)} maxLength={10} />
          <FormField
            id="launch_date"
            label="Launch date"
            type="date"
            value={form.launch_date ?? ''}
            onChange={(e) => set('launch_date', e.target.value || null)}
            hint="Used by the automatic “New launches” list. Empty: the date it was added."
          />
          <FormField
            id="short_description"
            label="Short description"
            className="sm:col-span-2"
            value={form.short_description}
            onChange={(e) => set('short_description', e.target.value)}
            maxLength={255}
          />
          <div className="sm:col-span-2">
            <TextAreaField id="description" label="Description" rows={5} value={form.description} onChange={(v) => set('description', v)} />
          </div>
        </div>
      </Panel>

      <ProductPageContent
        form={form}
        set={set}
        productId={product?.id ?? null}
        names={accessoryNames}
        onName={(id, name) => setAccessoryNames((current) => ({ ...current, [id]: name }))}
      />

      <Panel
        title="Variants and prices"
        action={
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => set('variants', [...form.variants, { ...EMPTY_VARIANT }])}>
            Add variant
          </button>
        }
      >
        <ul className="space-y-3">
          {form.variants.map((variant, index) => (
            <li key={variant.id ?? `new-${index}`} className="rounded-md bg-steel-50 p-3">
              <fieldset>
                <legend className="mb-2 text-sm font-semibold">
                  Variant {index + 1}
                  {variant.is_default && <span className="ml-2 font-normal text-ink-600">shown first</span>}
                </legend>
                <div className="grid gap-3 sm:grid-cols-4">
                  <FormField id={`variant-${index}-sku`} label="SKU" required value={variant.sku} onChange={(e) => setVariant(index, { sku: e.target.value })} />
                  <FormField
                    id={`variant-${index}-name`}
                    label="Name"
                    placeholder="e.g. 5 kg, Blue"
                    value={variant.name}
                    onChange={(e) => setVariant(index, { name: e.target.value })}
                  />
                  <FormField
                    id={`variant-${index}-mrp`}
                    label="MRP (₹)"
                    required
                    inputMode="decimal"
                    value={variant.mrp}
                    onChange={(e) => setVariant(index, { mrp: e.target.value })}
                  />
                  <FormField
                    id={`variant-${index}-price`}
                    label="Selling price (₹)"
                    required
                    inputMode="decimal"
                    value={variant.price}
                    onChange={(e) => setVariant(index, { price: e.target.value })}
                  />
                </div>
                {usableOptions.length > 0 && (
                  <div className="mt-3 grid gap-3 sm:grid-cols-4">
                    {usableOptions.map((type) => {
                      const current = variant.options?.find((o) => o.option_type === type.id)?.value ?? ''
                      return (
                        <FormField
                          key={type.id}
                          id={`variant-${index}-option-${type.id}`}
                          label={`${type.name}${type.unit ? ` (${type.unit})` : ''}`}
                          value={current}
                          list={`option-values-${type.id}`}
                          placeholder={type.values[0]?.value ?? ''}
                          onChange={(e) =>
                            setVariant(index, {
                              options: [
                                ...(variant.options ?? []).filter((o) => o.option_type !== type.id),
                                { option_type: type.id, value: e.target.value },
                              ],
                            })
                          }
                        />
                      )
                    })}
                  </div>
                )}
                <fieldset className="mt-3">
                  <legend className="text-sm font-medium">Bulk prices</legend>
                  <p className="text-xs text-ink-600">
                    From a quantity, a lower price per unit. Each must be lower than the price for fewer units and not above the MRP.
                  </p>
                  {(variant.price_tiers ?? []).map((tier, tierIndex) => (
                    <div key={tierIndex} className="mt-2 flex flex-wrap items-end gap-2">
                      <FormField
                        id={`variant-${index}-tier-${tierIndex}-qty`}
                        label="From units"
                        type="number"
                        min={2}
                        className="w-28"
                        value={tier.min_quantity}
                        onChange={(e) =>
                          setVariant(index, {
                            price_tiers: (variant.price_tiers ?? []).map((t, i) => (i === tierIndex ? { ...t, min_quantity: e.target.value } : t)),
                          })
                        }
                      />
                      <FormField
                        id={`variant-${index}-tier-${tierIndex}-price`}
                        label="Price per unit (₹)"
                        inputMode="decimal"
                        className="w-36"
                        value={tier.unit_price}
                        onChange={(e) =>
                          setVariant(index, {
                            price_tiers: (variant.price_tiers ?? []).map((t, i) => (i === tierIndex ? { ...t, unit_price: e.target.value } : t)),
                          })
                        }
                      />
                      <button
                        type="button"
                        className="btn-secondary px-2.5 py-1.5"
                        onClick={() => setVariant(index, { price_tiers: (variant.price_tiers ?? []).filter((_, i) => i !== tierIndex) })}
                      >
                        Remove{' '}<span className="sr-only">bulk price {tierIndex + 1} of variant {index + 1}</span>
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    className="mt-2 text-sm font-semibold text-amber-700 underline-offset-2 hover:underline"
                    onClick={() => setVariant(index, { price_tiers: [...(variant.price_tiers ?? []), { min_quantity: '', unit_price: '' }] })}
                  >
                    Add bulk price{' '}<span className="sr-only">to variant {index + 1}</span>
                  </button>
                </fieldset>
                <div className="mt-2 flex flex-wrap items-center gap-4">
                  <CheckField
                    id={`variant-${index}-default`}
                    label="Show first"
                    checked={variant.is_default}
                    onChange={(checked) => setVariant(index, { is_default: checked })}
                  />
                  <CheckField
                    id={`variant-${index}-active`}
                    label="On sale"
                    checked={variant.is_active}
                    onChange={(checked) => setVariant(index, { is_active: checked })}
                  />
                  {variant.id === undefined && form.variants.length > 1 && (
                    <button
                      type="button"
                      className="ml-auto text-sm font-semibold text-danger-600 underline-offset-2 hover:underline"
                      onClick={() => set('variants', form.variants.filter((_, i) => i !== index))}
                    >
                      Remove{' '}
<span className="sr-only">variant {index + 1}</span>
                    </button>
                  )}
                </div>
              </fieldset>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-ink-600">
          A saved variant can be taken off sale but not removed, because orders refer to it. Stock is managed under Inventory.
          Options come from Product options; a new value typed here is added to that option.
        </p>
        {usableOptions.map((type) => (
          <datalist key={type.id} id={`option-values-${type.id}`}>
            {type.values.map((value) => (
              <option key={value.id} value={value.value} />
            ))}
          </datalist>
        ))}
      </Panel>

      <Panel
        title="Specifications"
        action={
          <button
            type="button"
            className="btn-secondary px-2.5 py-1.5"
            onClick={() => set('specifications', [...form.specifications, { name: '', value: '' }])}
          >
            Add specification
          </button>
        }
      >
        {form.specifications.length === 0 ? (
          <p className="text-sm text-ink-600">None yet, e.g. Power: 850 W, Material: steel.</p>
        ) : (
          <ul className="space-y-2">
            {form.specifications.map((spec, index) => (
              <li key={index} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
                <FormField
                  id={`spec-${index}-name`}
                  label={`Specification ${index + 1}`}
                  value={spec.name}
                  maxLength={80}
                  onChange={(e) =>
                    set('specifications', form.specifications.map((s, i) => (i === index ? { ...s, name: e.target.value } : s)))
                  }
                />
                <FormField
                  id={`spec-${index}-value`}
                  label="Value"
                  value={spec.value}
                  maxLength={200}
                  onChange={(e) =>
                    set('specifications', form.specifications.map((s, i) => (i === index ? { ...s, value: e.target.value } : s)))
                  }
                />
                <button
                  type="button"
                  className="btn-secondary px-2.5"
                  onClick={() => set('specifications', form.specifications.filter((_, i) => i !== index))}
                >
                  Remove{' '}
<span className="sr-only">specification {index + 1}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Selling">
        <div className="grid gap-3 sm:grid-cols-2">
          <CheckField
            id="is_published"
            label="Published"
            hint="Customers can see and buy it."
            checked={form.is_published}
            onChange={(checked) => set('is_published', checked)}
          />
          <CheckField
            id="is_returnable"
            label="Can be returned"
            hint="Turn off for cut-to-size, mixed paint and similar goods."
            checked={form.is_returnable}
            onChange={(checked) => set('is_returnable', checked)}
          />
          <CheckField
            id="is_featured"
            label="Featured"
            hint="Shown in the featured rows of the shop."
            checked={form.is_featured}
            onChange={(checked) => set('is_featured', checked)}
          />
          <CheckField
            id="is_active"
            label="Active"
            hint="Inactive products are hidden everywhere, whatever else is set."
            checked={form.is_active}
            onChange={(checked) => set('is_active', checked)}
          />
        </div>
      </Panel>

      {(shown.length > 0 || save.isError) && (
        <div role="alert" className="rounded-md bg-danger-600/10 px-4 py-3 text-sm text-danger-600">
          {shown.length > 0 ? (
            <ul className="list-disc pl-4">
              {shown.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          ) : (
            errorMessage(save.error)
          )}
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Link to="/admin/products" className="btn-secondary">
          Cancel
        </Link>
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : product ? 'Save product' : 'Add product'}
        </button>
      </div>
    </form>
  )
}

function ProductSummary({ product }: { product: AdminProduct }) {
  return (
    <div className="space-y-5">
      <Panel title="Variants">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Variants of {product.name}</caption>
          <thead className="text-xs uppercase text-ink-600">
            <tr>
              <th scope="col" className="py-1.5 pr-3">
                Variant
              </th>
              {['MRP', 'Price', 'In stock', 'Reserved'].map((name) => (
                <th key={name} scope="col" className="py-1.5 pl-3 text-right">
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {product.variants.map((variant) => (
              <tr key={variant.id} className="border-t border-steel-100">
                <th scope="row" className="py-1.5 pr-3 font-medium">
                  {variant.name || product.name}
                  <span className="block text-xs font-normal text-ink-600">
                    SKU {variant.sku}
                    {!variant.is_active && ' · not on sale'}
                  </span>
                </th>
                <td className="py-1.5 pl-3 text-right">{formatPrice(variant.mrp)}</td>
                <td className="py-1.5 pl-3 text-right">{formatPrice(variant.price)}</td>
                <td className="py-1.5 pl-3 text-right">{variant.stock_available}</td>
                <td className="py-1.5 pl-3 text-right">{variant.stock_reserved}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Link to={`/admin/inventory?q=${encodeURIComponent(product.sku)}`} className="mt-3 inline-block text-sm font-semibold text-amber-700 hover:underline">
          Open inventory
        </Link>
      </Panel>
      {product.specifications.length > 0 && (
        <Panel title="Specifications">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            {product.specifications.map((spec) => (
              <div key={spec.name} className="contents">
                <dt className="text-ink-600">{spec.name}</dt>
                <dd className="font-medium">{spec.value}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      )}
    </div>
  )
}

export function AdminProductPage() {
  const { id } = useParams()
  const creating = id === 'new'
  const session = useSession()
  const query = useProduct(creating ? undefined : id)
  usePageMeta(creating ? 'Add product' : (query.data?.name ?? 'Product'))
  const crumbs = [{ label: 'Products', to: '/admin/products' }]

  if (creating) {
    if (!session.can.manage_catalog) return <NotAllowed what="Products" />
    return (
      <>
        <PageHeader title="Add product" crumbs={crumbs} />
        <ProductForm product={null} />
      </>
    )
  }
  if (query.isPending) return <PageSpinner label="Loading the product…" />
  if (isNotFound(query.error)) return <NotFoundPage />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn’t load the product" />
  const product = query.data
  const editable = session.can.manage_catalog && !product.is_deleted

  return (
    <>
      <PageHeader
        title={product.name}
        crumbs={crumbs}
        description={`SKU ${product.sku} · last changed ${dateTime(product.updated_at)}`}
        actions={
          <>
            <StatusBadge status={product.state} text={product.state === 'live' ? 'On sale' : undefined} />
            {product.state === 'live' && (
              <Link to={`/p/${product.slug}`} className="btn-secondary">
                View in the shop
              </Link>
            )}
          </>
        }
      />
      {product.is_deleted && (
        <p className="mb-4 rounded-md bg-amber-100 px-3 py-2 text-sm">This product is deleted. Restore it from the product list to change it.</p>
      )}
      {editable ? (
        <div className="space-y-5">
          <Images product={product} />
          <ProductForm key={product.updated_at} product={product} />
        </div>
      ) : (
        <ProductSummary product={product} />
      )}
    </>
  )
}

// --- Categories ----------------------------------------------------------------------------------

type CategoryDraft = { id?: number; name: string; parent: number | null; description: string; sort_order: string; is_active: boolean }

export function AdminCategoriesPage() {
  usePageMeta('Categories')
  const session = useSession()
  const categories = useCategories()
  const { save, remove } = useCategoryCrud()
  const toast = useToast()
  const [draft, setDraft] = useState<CategoryDraft | null>(null)
  const [deleting, setDeleting] = useState<AdminCategory | null>(null)
  const canEdit = session.can.manage_catalog

  const edit = (category: AdminCategory) =>
    setDraft({
      id: category.id,
      name: category.name,
      parent: category.parent,
      description: category.description,
      sort_order: String(category.sort_order),
      is_active: category.is_active,
    })
  const create = (parent: number | null) => {
    save.reset()
    setDraft({ name: '', parent, description: '', sort_order: '0', is_active: true })
  }

  function row(category: AdminCategory, depth = 1) {
    const child = depth > 1
    return (
      <li key={category.id} className={`flex flex-wrap items-center gap-2 py-2.5 ${depth === 2 ? 'pl-6' : depth === 3 ? 'pl-12' : ''}`}>
        <span className="min-w-0 flex-1">
          <span className={child ? 'text-sm' : 'font-semibold'}>{category.name}</span>
          <span className="ml-2 text-xs text-ink-600">
            {category.product_count} {category.product_count === 1 ? 'product' : 'products'} · position {category.sort_order}
          </span>
        </span>
        {!category.is_active && <Badge>Inactive</Badge>}
        {canEdit && (
          <>
            {depth < 3 && (
              <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => create(category.id)}>
                {depth === 1 ? 'Add category' : 'Add subcategory'}{' '}
<span className="sr-only">to {category.name}</span>
              </button>
            )}
            <button
              type="button"
              className="btn-secondary px-2.5 py-1.5"
              onClick={() => {
                save.reset()
                edit(category)
              }}
            >
              Edit{' '}
<span className="sr-only">{category.name}</span>
            </button>
            <button
              type="button"
              className="btn-secondary px-2.5 py-1.5"
              disabled={save.isPending}
              onClick={() =>
                save.mutate(
                  { id: category.id, data: { is_active: !category.is_active } },
                  {
                    onSuccess: () => toast.show(`${category.name} ${category.is_active ? 'deactivated' : 'activated'}.`),
                    onError: (error) => toast.show(errorMessage(error), { tone: 'error' }),
                  },
                )
              }
            >
              {category.is_active ? 'Deactivate' : 'Activate'}
              {' '}
<span className="sr-only">{category.name}</span>
            </button>
            <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => setDeleting(category)}>
              Delete{' '}
<span className="sr-only">{category.name}</span>
            </button>
          </>
        )}
      </li>
    )
  }

  return (
    <>
      <PageHeader
        title="Categories"
        description="Departments, categories and subcategories (up to three levels), in the order customers see them (lowest position first)."
        actions={
          canEdit && (
            <button type="button" className="btn-primary" onClick={() => create(null)}>
              Add department
            </button>
          )
        }
      />
      {categories.isPending ? (
        <PageSpinner label="Loading categories…" />
      ) : categories.isError ? (
        <ErrorState error={categories.error} onRetry={() => void categories.refetch()} title="Couldn’t load categories" />
      ) : categories.data.length === 0 ? (
        <Panel>
          <p className="py-8 text-center text-sm text-ink-600">No categories yet. Add the first one to organise your products.</p>
        </Panel>
      ) : (
        <Panel>
          <ul className="divide-y divide-steel-100">
            {categories.data.map((category) => (
              <li key={category.id}>
                <ul className="divide-y divide-steel-100">
                  {row(category)}
                  {category.children.map((child) => (
                    <li key={`branch-${child.id}`}>
                      <ul className="divide-y divide-steel-100">
                        {row(child, 2)}
                        {(child.children ?? []).map((grandchild) => row(grandchild, 3))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <FormDialog
        open={draft !== null}
        title={draft?.id ? 'Edit category' : draft?.parent ? 'Add category inside' : 'Add department'}
        busy={save.isPending}
        error={save.error}
        onClose={() => setDraft(null)}
        onSubmit={() => {
          if (!draft) return
          save.mutate(
            {
              id: draft.id,
              data: {
                name: draft.name.trim(),
                parent: draft.parent,
                description: draft.description,
                sort_order: Number(draft.sort_order) || 0,
                is_active: draft.is_active,
              },
            },
            {
              onSuccess: () => {
                toast.show('Category saved.')
                setDraft(null)
              },
            },
          )
        }}
      >
        {draft && (
          <>
            <FormField id="category-name" label="Name" required maxLength={120} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <SelectField
              id="category-parent"
              label="Inside"
              value={draft.parent ?? ''}
              onChange={(e) => setDraft({ ...draft, parent: Number(e.target.value) || null })}
              hint="Leave empty for a department (top level). At most three levels."
            >
              <option value="">— department (top level) —</option>
              {flattenCategories(categories.data ?? [])
                .filter((entry) => entry.level < 3 && entry.category.id !== draft.id)
                .map(({ category, path }) => (
                  <option key={category.id} value={category.id}>
                    {path}
                  </option>
                ))}
            </SelectField>
            <FormField
              id="category-order"
              label="Position"
              type="number"
              min={0}
              value={draft.sort_order}
              onChange={(e) => setDraft({ ...draft, sort_order: e.target.value })}
              hint="Lower numbers come first."
            />
            <TextAreaField id="category-description" label="Description" rows={2} value={draft.description} onChange={(v) => setDraft({ ...draft, description: v })} />
            <CheckField id="category-active" label="Active" hint="Inactive categories are hidden from customers." checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} />
          </>
        )}
      </FormDialog>

      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.name ?? ''}?`}
        confirmLabel="Delete category"
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
        <p>A category can only be deleted when it has no products and nothing inside it. Otherwise, deactivate it.</p>
      </ConfirmDialog>
    </>
  )
}

// --- Brands --------------------------------------------------------------------------------------

export function AdminBrandsPage() {
  usePageMeta('Brands')
  const session = useSession()
  const list = useListParams()
  const brands = useBrands({ page: list.page, q: list.get('q'), is_active: list.get('is_active') })
  const { save, remove } = useBrandCrud()
  const toast = useToast()
  const [draft, setDraft] = useState<{ id?: number; name: string; is_active: boolean } | null>(null)
  const [deleting, setDeleting] = useState<AdminBrand | null>(null)
  const canEdit = session.can.manage_catalog

  const columns: Column<AdminBrand>[] = [
    { header: 'Brand', cell: (brand) => <span className="font-semibold">{brand.name}</span> },
    { header: 'Products', numeric: true, cell: (brand) => brand.product_count },
    { header: 'Status', cell: (brand) => <StatusBadge status={brand.is_active ? 'live' : 'inactive'} text={brand.is_active ? 'Active' : 'Inactive'} /> },
    ...(canEdit
      ? [
          {
            header: 'Actions',
            cell: (brand: AdminBrand) => (
              <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
                <button
                  type="button"
                  className="btn-secondary px-2.5 py-1.5"
                  onClick={() => {
                    save.reset()
                    setDraft({ id: brand.id, name: brand.name, is_active: brand.is_active })
                  }}
                >
                  Edit{' '}
<span className="sr-only">{brand.name}</span>
                </button>
                <button
                  type="button"
                  className="btn-secondary px-2.5 py-1.5"
                  disabled={save.isPending}
                  onClick={() =>
                    save.mutate(
                      { id: brand.id, data: { is_active: !brand.is_active } },
                      {
                        onSuccess: () => toast.show(`${brand.name} ${brand.is_active ? 'deactivated' : 'activated'}.`),
                        onError: (error) => toast.show(errorMessage(error), { tone: 'error' }),
                      },
                    )
                  }
                >
                  {brand.is_active ? 'Deactivate' : 'Activate'}
                  {' '}
<span className="sr-only">{brand.name}</span>
                </button>
                <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => setDeleting(brand)}>
                  Delete{' '}
<span className="sr-only">{brand.name}</span>
                </button>
              </span>
            ),
          } satisfies Column<AdminBrand>,
        ]
      : []),
  ]

  return (
    <>
      <PageHeader
        title="Brands"
        actions={
          canEdit && (
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                save.reset()
                setDraft({ name: '', is_active: true })
              }}
            >
              Add brand
            </button>
          )
        }
      />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search brands" />
        <FilterSelect list={list} name="is_active" label="Status" options={[['true', 'Active'], ['false', 'Inactive']]} />
      </FilterBar>
      <ListView query={brands} list={list} caption="Brands" columns={columns} rowKey={(brand) => brand.id} empty="No brands yet" />

      <FormDialog
        open={draft !== null}
        title={draft?.id ? 'Edit brand' : 'Add brand'}
        busy={save.isPending}
        error={save.error}
        onClose={() => setDraft(null)}
        onSubmit={() => {
          if (!draft) return
          save.mutate(
            { id: draft.id, data: { name: draft.name.trim(), is_active: draft.is_active } },
            {
              onSuccess: () => {
                toast.show('Brand saved.')
                setDraft(null)
              },
            },
          )
        }}
      >
        {draft && (
          <>
            <FormField id="brand-name" label="Name" required maxLength={120} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <CheckField id="brand-active" label="Active" checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} />
          </>
        )}
      </FormDialog>
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.name ?? ''}?`}
        confirmLabel="Delete brand"
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
        <p>A brand with products can’t be deleted; deactivate it instead.</p>
      </ConfirmDialog>
    </>
  )
}
