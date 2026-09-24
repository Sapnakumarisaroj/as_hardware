import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { cart, customer, productPage, wireDetail } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const reviews = { count: 0, next: null, previous: null, results: [] }

function detailRoutes(extra: Record<string, unknown> = {}) {
  return {
    '/categories/': [],
    '/products/fr-pvc-copper-wire/': wireDetail(),
    '/products/fr-pvc-copper-wire/reviews/': reviews,
    '/products/': productPage([]),
    ...extra,
  }
}

function priceArea() {
  return screen.getByRole('heading', { level: 1 }).parentElement!.parentElement!
}

describe('product detail page', () => {
  it('renders product info, the default variant, specifications and delivery information', async () => {
    mockApi({ get: detailRoutes() })
    renderRoute('/p/fr-pvc-copper-wire')

    expect(await screen.findByRole('heading', { level: 1, name: 'FR PVC Insulated Copper Wire' })).toBeInTheDocument()
    expect(document.title).toContain('FR PVC Insulated Copper Wire')
    expect(screen.getByRole('link', { name: 'VoltLine' })).toBeInTheDocument()
    const area = priceArea()
    expect(area).toHaveTextContent('SKU: DEMO-WIRE-15-10')
    expect(area).toHaveTextContent('Price: ₹400')
    expect(area).toHaveTextContent('You save ₹100')
    expect(screen.getByRole('radio', { name: /1\.5 sq mm × 10 m/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText('Fast delivery available from a nearby store')).toBeInTheDocument()
    expect(screen.getByText(/checked after you select your address/)).toBeInTheDocument()

    const specs = screen.getByRole('table', { name: /Specifications of/ })
    expect(within(specs).getByRole('rowheader', { name: 'Conductor' })).toBeInTheDocument()
    expect(within(specs).getByRole('cell', { name: 'DEMO-WIRE-15-10' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Wires & Cables' })).toHaveAttribute('href', '/c/wires-cables')
    expect(await screen.findByText(/No reviews yet\. Customers can review/)).toBeInTheDocument()
  })

  it('switching variant updates price, MRP, SKU, stock, delivery and specs from server data', async () => {
    mockApi({ get: detailRoutes() })
    const { user, router } = renderRoute('/p/fr-pvc-copper-wire')
    await screen.findByRole('heading', { level: 1 })

    await user.click(screen.getByRole('radio', { name: /1\.5 sq mm × 50 m/ }))
    const area = priceArea()
    expect(area).toHaveTextContent('SKU: DEMO-WIRE-15-50')
    expect(area).toHaveTextContent('Price: ₹1,899')
    expect(area).toHaveTextContent('MRP: ₹2,400')
    expect(area).toHaveTextContent('You save ₹501')
    expect(screen.getByText('Only 3 left')).toBeInTheDocument()
    expect(screen.getByText('Standard delivery from our stores')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByRole('cell', { name: '50 m' })).toBeInTheDocument()
    // The choice is kept in the URL so it can be shared/bookmarked.
    expect(currentUrl(router)).toBe('/p/fr-pvc-copper-wire?variant=202')
    // Quantity is capped at what is available.
    await user.click(screen.getByRole('button', { name: 'Increase quantity' }))
    await user.click(screen.getByRole('button', { name: 'Increase quantity' }))
    expect(screen.getByRole('button', { name: 'Increase quantity' })).toBeDisabled()
  })

  it('an out-of-stock variant cannot be added to the cart', async () => {
    mockApi({ get: detailRoutes() })
    renderRoute('/p/fr-pvc-copper-wire?variant=203')
    await screen.findByRole('heading', { level: 1 })
    expect(screen.getByText('Out of stock', { selector: 'span' })).toBeInTheDocument()
    for (const button of screen.getAllByRole('button', { name: 'Out of stock' })) expect(button).toBeDisabled()
    expect(screen.getByText(/Currently unavailable for delivery/)).toBeInTheDocument()
  })

  it('adds the selected variant and quantity to the server cart', async () => {
    signIn()
    const api = mockApi({
      get: { ...detailRoutes(), '/auth/me/': customer, '/wishlist/': [], '/cart/': cart(), '/search/recent/': [] },
      post: { '/cart/items/': cart() },
    })
    const { user } = renderRoute('/p/fr-pvc-copper-wire')
    await screen.findByRole('heading', { level: 1 })
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Add to cart' })[0]).toBeEnabled())

    await user.click(screen.getByRole('button', { name: 'Increase quantity' }))
    await user.click(screen.getAllByRole('button', { name: 'Add to cart' })[0]!)
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/', { variant_id: 201, quantity: 2 }))
    expect(await screen.findByText(/Added to cart: FR PVC Insulated Copper Wire \(1\.5 sq mm × 10 m\)/)).toBeInTheDocument()
  })

  it('shows the backend stock message when the cart rejects the quantity', async () => {
    signIn()
    mockApi({
      get: { ...detailRoutes(), '/auth/me/': customer, '/wishlist/': [], '/cart/': cart(), '/search/recent/': [] },
      post: { '/cart/items/': httpError(409, 'Only 2 available.', 'insufficient_stock') },
    })
    const { user } = renderRoute('/p/fr-pvc-copper-wire')
    await screen.findByRole('heading', { level: 1 })
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Add to cart' })[0]).toBeEnabled())
    await user.click(screen.getAllByRole('button', { name: 'Add to cart' })[0]!)
    expect(await screen.findByText('Only 2 available.')).toBeInTheDocument()
  })

  it('logged-out add to cart goes to login and remembers the item', async () => {
    const api = mockApi({ get: detailRoutes() })
    const { user, router } = renderRoute('/p/fr-pvc-copper-wire')
    await screen.findByRole('heading', { level: 1 })
    await user.click(screen.getAllByRole('button', { name: 'Add to cart' })[0]!)
    expect(currentUrl(router)).toBe('/login?next=%2Fp%2Ffr-pvc-copper-wire')
    expect(api.post).not.toHaveBeenCalled()
    expect(JSON.parse(window.sessionStorage.getItem('boltrun.pending-action')!)).toMatchObject({
      type: 'cart',
      variantId: 201,
      quantity: 1,
    })
  })

  it('shows not-found for an unknown slug and an error with retry for other failures', async () => {
    mockApi({ get: { '/categories/': [], '/products/missing/': httpError(404, 'Not found.') } })
    renderRoute('/p/missing')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('shows a retryable error when the product cannot load', async () => {
    let calls = 0
    mockApi({
      get: {
        ...detailRoutes(),
        '/products/fr-pvc-copper-wire/': () => (++calls === 1 ? httpError(500, 'Server error.') : wireDetail()),
      },
    })
    const { user } = renderRoute('/p/fr-pvc-copper-wire')
    expect(await screen.findByText('Couldn’t load this product')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'FR PVC Insulated Copper Wire' })).toBeInTheDocument()
  })
})
