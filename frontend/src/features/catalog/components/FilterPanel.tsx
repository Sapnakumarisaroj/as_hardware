import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'

import { StarIcon } from '@/components/icons'
import { isValidPincode, usePincode } from '@/features/delivery/location'
import { formatPrice } from '@/lib/format'

import { csv, type ListingState } from '../listingState'
import type { ProductFacets } from '../types'

interface Props {
  facets: ProductFacets
  state: ListingState
  /** On a category page subcategories are links; on search they filter in place. */
  categoryLinks: boolean
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="border-b border-steel-200 py-4 first:pt-0 last:border-0">
      <legend className="mb-2 text-sm font-bold text-ink-950">{title}</legend>
      <div className="space-y-1.5">{children}</div>
    </fieldset>
  )
}

function Option({
  type,
  name,
  checked,
  onChange,
  label,
  count,
}: {
  type: 'checkbox' | 'radio'
  name: string
  checked: boolean
  onChange: () => void
  label: ReactNode
  count?: number
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-800">
      <input type={type} name={name} checked={checked} onChange={onChange} className="size-4 accent-amber-600" />
      <span className="flex-1">{label}</span>
      {count !== undefined && <span className="text-xs text-ink-600">{count}</span>}
    </label>
  )
}

export function FilterPanel({ facets, state, categoryLinks }: Props) {
  const { filters, setParam, toggleValue } = state
  const pincode = usePincode()
  const brands = csv(filters.brand)
  const showRatings = facets.ratings.some((r) => r.count > 0) || Boolean(filters.rating)
  const discounts = facets.discounts.filter((d) => d.count > 0 || filters.discount === String(d.min))

  return (
    <div>
      {facets.categories.length > 0 && (
        <Section title={categoryLinks ? 'Subcategories' : 'Category'}>
          {facets.categories.map((option) =>
            categoryLinks ? (
              <Link
                key={option.slug}
                to={`/c/${option.slug}`}
                className="flex items-center justify-between rounded px-1 py-0.5 text-sm text-ink-800 hover:bg-steel-50 hover:text-amber-600"
              >
                <span>{option.name}</span>
                <span className="text-xs text-ink-600">{option.count}</span>
              </Link>
            ) : (
              <Option
                key={option.slug}
                type="radio"
                name="category"
                checked={filters.category === option.slug}
                onChange={() => setParam('category', filters.category === option.slug ? null : option.slug)}
                label={option.name}
                count={option.count}
              />
            ),
          )}
          {!categoryLinks && filters.category && (
            <button type="button" onClick={() => setParam('category', null)} className="text-xs font-semibold text-amber-600">
              All categories
            </button>
          )}
        </Section>
      )}

      {facets.brands.length > 0 && (
        <Section title="Brand">
          {facets.brands.map((option) => (
            <Option
              key={option.slug}
              type="checkbox"
              name="brand"
              checked={brands.includes(option.slug)}
              onChange={() => toggleValue('brand', option.slug)}
              label={option.name}
              count={option.count}
            />
          ))}
        </Section>
      )}

      {/* Product options (Grade, Bag size, Cross-section…) come from the catalogue's option types, so
          only the options of the products listed appear (no cement grades on a wire page). */}
      {facets.options?.map((option) => {
        const key = `opt_${option.slug}`
        const selected = csv(filters[key])
        return (
          <Section key={key} title={option.name}>
            {option.values.map((value) => (
              <Option
                key={value.slug}
                type="checkbox"
                name={key}
                checked={selected.includes(value.slug)}
                onChange={() => toggleValue(key, value.slug)}
                label={value.value}
                count={value.count}
              />
            ))}
          </Section>
        )
      })}

      {facets.price.min !== null && (
        <Section title="Price">
          <PriceRange
            key={`${filters.min_price ?? ''}-${filters.max_price ?? ''}`}
            min={filters.min_price ?? ''}
            max={filters.max_price ?? ''}
            placeholderMin={facets.price.min}
            placeholderMax={facets.price.max}
            onApply={(min, max) => state.setParams({ min_price: min || null, max_price: max || null })}
          />
        </Section>
      )}

      <Section title="Availability">
        <Option
          type="checkbox"
          name="availability"
          checked={filters.availability === 'in_stock'}
          onChange={() => setParam('availability', filters.availability === 'in_stock' ? null : 'in_stock')}
          label="In stock only"
          count={facets.availability.in_stock}
        />
        {/* Fast delivery depends on the address, so the filter is offered only for a chosen PIN. */}
        {isValidPincode(pincode) && (facets.availability.fast_delivery > 0 || filters.fast_delivery) && (
          <Option
            type="checkbox"
            name="fast_delivery"
            checked={filters.fast_delivery === 'true'}
            onChange={() => setParam('fast_delivery', filters.fast_delivery === 'true' ? null : 'true')}
            label={`Fast delivery to ${pincode}`}
            count={facets.availability.fast_delivery}
          />
        )}
      </Section>

      {showRatings && (
        <Section title="Customer rating">
          {facets.ratings.map((option) => (
            <Option
              key={option.min}
              type="radio"
              name="rating"
              checked={filters.rating === String(option.min)}
              onChange={() => setParam('rating', filters.rating === String(option.min) ? null : String(option.min))}
              label={
                <span className="inline-flex items-center gap-1">
                  {option.min}
                  <StarIcon className="size-3.5 text-amber-500" /> & above
                </span>
              }
              count={option.count}
            />
          ))}
        </Section>
      )}

      {discounts.length > 0 && (
        <Section title="Discount">
          {discounts.map((option) => (
            <Option
              key={option.min}
              type="radio"
              name="discount"
              checked={filters.discount === String(option.min)}
              onChange={() =>
                setParam('discount', filters.discount === String(option.min) ? null : String(option.min))
              }
              label={`${option.min}% or more`}
              count={option.count}
            />
          ))}
        </Section>
      )}

      {facets.specifications.map((spec) => {
        const key = `spec_${spec.key}`
        const selected = csv(filters[key])
        return (
          <Section key={spec.key} title={spec.name}>
            {spec.values.map((option) => (
              <Option
                key={option.value}
                type="checkbox"
                name={key}
                checked={selected.includes(option.value)}
                onChange={() => toggleValue(key, option.value)}
                label={spec.unit ? `${option.value} ${spec.unit}` : option.value}
                count={option.count}
              />
            ))}
          </Section>
        )
      })}
    </div>
  )
}

function PriceRange({
  min,
  max,
  placeholderMin,
  placeholderMax,
  onApply,
}: {
  min: string
  max: string
  placeholderMin: string | null
  placeholderMax: string | null
  onApply: (min: string, max: string) => void
}) {
  const [low, setLow] = useState(min)
  const [high, setHigh] = useState(max)
  function submit(event: FormEvent) {
    event.preventDefault()
    onApply(low.trim(), high.trim())
  }
  return (
    <form onSubmit={submit} className="space-y-2">
      <div className="flex items-center gap-2">
        <label className="flex-1">
          <span className="sr-only">Minimum price</span>
          <input
            inputMode="decimal"
            pattern="[0-9]*[.]?[0-9]*"
            value={low}
            onChange={(e) => setLow(e.target.value)}
            placeholder={placeholderMin ? `Min ${formatPrice(placeholderMin)}` : 'Min'}
            className="input"
          />
        </label>
        <span aria-hidden className="text-ink-600">
          –
        </span>
        <label className="flex-1">
          <span className="sr-only">Maximum price</span>
          <input
            inputMode="decimal"
            pattern="[0-9]*[.]?[0-9]*"
            value={high}
            onChange={(e) => setHigh(e.target.value)}
            placeholder={placeholderMax ? `Max ${formatPrice(placeholderMax)}` : 'Max'}
            className="input"
          />
        </label>
      </div>
      <button type="submit" className="btn-secondary w-full py-1.5">
        Apply price
      </button>
    </form>
  )
}
