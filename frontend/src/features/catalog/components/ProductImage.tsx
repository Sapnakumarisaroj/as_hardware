import { useState } from 'react'

import { ImageIcon } from '@/components/icons'

interface Props {
  src: string | null | undefined
  alt: string
  className?: string
  eager?: boolean
}

/** Product picture with lazy loading and a neutral fallback when missing or broken. */
export function ProductImage({ src, alt, className = '', eager = false }: Props) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  if (!src || failedSrc === src) {
    return (
      <div
        role="img"
        aria-label={`${alt} (no image available)`}
        className={`grid place-items-center bg-steel-100 text-steel-400 ${className}`}
      >
        <ImageIcon className="size-10" />
      </div>
    )
  }
  return (
    <img
      src={src}
      alt={alt}
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      onError={() => setFailedSrc(src)}
      className={`bg-steel-100 object-contain ${className}`}
    />
  )
}
