import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { productPage, productSummary } from '@/test/fixtures'
import { mockApi } from '@/test/mockApi'
import { renderRoute } from '@/test/utils'

/** Cards are rendered through the real /products listing so they get real providers. */
async function renderCards(products: ReturnType<typeof productSummary>[]) {
  mockApi({
    get: {
      '/categories/': [],
      '/products/': productPage(products),
      '/products/facets/': {
        total: products.length,
        categories: [],
        brands: [],
        price: { min: null, max: null },
        ratings: [],
        discounts: [],
        availability: { in_stock: 0, fast_delivery: 0 },
        specifications: [],
      },
    },
  })
  const view = renderRoute('/products')
  await screen.findAllByRole('article')
  return view
}

describe('ProductCard', () => {
  it('shows server price, MRP, discount, saving, rating, stock, quantity and add button', async () => {
    await renderCards([productSummary()])
    const card = screen.getByRole('article')
    expect(card).toHaveTextContent('DrillCo')
    expect(screen.getByRole('link', { name: 'Impact Drill 650W' })).toHaveAttribute('href', '/p/impact-drill-650w')
    expect(card).toHaveTextContent('Price: ₹3,200')
    expect(card).toHaveTextContent('MRP: ₹4,000')
    expect(card).toHaveTextContent('20% off')
    expect(card).toHaveTextContent('4.5')
    expect(card).toHaveTextContent('(12)')
    expect(card).toHaveTextContent('Save ₹800')
    expect(card).toHaveTextContent('In stock')
    // No PIN chosen: no fast-delivery promise, even though some store offers fast delivery.
    expect(screen.queryByTestId('fast-badge')).not.toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Quantity of Impact Drill 650W' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Save Impact Drill 650W to wishlist' })).toBeInTheDocument()
    // Missing image → labelled fallback, never a broken <img>. (The image link duplicates the
    // title link, so it is hidden from assistive tech on purpose.)
    expect(screen.getByRole('img', { name: 'Impact Drill 650W (no image available)', hidden: true })).toBeInTheDocument()
  })

  it('sends multi-variant products to the detail page to choose an option', async () => {
    await renderCards([productSummary({ variant_count: 3 })])
    expect(screen.getByText('3 options')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Choose options' })).toHaveAttribute('href', '/p/impact-drill-650w')
    expect(screen.queryByRole('button', { name: 'Add' })).not.toBeInTheDocument()
  })

  it('shows fast delivery only for the chosen PIN, and says when that PIN is not served', async () => {
    await renderCards([
      productSummary({ delivery: { postal_code: '411038', deliverable: true, fast: true } }),
      productSummary({ id: 2, slug: 'saw', name: 'Saw', delivery: { postal_code: '411038', deliverable: false, fast: false } }),
    ])
    const [drill, saw] = screen.getAllByRole('article')
    expect(drill).toHaveTextContent('Fast delivery to 411038')
    expect(saw).not.toHaveTextContent('Fast delivery')
    expect(saw).toHaveTextContent('Not available for delivery to 411038')
  })

  it('shows the free-delivery rule and bulk price from the server', async () => {
    await renderCards([
      productSummary({
        free_delivery: { name: 'Tools from ₹2,000', threshold: '2000.00' },
        bulk_pricing: { from_quantity: 10, lowest_unit_price: '3000.00' },
      }),
    ])
    expect(screen.getByTestId('free-delivery-badge')).toHaveTextContent('Free delivery from ₹2,000')
    expect(screen.getByTestId('bulk-indicator')).toHaveTextContent('from ₹3,000/unit (10+)')
  })

  it('disables buying when out of stock and hides the fast-delivery badge', async () => {
    await renderCards([productSummary({ stock_status: 'out_of_stock' })])
    const card = screen.getByRole('article')
    expect(card).toHaveTextContent('Out of stock')
    expect(card).not.toHaveTextContent('Fast delivery')
    expect(screen.getByRole('button', { name: 'Out of stock' })).toBeDisabled()
    expect(screen.queryByRole('group', { name: /Quantity of/ })).not.toBeInTheDocument()
  })

  it('shows limited stock and no discount badge when price equals MRP', async () => {
    await renderCards([
      productSummary({ stock_status: 'low_stock', price: '4000.00', discount_percent: '0.00', discount_amount: '0.00', rating_count: 0 }),
    ])
    const card = screen.getByRole('article')
    expect(card).toHaveTextContent('Limited stock')
    expect(card).not.toHaveTextContent('off')
    expect(card).toHaveTextContent('No reviews yet')
  })
})
