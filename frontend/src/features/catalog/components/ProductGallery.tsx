import { useState } from 'react'

import { ChevronRightIcon } from '@/components/icons'

import type { ProductImage as ProductImageType } from '../types'
import { ProductImage } from './ProductImage'

/** Says when a picture is only an illustration, and credits licensed photos. */
function ImageCredit({ image }: { image: ProductImageType | undefined }) {
  if (!image) return null
  if (image.image_type === 'illustration') {
    return (
      <p className="border-t border-steel-100 px-3 py-1.5 text-xs text-ink-600" data-testid="image-note">
        Illustration — not a photo of this exact product.
      </p>
    )
  }
  if (image.source_type === 'licensed' && image.licence) {
    return (
      <p className="border-t border-steel-100 px-3 py-1.5 text-xs text-ink-600" data-testid="image-note">
        Photo: {image.source_url ? <a href={image.source_url} target="_blank" rel="noreferrer noopener" className="underline">{image.licence}</a> : image.licence}
      </p>
    )
  }
  return null
}

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
  const position = current ? ordered.indexOf(current) : 0
  const step = (by: number) => setSelectedId(ordered[(position + by + ordered.length) % ordered.length]?.id ?? null)
  const arrow =
    'absolute top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full bg-white/90 text-ink-900 shadow ring-1 ring-steel-200 hover:bg-white focus-visible:outline-2 focus-visible:outline-amber-500'

  return (
    <div className="flex flex-col gap-3 md:flex-row-reverse">
      <div className="flex-1 overflow-hidden rounded-2xl bg-white shadow-(--shadow-card) ring-1 ring-steel-200">
        <div className="relative">
          <ProductImage
            src={current?.image}
            alt={current?.alt_text || productName}
            eager
            className="aspect-square w-full"
          />
          {ordered.length > 1 && (
            <>
              <button type="button" onClick={() => step(-1)} aria-label="Previous image" className={`${arrow} left-2`}>
                <ChevronRightIcon className="size-5 rotate-180" />
              </button>
              <button type="button" onClick={() => step(1)} aria-label="Next image" className={`${arrow} right-2`}>
                <ChevronRightIcon className="size-5" />
              </button>
              <p className="absolute bottom-2 right-2 rounded-full bg-ink-900/70 px-2 py-0.5 text-xs text-white" aria-live="polite">
                {position + 1} / {ordered.length}
              </p>
            </>
          )}
        </div>
        <ImageCredit image={current} />
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
