import { useState } from 'react'
import { Link } from 'react-router'

import { useToast } from '@/components/toast'
import { useAddToCart, useRemoveCartItem } from '@/features/cart/api'
import { ProductCard } from '@/features/catalog/components/ProductCard'
import { useReplaceCartItem } from '@/features/compatibility/api'
import { ApiError } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'

import { useAddBundleToCart, useSetCartQuantity } from './api'
import type { BundleSummary, Recommendations, SmartCart, SmartSuggestion } from './types'

/** Recommendation groups as rails of real product cards, each with its reason. Empty groups are not shown. */
export function RecommendationRails({ data, order, titles = {} }: { data: Recommendations; order: string[]; titles?: Record<string, string> }) {
  const names = order.filter((name) => (data.groups[name] ?? []).length > 0)
  if (!names.length) return null
  return (
    <>
      {names.map((name) => {
        const title = titles[name] ?? data.titles[name] ?? name
        return (
          <section key={name} aria-label={title} className="py-4">
            <h2 className="mb-3 text-lg font-bold text-ink-950">{title}</h2>
            <ul role="list" aria-label={title} className="scrollbar-none -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2 sm:gap-4">
              {data.groups[name]!.map((row) => (
                <li key={row.product_id} className="flex w-44 shrink-0 snap-start flex-col sm:w-56">
                  {row.reason && <p className="mb-1 line-clamp-2 text-xs font-medium text-ink-600">{row.reason}</p>}
                  <div className="w-full flex-1">
                    <ProductCard product={row.product} />
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </>
  )
}

export function BundleCard({ bundle }: { bundle: BundleSummary }) {
  return (
    <li className="flex flex-col rounded-lg bg-white p-4 ring-1 ring-steel-200">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
        {bundle.kind_label}
        {bundle.promo_label && <span className="ml-2 rounded bg-amber-100 px-1.5 normal-case text-ink-900">{bundle.promo_label}</span>}
      </p>
      <Link to={`/bundles/${bundle.slug}`} className="mt-1 font-bold hover:text-amber-600">
        {bundle.name}
      </Link>
      <p className="mt-1 flex-1 text-sm text-ink-600">{bundle.description}</p>
      <p className="mt-2 text-sm">
        {bundle.item_count} items · <span className="font-bold">{formatPrice(bundle.total)}</span>
        {Number(bundle.savings.vs_mrp) > 0 && <span className="ml-1 text-xs text-success-600">save {formatPrice(bundle.savings.vs_mrp)} vs MRP</span>}
      </p>
      {!bundle.valid && <p className="text-xs text-danger-600">Some items are unavailable right now.</p>}
    </li>
  )
}

const ACTION_LABEL: Record<string, string> = {
  add: 'Add to cart',
  replace: 'Replace',
  remove: 'Remove',
  set_quantity: 'Update quantity',
  apply_bundle: 'Add the missing items',
}

/**
 * The smart cart: warnings first, then the highest-value suggestions. Nothing changes the cart until the customer
 * presses a button; replacing or removing a line asks for confirmation first.
 */
export function SmartCartPanel({ data }: { data: SmartCart }) {
  const [expanded, setExpanded] = useState(false)
  if (data.empty || !data.sections.length) return null
  const shown = expanded ? data.sections : data.sections.slice(0, 3)
  return (
    <section aria-label="Smart cart" className="mt-4 space-y-3">
      {shown.map((section) => (
        <div key={section.key} className={`rounded-lg p-3 ring-1 ${section.key === 'warnings' ? 'bg-amber-50 ring-amber-300' : 'bg-white ring-steel-200'}`}>
          <h2 className="text-sm font-bold">{section.title}</h2>
          <ul className="mt-2 space-y-2" aria-label={section.title}>
            {section.items.map((item, index) => (
              <SuggestionRow key={`${item.type}-${item.product_id ?? item.cart_item_id ?? index}`} item={item} />
            ))}
          </ul>
        </div>
      ))}
      {data.sections.length > 3 && (
        <button type="button" className="text-sm font-semibold text-amber-700 underline" onClick={() => setExpanded((v) => !v)}>
          {expanded ? 'Show fewer suggestions' : `Show ${data.sections.length - 3} more`}
        </button>
      )}
    </section>
  )
}

function SuggestionRow({ item }: { item: SmartSuggestion }) {
  const toast = useToast()
  const add = useAddToCart()
  const replace = useReplaceCartItem()
  const remove = useRemoveCartItem()
  const setQuantity = useSetCartQuantity()
  const addBundle = useAddBundleToCart()
  const [confirming, setConfirming] = useState(false)
  const busy = add.isPending || replace.isPending || remove.isPending || setQuantity.isPending || addBundle.isPending
  const fail = (error: unknown) => toast.show(error instanceof ApiError ? error.message : 'Could not do that. Please try again.', { tone: 'error' })
  const needsConfirm = item.action === 'replace' || item.action === 'remove'

  function run() {
    if (needsConfirm && !confirming) {
      setConfirming(true)
      return
    }
    setConfirming(false)
    if (item.action === 'add' && item.variant_id) {
      add.mutate({ variantId: item.variant_id, quantity: item.quantity ?? 1 }, { onSuccess: () => toast.show(`Added ${item.product?.name ?? 'it'} to your cart.`), onError: fail })
    } else if (item.action === 'replace' && item.cart_item_id && item.variant_id) {
      replace.mutate({ itemId: item.cart_item_id, variantId: item.variant_id }, { onSuccess: () => toast.show(`Replaced with ${item.product?.name ?? 'the suggestion'}.`), onError: fail })
    } else if (item.action === 'remove' && item.cart_item_id) {
      remove.mutate(item.cart_item_id, { onSuccess: () => toast.show('Removed from your cart.'), onError: fail })
    } else if (item.action === 'set_quantity' && item.cart_item_id && item.quantity) {
      setQuantity.mutate({ itemId: item.cart_item_id, quantity: item.quantity }, { onSuccess: () => toast.show('Quantity updated.'), onError: fail })
    } else if (item.action === 'apply_bundle' && item.bundle) {
      addBundle.mutate({ slug: item.bundle.slug, onlyMissing: true }, { onSuccess: (r) => toast.show(`Added ${r.added_lines} item${r.added_lines === 1 ? '' : 's'} from ${item.bundle!.name}.`), onError: fail })
    }
  }

  const actionable = item.action && item.action !== 'view' && (item.action !== 'set_quantity' || item.quantity)
  return (
    <li className="text-sm">
      <p>{item.message}</p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {item.product && (
          <Link to={`/p/${item.product.slug}`} className="text-xs font-semibold text-amber-700 underline">
            View {item.product.name}
          </Link>
        )}
        {item.price && <span className="text-xs text-ink-600">{formatPrice(item.price.unit_price)} each</span>}
        {item.saving && <span className="text-xs text-success-600">save {formatPrice(item.saving)}</span>}
        {actionable && !confirming && (
          <button type="button" className="btn-secondary px-2.5 py-1 text-xs" disabled={busy} onClick={run}>
            {item.action === 'set_quantity' ? `Make it ${item.quantity}` : ACTION_LABEL[item.action!]}
          </button>
        )}
        {confirming && (
          <span className="flex items-center gap-2" role="group" aria-label="Confirm">
            <span className="text-xs">{item.action === 'replace' ? `Replace with ${item.product?.name ?? 'the suggestion'}?` : 'Remove this line?'}</span>
            <button type="button" className="btn-primary px-2.5 py-1 text-xs" disabled={busy} onClick={run}>
              Yes, {item.action === 'replace' ? 'replace' : 'remove'}
            </button>
            <button type="button" className="text-xs underline" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </span>
        )}
      </div>
    </li>
  )
}
