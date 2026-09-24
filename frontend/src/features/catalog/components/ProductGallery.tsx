import { useState } from 'react'

import type { ProductImage as ProductImageType } from '../types'
import { ProductImage } from './ProductImage'

/** Main image + thumbnails. Images of the selected variant are shown first. */
export function ProductGallery({
  images,
  productName,
  variantId,
}: {
  images: ProductImageType[]
  productName: string
  variantId: number | null
}) {
  const ordered = [
    ...images.filter((img) => img.variant !== null && img.variant === variantId),
    ...images.filter((img) => img.variant === null),
  ]
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const current = ordered.find((img) => img.id === selectedId) ?? ordered[0]

  return (
    <div className="flex flex-col gap-3 md:flex-row-reverse">
      <div className="flex-1 overflow-hidden rounded-lg bg-white ring-1 ring-steel-200">
        <ProductImage
          src={current?.image}
          alt={current?.alt_text || productName}
          eager
          className="aspect-square w-full"
        />
      </div>
      {ordered.length > 1 && (
        <ul
          aria-label="Product images"
          className="scrollbar-none flex gap-2 overflow-x-auto md:w-20 md:flex-col md:overflow-visible"
        >
          {ordered.map((img, index) => {
            const active = img.id === current?.id
            return (
              <li key={img.id} className="shrink-0">
                <button
                  type="button"
                  onClick={() => setSelectedId(img.id)}
                  aria-label={`Show image ${index + 1} of ${ordered.length}`}
                  aria-pressed={active}
                  className={`block overflow-hidden rounded-md ring-2 ${active ? 'ring-amber-500' : 'ring-transparent hover:ring-steel-200'}`}
                >
                  <ProductImage src={img.image} alt="" className="size-16 md:size-20" />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
