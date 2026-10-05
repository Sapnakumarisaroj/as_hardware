interface Props {
  value: number
  max: number
  onChange: (value: number) => void
  disabled?: boolean
  label?: string
  /** `sm` for product cards (still a 32 px touch target). */
  size?: 'md' | 'sm'
}

/** − / + quantity control. Limits are a convenience; the server re-validates stock. */
export function QuantityStepper({ value, max, onChange, disabled, label = 'Quantity', size = 'md' }: Props) {
  const small = size === 'sm'
  const button =
    `grid ${small ? 'size-8 text-base' : 'size-9 text-lg'} place-items-center font-semibold text-ink-900 hover:bg-steel-50 disabled:cursor-not-allowed disabled:text-steel-400`
  return (
    <div className="inline-flex items-center rounded-md bg-white ring-1 ring-steel-200" role="group" aria-label={label}>
      <button
        type="button"
        onClick={() => onChange(value - 1)}
        disabled={disabled || value <= 1}
        className={button}
        aria-label="Decrease quantity"
      >
        −
      </button>
      <output aria-live="polite" className={`${small ? 'w-7' : 'w-10'} text-center text-sm font-semibold`}>
        {value}
      </output>
      <button
        type="button"
        onClick={() => onChange(value + 1)}
        disabled={disabled || value >= max}
        className={button}
        aria-label="Increase quantity"
      >
        +
      </button>
    </div>
  )
}
