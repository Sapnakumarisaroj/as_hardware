import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ProductImage } from '../types'
import { ProductGallery } from './ProductGallery'

const base: ProductImage = { id: 1, image: '/media/products/x.png', alt_text: '', variant: null, is_primary: true, sort_order: 0 }

describe('product gallery image note', () => {
  it('says when the picture is an illustration, not a photo of the product', () => {
    render(<ProductGallery images={[{ ...base, source_type: 'generated', image_type: 'illustration' }]} productName="Claw Hammer" variantId={null} />)
    expect(screen.getByTestId('image-note')).toHaveTextContent('Illustration — not a photo of this exact product.')
  })

  it('credits a licensed photo with its source', () => {
    render(
      <ProductGallery
        images={[{ ...base, source_type: 'licensed', image_type: 'photo', licence: 'CC BY-SA 4.0, A. Author', source_url: 'https://example.org/file' }]}
        productName="Claw Hammer"
        variantId={null}
      />,
    )
    expect(screen.getByRole('link', { name: 'CC BY-SA 4.0, A. Author' })).toHaveAttribute('href', 'https://example.org/file')
  })

  it('adds nothing for an ordinary product photo', () => {
    render(<ProductGallery images={[{ ...base, source_type: 'supplier', image_type: 'photo' }]} productName="Claw Hammer" variantId={null} />)
    expect(screen.queryByTestId('image-note')).not.toBeInTheDocument()
  })
})
