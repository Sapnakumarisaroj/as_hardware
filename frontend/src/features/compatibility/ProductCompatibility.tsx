import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { useProduct, useProducts } from '@/features/catalog/api'
import { ProductCard } from '@/features/catalog/components/ProductCard'
import type { ProductDetail, ProductSummary } from '@/features/catalog/types'
import { ApiError } from '@/lib/api/errors'

import { useCompatibilityCheck, useProductCompatibility } from './api'
import { CompatibilityResultCard } from './components'
import type { AccessoryRow } from './types'

/**
 * "Compatibility" on the product page: this product (and variant) against another one the customer picks.
 * The verdict comes from the server (listing facts + the shop's links); nothing is decided here.
 */
export function CompatibilityChecker({ product, variantId }: { product: ProductDetail; variantId: number }) {
  const [term, setTerm] = useState('')
  const [other, setOther] = useState<ProductSummary | null>(null)
  const [otherVariant, setOtherVariant] = useState<number | null>(null)
  const [ownVariant, setOwnVariant] = useState<number>(variantId)
  const results = useProducts({ q: term.trim(), page_size: '6' }, { enabled: term.trim().length >= 2 && !other })
  const detail = useProduct(other?.slug ?? '')
  const check = useCompatibilityCheck()
  const variants = product.variants ?? []
  const otherVariants = other && detail.data ? detail.data.variants : []

  function run() {
    if (!other) return
    check.mutate({ product_a: product.id, variant_a: ownVariant, product_b: other.id, variant_b: otherVariant })
  }

  return (
    <section aria-labelledby="compatibility-heading" className="rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200">
      <h2 id="compatibility-heading" className="text-lg font-bold">
        Compatibility
      </h2>
      <p className="mt-1 text-sm text-ink-600">Check whether this works with another product, using both products’ listed specifications.</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <p className="label">This product</p>
          <p className="text-sm font-medium">{product.name}</p>
          {variants.length > 1 && (
            <select aria-label="This product's variant" className="input mt-1" value={ownVariant} onChange={(e) => setOwnVariant(Number(e.target.value))}>
              {variants.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name || v.sku}
                </option>
              ))}
            </select>
          )}
        </div>
        <div>
          {other ? (
            <>
              <p className="label">Check with</p>
              <p className="flex items-center justify-between gap-2 text-sm font-medium">
                {other.name}
                <button
                  type="button"
                  className="text-xs text-ink-600 underline"
                  onClick={() => {
                    setOther(null)
                    setOtherVariant(null)
                    check.reset()
                  }}
                >
                  Change
                </button>
              </p>
              {otherVariants.length > 1 && (
                <select
                  aria-label="Other product's variant"
                  className="input mt-1"
                  value={otherVariant ?? ''}
                  onChange={(e) => setOtherVariant(e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">Any size / variant</option>
                  {otherVariants.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name || v.sku}
                    </option>
                  ))}
                </select>
              )}
            </>
          ) : (
            <>
              <label htmlFor="compatibility-search" className="label">
                Check with another product
              </label>
              <input
                id="compatibility-search"
                className="input"
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder="e.g. drill bit, wall plug, elbow"
              />
              {term.trim().length >= 2 && (
                <ul className="mt-1 divide-y divide-steel-100 rounded-md ring-1 ring-steel-200" aria-label="Products to check with">
                  {(results.data?.results ?? [])
                    .filter((row) => row.id !== product.id)
                    .map((row) => (
                      <li key={row.id}>
                        <button
                          type="button"
                          className="w-full px-3 py-2 text-left text-sm hover:bg-steel-50"
                          onClick={() => {
                            setOther(row)
                            setTerm('')
                          }}
                        >
                          {row.name}
                        </button>
                      </li>
                    ))}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="button" className="btn-primary" disabled={!other || check.isPending} onClick={run}>
          {check.isPending ? 'Checking…' : 'Check compatibility'}
        </button>
        <Link
          to={`/ai-assistant?product=${product.id}&ask=${encodeURIComponent(`What works with the ${product.name}?`)}`}
          className="text-sm font-semibold text-amber-700 hover:underline"
        >
          Ask the assistant
        </Link>
      </div>
      {check.isError && (
        <p role="alert" className="mt-2 text-sm text-danger-600">
          {check.error instanceof ApiError ? check.error.message : 'Could not check. Please try again.'}
        </p>
      )}
      {check.data && (
        <div className="mt-3">
          <CompatibilityResultCard result={check.data} />
        </div>
      )}
    </section>
  )
}

const GROUPS: { key: keyof NonNullable<ReturnType<typeof useProductCompatibility>['data']>['groups']; title: string }[] = [
  { key: 'required', title: 'Needed with it' },
  { key: 'compatible', title: 'Works with it' },
  { key: 'accessories', title: 'Goes well with' },
  { key: 'alternatives', title: 'Alternatives' },
]

/** Recommended accessories in groups; the shop's own Phase 16 list is shown while they load or if they fail. */
export function AccessoryGroups({ productId, variantId, fallback }: { productId: number; variantId: number | null; fallback: ReactNode }) {
  const data = useProductCompatibility(productId, variantId)
  if (!data.data) return <>{fallback}</>
  const groups = GROUPS.filter((g) => data.data.groups[g.key].length > 0)
  if (!groups.length) return <>{fallback}</>
  return (
    <section aria-labelledby="accessories-heading" className="py-6">
      <h2 id="accessories-heading" className="mb-2 text-xl font-bold text-ink-950">
        Recommended accessories
      </h2>
      {groups.map((group) => (
        <div key={group.key} className="mb-4">
          <h3 className="mb-2 text-sm font-semibold text-ink-700">{group.title}</h3>
          <ul role="list" aria-label={group.title} className="scrollbar-none -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2 sm:gap-4">
            {data.data.groups[group.key].map((row: AccessoryRow) => (
              <li key={row.product_id} className="flex w-44 shrink-0 snap-start flex-col sm:w-56">
                {(row.note || row.reason) && <p className="mb-1 line-clamp-2 text-xs font-medium text-ink-600">{row.note || row.reason}</p>}
                <div className="w-full flex-1">
                  <ProductCard product={row.product} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}
