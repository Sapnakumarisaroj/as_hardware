import { business } from '@/lib/business'

interface Props {
  /** Size of the round mark, e.g. 'size-10'. */
  size?: string
  /** Classes for the shop name next to the mark; null shows the mark alone. */
  nameClassName?: string | null
  /** Show the short name ("AS Hardware") where space is tight. */
  short?: boolean
  suffix?: string
}

/** Round "AS" logo mark + shop name (square image, never stretched). Wrap it in a Link where it should lead home. */
export function BrandLogo({ size = 'size-9', nameClassName = '', short = false, suffix }: Props) {
  return (
    <>
      <img
        src={business.logo.mark}
        alt={nameClassName === null ? business.name : ''}
        width={256}
        height={256}
        className={`${size} shrink-0 rounded-full object-contain`}
      />
      {nameClassName !== null && (
        <span className={nameClassName}>
          {short ? business.shortName : business.name}
          {suffix && <span className="font-normal text-steel-200"> {suffix}</span>}
        </span>
      )}
    </>
  )
}

/** The full official logo (keeps its 720 × 453 proportions; the width comes from `className`). */
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
