import { CheckIcon, CompareIcon } from '@/components/icons'
import { useToast } from '@/components/toast'

import { addToCompare, COMPARE_MAX, removeFromCompare, useCompareItems, type CompareItem } from './store'

/**
 * Adds a product to (or takes it off) the compare list. `icon` sits on a product card's picture
 * (a 36px circle with a 44px touch area), `button` is the labelled version for the product page.
 */
export function CompareButton({ product, variant = 'icon' }: { product: CompareItem; variant?: 'icon' | 'button' }) {
  const items = useCompareItems()
  const toast = useToast()
  const selected = items.some((i) => i.slug === product.slug)

  function toggle() {
    if (selected) {
      removeFromCompare(product.slug)
      return
    }
    if (!addToCompare(product)) {
      toast.show(`You can compare up to ${COMPARE_MAX} products. Remove one to add this.`, {
        tone: 'info',
        action: { label: 'Compare now', to: '/compare' },
      })
    }
  }

  const label = selected ? `Remove ${product.name} from compare` : `Add ${product.name} to compare`
  if (variant === 'button') {
    return (
      <button type="button" onClick={toggle} aria-pressed={selected} className="btn-secondary min-h-11" data-testid="compare-toggle">
        {selected ? <CheckIcon className="size-4 text-success-600" /> : <CompareIcon className="size-4" />}
        {selected ? 'Added to compare' : 'Compare'}
      </button>
    )
  }
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={selected}
      aria-label={label}
      title={selected ? 'Remove from compare' : 'Compare'}
      data-testid="compare-toggle"
      className={`relative grid size-9 place-items-center rounded-full shadow-sm ring-1 backdrop-blur transition after:absolute after:-inset-1 after:content-[''] hover:scale-110 ${
        selected ? 'bg-ink-900 text-amber-400 ring-ink-900' : 'bg-white/95 text-ink-800 ring-steel-200 hover:text-amber-700'
      }`}
    >
      {selected ? <CheckIcon className="size-5" /> : <CompareIcon className="size-5" />}
    </button>
  )
}
