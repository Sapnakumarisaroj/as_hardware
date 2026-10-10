import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { EmptyState, ErrorState, PageSpinner } from '@/components/feedback'
import { CloseIcon, CompareIcon } from '@/components/icons'
import { AddToCartButton } from '@/features/cart/AddToCartButton'
import { PriceBlock, StockLabel } from '@/features/catalog/components/badges'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { useCompare, type CompareProduct, type CompareRow } from '@/features/compare/api'
import { clearCompare, COMPARE_MAX, removeFromCompare, useCompareItems } from '@/features/compare/store'
import { formatPercent } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const MISSING = '—'

/** The fixed facts every product has, as rows like the specifications (so "only differences" works for them too). */
function summaryRows(products: CompareProduct[]): CompareRow[] {
  const row = (key: string, name: string, values: string[]): CompareRow => ({
    key,
    name,
    values,
    differs: new Set(values.map((v) => v.trim().toLowerCase())).size > 1,
  })
  return [
    row('brand', 'Brand', products.map((p) => p.brand?.name ?? MISSING)),
    row('department', 'Department', products.map((p) => p.department?.name ?? MISSING)),
    row('category', 'Category', products.map((p) => p.category.name)),
    row('unit', 'Sold per', products.map((p) => p.unit_label || p.unit || MISSING)),
    row('discount', 'Discount', products.map((p) => (formatPercent(p.discount_percent) ? `${formatPercent(p.discount_percent)} off` : MISSING))),
    row(
      'rating',
      'Rating',
      products.map((p) => (p.rating_count && p.rating_avg ? `${Number(p.rating_avg).toFixed(1)} (${p.rating_count})` : 'No reviews yet')),
    ),
  ]
}

const CELL = 'min-w-[9.5rem] max-w-[16rem] border-b border-steel-100 px-3 py-2.5 align-top text-sm sm:min-w-[11rem]'
const HEAD = 'sticky left-0 z-[1] w-28 min-w-28 border-b border-r border-steel-100 bg-steel-50 px-3 py-2.5 text-left align-top text-xs font-semibold text-ink-700 sm:w-40 sm:min-w-40 sm:text-sm'

function ProductColumn({ product }: { product: CompareProduct }) {
  const outOfStock = product.stock_status === 'out_of_stock'
  const href = `/p/${product.slug}`
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="relative">
        <Link to={href} tabIndex={-1} aria-hidden className="block overflow-hidden rounded-xl bg-steel-50">
          <ProductImage src={product.image} alt={product.image_alt} className="aspect-square w-full bg-transparent p-2" />
        </Link>
        <button
          type="button"
          onClick={() => removeFromCompare(product.slug)}
          aria-label={`Remove ${product.name} from compare`}
          className="absolute right-1 top-1 grid size-9 place-items-center rounded-full bg-white/95 text-ink-800 shadow-sm ring-1 ring-steel-200 after:absolute after:-inset-1 after:content-[''] hover:text-danger-600"
        >
          <CloseIcon className="size-4" />
        </button>
      </div>
      {product.brand && <p className="truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-600">{product.brand.name}</p>}
      <h2 className="line-clamp-3 text-sm font-semibold leading-5 text-ink-950">
        <Link to={href} className="hover:text-amber-700">
          {product.name}
        </Link>
      </h2>
      {product.variant_name && <p className="truncate text-xs text-ink-600">{product.variant_name}</p>}
      <PriceBlock price={product.price} mrp={product.mrp} discountPercent={product.discount_percent} />
      <StockLabel status={product.stock_status} compact />
      <div className="mt-auto pt-1">
        {outOfStock || !product.default_variant_id ? (
          <button type="button" disabled className="btn-secondary min-h-11 w-full">
            Out of stock
          </button>
        ) : (
          <AddToCartButton
            variantId={product.default_variant_id}
            productName={product.name}
            label="Add to cart"
            className="btn-primary min-h-11 w-full px-2"
          />
        )}
      </div>
    </div>
  )
}

function Row({ row }: { row: CompareRow }) {
  return (
    <tr data-differs={row.differs} className={row.differs ? 'bg-amber-50/40' : undefined}>
      <th scope="row" className={HEAD}>
        {row.name}
      </th>
      {row.values.map((value, i) => (
        <td key={i} className={`${CELL} ${value === MISSING ? 'text-steel-400' : 'text-ink-900'}`}>
          {value}
        </td>
      ))}
    </tr>
  )
}

/**
 * Side-by-side comparison of up to four products picked in this browser. Everything shown comes from
 * GET /products/compare/: live prices of the default variant, stock, ratings and the products' own
 * specifications ("—" where a product doesn't list one). On phones the table scrolls sideways with
 * the row names kept in view.
 */
export function ComparePage() {
  usePageMeta('Compare products')
  const items = useCompareItems()
  const slugs = items.map((i) => i.slug)
  const query = useCompare(slugs)
  const [onlyDiff, setOnlyDiff] = useState(false)
  const [dropped, setDropped] = useState<string[]>([])
  const missing = query.data?.missing

  // Products no longer on sale drop out of the list, and the shopper is told which (state set
  // while rendering, the store updated in an effect).
  const missingNames = missing?.length ? items.filter((i) => missing.includes(i.slug)).map((i) => i.name) : []
  if (missingNames.length && missingNames.join('|') !== dropped.join('|')) setDropped(missingNames)
  useEffect(() => {
    missing?.forEach(removeFromCompare)
  }, [missing])

  const breadcrumb = (
    <div className="border-b border-steel-200 bg-white">
      <div className="container-page py-3">
        <Breadcrumbs items={[{ label: 'Compare products' }]} />
      </div>
    </div>
  )

  if (!items.length) {
    return (
      <>
        {breadcrumb}
        <div className="container-page py-8">
          {dropped.length > 0 && <DroppedNote names={dropped} />}
          <EmptyState
            title="Nothing to compare yet"
            action={
              <Link to="/products" className="btn-primary">
                Browse products
              </Link>
            }
          >
            Tap the compare button on up to {COMPARE_MAX} products to see their prices and specifications side by side.
          </EmptyState>
        </div>
      </>
    )
  }

  if (query.isPending) return <PageSpinner label="Loading comparison…" />
  if (query.isError) {
    return (
      <div className="container-page py-8">
        <ErrorState error={query.error} onRetry={() => query.refetch()} title="Couldn’t load the comparison" />
      </div>
    )
  }

  const { products, specifications, mixed_departments: mixed } = query.data
  const rows = [...summaryRows(products), ...specifications]
  const shown = onlyDiff ? rows.filter((r) => r.differs) : rows
  const hiddenCount = rows.length - shown.length

  return (
    <>
      {breadcrumb}
      <div className="container-page py-6 sm:py-8">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">Side by side</p>
            <h1 className="section-title flex items-center gap-2">
              <CompareIcon className="size-6 text-amber-700" />
              Compare products
            </h1>
            <p className="mt-1 text-sm text-ink-600">
              {products.length} of {COMPARE_MAX} products
              {products.length < COMPARE_MAX && (
                <>
                  {' · '}
                  <Link to="/products" className="font-semibold text-amber-700 hover:underline">
                    Add more
                  </Link>
                </>
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg bg-white px-3 text-sm font-semibold text-ink-900 ring-1 ring-steel-200">
              <input
                type="checkbox"
                checked={onlyDiff}
                onChange={(e) => setOnlyDiff(e.target.checked)}
                className="size-4 accent-amber-500"
              />
              Show only differences
            </label>
            <button type="button" onClick={clearCompare} className="btn-secondary min-h-11">
              Clear all
            </button>
          </div>
        </div>

        {dropped.length > 0 && <DroppedNote names={dropped} />}
        {mixed && (
          <p className="mb-4 rounded-xl bg-steel-100 px-4 py-3 text-sm text-ink-800" data-testid="mixed-departments">
            These products are from different departments, so many specifications won’t line up.
          </p>
        )}
        {products.length === 1 && (
          <p className="mb-4 rounded-xl bg-amber-50 px-4 py-3 text-sm text-ink-800 ring-1 ring-amber-100">
            Add at least one more product to compare.
          </p>
        )}

        <div className="card overflow-x-auto overscroll-x-contain" tabIndex={0} aria-label="Comparison table, scrolls sideways">
          <table className="w-full border-separate border-spacing-0">
            <caption className="sr-only">Product comparison</caption>
            <thead>
              <tr>
                <td className={`${HEAD} align-bottom`}>
                  <span className="sr-only">Product</span>
                </td>
                {products.map((product) => (
                  <th key={product.slug} scope="col" className={`${CELL} text-left font-normal`}>
                    <ProductColumn product={product} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <Row key={row.key} row={row} />
              ))}
            </tbody>
          </table>
        </div>
        {onlyDiff && (
          <p className="mt-3 text-xs text-ink-600">
            {hiddenCount ? `${hiddenCount} matching ${hiddenCount === 1 ? 'row is' : 'rows are'} hidden.` : 'Every row differs.'}
          </p>
        )}
        {!specifications.length && (
          <p className="mt-3 text-sm text-ink-600">These products don’t list any specifications yet.</p>
        )}
      </div>
    </>
  )
}

function DroppedNote({ names }: { names: string[] }) {
  return (
    <p role="status" className="mb-4 rounded-xl bg-steel-100 px-4 py-3 text-sm text-ink-800">
      No longer available, removed from compare: {names.join(', ')}
    </p>
  )
}
