import { formatPrice } from '@/lib/format'

import type { ProductVariant } from '../types'
import { variantLabel } from '../variants'

/** Every sellable unit is a variant; choosing one switches price, SKU, stock and specs. */
export function VariantSelector({
  variants,
  selectedId,
  onSelect,
}: {
  variants: ProductVariant[]
  selectedId: number
  onSelect: (id: number) => void
}) {
  if (variants.length < 2) return null
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-semibold text-ink-900">
        Choose an option <span className="font-normal text-ink-600">({variants.length} available)</span>
      </legend>
      <div role="radiogroup" className="flex flex-wrap gap-2">
        {variants.map((variant, index) => {
          const selected = variant.id === selectedId
          const out = variant.stock_status === 'out_of_stock'
          return (
            <button
              key={variant.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onSelect(variant.id)}
              className={`min-w-24 rounded-md px-3 py-2 text-left text-sm ring-1 transition ${
                selected ? 'bg-amber-100 ring-2 ring-amber-500' : 'bg-white ring-steel-200 hover:ring-ink-600'
              } ${out ? 'opacity-60' : ''}`}
            >
              <span className="block font-semibold text-ink-900">{variantLabel(variant, index)}</span>
              <span className="block text-xs text-ink-600">
                {formatPrice(variant.price)}
                {out && ' · Out of stock'}
              </span>
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}
