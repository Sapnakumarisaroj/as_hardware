import type { SmartCart } from './types'

/** A section is shown only with something to act on: the free-delivery gap alone (no add-on that closes it) is not. */
export function visibleSections(data: SmartCart) {
  return data.sections.filter((section) => section.items.length > 0 && (section.key !== 'free_delivery' || section.items.some((item) => item.action === 'add')))
}
