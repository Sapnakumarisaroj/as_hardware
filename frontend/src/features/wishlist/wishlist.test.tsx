import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { cart, customer, productPage, productSummary } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const drill = productSummary()
const facetsStub = {
  total: 1,
  categories: [],
  brands: [],
  price: { min: null, max: null },
  ratings: [],
  discounts: [],
  availability: { in_stock: 1, fast_delivery: 1 },
  specifications: [],
}

function signedInRoutes(wishlist: unknown) {
  return {
    '/categories/': [],
    '/auth/me/': customer,
    '/cart/': cart(),
    '/search/recent/': [],
    '/wishlist/': wishlist,
    '/products/': productPage([drill]),
    '/products/facets/': facetsStub,
  }
}

describe('wishlist', () => {
  it('logged out: the heart asks to log in and remembers the product for after login', async () => {
    const api = mockApi({ get: { '/categories/': [], '/products/': productPage([drill]), '/products/facets/': facetsStub } })
    const { user, router } = renderRoute('/products')
    await user.click(await screen.findByRole('button', { name: 'Save Impact Drill 650W to wishlist' }))

    expect(currentUrl(router)).toBe('/login?next=%2Fproducts')
    expect(await screen.findByText(/Login to save items/)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
    expect(JSON.parse(window.sessionStorage.getItem('boltrun.pending-action')!)).toMatchObject({
      type: 'wishlist',
      productId: 1,
    })
  })

  it('logged in: toggles add and remove through the wishlist API', async () => {
    signIn()
    let saved = false
    const api = mockApi({
      get: { ...signedInRoutes(() => (saved ? [{ product: drill, added_at: '2026-09-24T10:00:00Z' }] : [])) },
      post: { '/wishlist/': () => ((saved = true), null) },
      delete: { '/wishlist/1/': () => ((saved = false), null) },
    })
    const { user } = renderRoute('/products')
    await screen.findByText('Account menu')

    await user.click(await screen.findByRole('button', { name: 'Save Impact Drill 650W to wishlist' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/wishlist/', { product_id: 1 }))
    const remove = await screen.findByRole('button', { name: 'Remove Impact Drill 650W from wishlist' })
    expect(remove).toHaveAttribute('aria-pressed', 'true')

    await user.click(remove)
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/wishlist/1/'))
    expect(await screen.findByRole('button', { name: 'Save Impact Drill 650W to wishlist' })).toBeInTheDocument()
  })

  it('completes the remembered wishlist action after signing in', async () => {
    window.sessionStorage.setItem(
      'boltrun.pending-action',
      JSON.stringify({ type: 'wishlist', productId: 1, productName: 'Impact Drill 650W' }),
    )
    signIn()
    const api = mockApi({ get: signedInRoutes([]), post: { '/wishlist/': null } })
    renderRoute('/')
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/wishlist/', { product_id: 1 }))
    expect(await screen.findByText('Saved to wishlist: Impact Drill 650W')).toBeInTheDocument()
  })

  it('wishlist page: sign-in prompt, empty state, items and error states', async () => {
    mockApi({ get: { '/categories/': [] } })
    const anonymous = renderRoute('/wishlist')
    expect(await screen.findByText('Login to save items and see them here.')).toBeInTheDocument()
    anonymous.unmount()

    signIn()
    mockApi({ get: signedInRoutes([]) })
    const empty = renderRoute('/wishlist')
    expect(await screen.findByText('No saved items yet')).toBeInTheDocument()
    empty.unmount()

    mockApi({ get: signedInRoutes([{ product: drill, added_at: '2026-09-24T10:00:00Z' }]) })
    const full = renderRoute('/wishlist')
    expect(await screen.findByRole('heading', { name: 'Wishlist (1)' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Impact Drill 650W' })).toBeInTheDocument()
    full.unmount()

    mockApi({ get: signedInRoutes(httpError(500, 'Server error.')) })
    renderRoute('/wishlist')
    expect(await screen.findByText('Couldn’t load your wishlist')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
