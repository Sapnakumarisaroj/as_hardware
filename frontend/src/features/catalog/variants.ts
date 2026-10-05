import type { ProductVariant } from './types'

/** Human label for a variant: its name, else its attributes, else "Option N". */
export function variantLabel(variant: ProductVariant, index: number): string {
  if (variant.name) return variant.name
  const attrs = Object.values(variant.attributes ?? {})
  return attrs.length ? attrs.join(' · ') : `Option ${index + 1}`
}

/** The variant that has `wanted` for `type` and keeps as many of the other current choices as possible. */
export function variantForChoice(
  variants: ProductVariant[],
  current: ProductVariant,
  type: string,
  wanted: string,
): ProductVariant | undefined {
  const candidates = variants.filter((v) => v.options?.[type] === wanted)
  const score = (v: ProductVariant) =>
    Object.entries(current.options ?? {}).filter(([key, value]) => key !== type && v.options?.[key] === value).length
  return [...candidates].sort((a, b) => score(b) - score(a))[0]
}
