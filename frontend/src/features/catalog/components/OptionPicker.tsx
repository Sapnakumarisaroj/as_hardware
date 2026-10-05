import type { ProductOption, ProductVariant } from '../types'
import { variantForChoice } from '../variants'

/**
 * Structured options (Grade, Bag size, Thickness…). Each value is a button; values that don't exist
 * with the other current choices are still offered (choosing one switches the other options to a
 * combination that is sold), while values sold nowhere aren't listed at all — the server only
 * returns values used by active variants.
 */
export function OptionPicker({
  options,
  variants,
  selected,
  onSelect,
}: {
  options: ProductOption[]
  variants: ProductVariant[]
  selected: ProductVariant
  onSelect: (id: number) => void
}) {
  if (!options.length) return null
  return (
    <div className="space-y-3">
      {options.map((option) => {
        const current = selected.options?.[option.slug]
        const currentLabel = option.values.find((v) => v.slug === current)?.value
        return (
          <fieldset key={option.slug}>
            <legend className="mb-2 text-sm font-semibold text-ink-900">
              {option.name}
              {currentLabel && <span className="font-normal text-ink-600">: {currentLabel}</span>}
            </legend>
            <div role="radiogroup" aria-label={option.name} className="flex flex-wrap gap-2">
              {option.values.map((value) => {
                const isSelected = value.slug === current
                const target = variantForChoice(variants, selected, option.slug, value.slug)
                const exact = variants.some((v) =>
                  Object.entries({ ...selected.options, [option.slug]: value.slug }).every(([k, val]) => v.options?.[k] === val),
                )
                const out = target?.stock_status === 'out_of_stock'
                return (
                  <button
                    key={value.slug}
                    type="button"
                    role="radio"
                    aria-checked={isSelected}
                    disabled={!target}
                    onClick={() => target && onSelect(target.id)}
                    title={!exact && target ? 'Changes your other choices to an available combination' : undefined}
                    className={`min-h-10 rounded-md px-3 py-1.5 text-sm ring-1 transition ${
                      isSelected ? 'bg-amber-100 font-semibold ring-2 ring-amber-500' : 'bg-white ring-steel-200 hover:ring-ink-600'
                    } ${!exact || out ? 'text-ink-600' : 'text-ink-900'}`}
                  >
                    {value.value}
                    {out && <span className="text-xs"> · out of stock</span>}
                  </button>
                )
              })}
            </div>
          </fieldset>
        )
      })}
    </div>
  )
}
