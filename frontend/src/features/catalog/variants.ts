import type { ProductVariant } from './types'

/** Human label for a variant: its name, else its attributes, else "Option N". */
export function variantLabel(variant: ProductVariant, index: number): string {
  if (variant.name) return variant.name
  const attrs = Object.values(variant.attributes ?? {})
  return attrs.length ? attrs.join(' · ') : `Option ${index + 1}`
}
