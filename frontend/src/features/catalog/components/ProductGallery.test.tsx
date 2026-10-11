import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

describe('product gallery controls', () => {
  const images: ProductImage[] = [
    { ...base, id: 1, image: '/media/a.webp', alt_text: 'Front' },
    { ...base, id: 2, image: '/media/b.webp', alt_text: 'Back', is_primary: false, sort_order: 1 },
    { ...base, id: 3, image: '/media/c.webp', alt_text: 'Label', is_primary: false, sort_order: 2 },
  ]

  it('steps through the pictures with previous and next, wrapping at the ends', async () => {
    const user = userEvent.setup()
    render(<ProductGallery images={images} productName="Fevicol SH" variantId={null} />)
    expect(screen.getByText('1 / 3')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Next image' }))
    expect(screen.getByText('2 / 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show image 2 of 3' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'Previous image' }))
    await user.click(screen.getByRole('button', { name: 'Previous image' }))
    expect(screen.getByText('3 / 3')).toBeInTheDocument()
  })

  it('shows no arrows for a single picture', () => {
    render(<ProductGallery images={[base]} productName="Fevicol SH" variantId={null} />)
    expect(screen.queryByRole('button', { name: 'Next image' })).not.toBeInTheDocument()
  })
})
