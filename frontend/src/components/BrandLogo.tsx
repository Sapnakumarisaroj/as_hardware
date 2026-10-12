import { business } from '@/lib/business'

interface Props {
  /** Height of the AS symbol, e.g. 'h-11 md:h-12'; its width follows the symbol's own proportions. */
  size?: string
  /** Show "Hardware and Plywood" under the symbol (the full brand lock-up). */
  withName?: boolean
  /** Classes for an extra label next to the logo (e.g. "Admin"); omitted = none. */
  suffix?: string
  /** Text colour of the name under the symbol. */
  nameTone?: string
}

/**
 * The AS symbol (cropped from the official logo, never stretched) with "Hardware and Plywood" below it.
 * The image has a white background; `mix-blend-multiply` lets light page colours show through it.
 * Wrap it in a Link where it should lead home.
 */
export function BrandLogo({ size = 'h-11', withName = true, suffix, nameTone = 'text-ink-950' }: Props) {
  return (
    <>
      <span className="inline-flex shrink-0 flex-col items-center leading-none">
        <img
          src={business.logo.symbol}
          alt={business.name}
          width={business.logo.symbolWidth}
          height={business.logo.symbolHeight}
          className={`${size} w-auto object-contain mix-blend-multiply`}
        />
        {withName && (
          <span aria-hidden className={`mt-0.5 whitespace-nowrap text-[10px] font-extrabold uppercase tracking-[0.08em] sm:text-[11px] ${nameTone}`}>
            {business.nameUnderSymbol}
          </span>
        )}
      </span>
      {suffix && <span className="font-semibold">{suffix}</span>}
    </>
  )
}

/** The full official logo, larger (keeps its proportions; the width comes from `className`). */
export function FullLogo({ className = 'w-56', loading = 'lazy' }: { className?: string; loading?: 'lazy' | 'eager' }) {
  return (
    <img
      src={business.logo.full}
      alt={`${business.name} logo`}
      width={business.logo.fullWidth}
      height={business.logo.fullHeight}
      loading={loading}
      className={`${className} h-auto object-contain`}
    />
  )
}
