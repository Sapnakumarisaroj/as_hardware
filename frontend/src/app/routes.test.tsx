import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { cart, categories, customer, productPage, productSummary } from '@/test/fixtures'
import { httpError, mockApi, paramsSent } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const drill = productSummary()
const tap = productSummary({ id: 2, name: 'Brass Pillar Tap', slug: 'brass-pillar-tap', default_variant_id: 102 })

function catalogRoutes(products = [drill, tap]) {
  return { '/categories/': categories, '/products/': productPage(products) }
}

describe('homepage', () => {
  it('shows the hero, categories from the API and product sections fed by the listing API', async () => {
    const api = mockApi({ get: catalogRoutes() })
    renderRoute('/')

    expect(screen.getByRole('heading', { level: 1, name: /right part for the job/i })).toBeInTheDocument()
    const categorySection = await screen.findByRole('region', { name: 'Shop by category' })
    expect(await within(categorySection).findByRole('link', { name: /Electrical\s*14 products/ })).toHaveAttribute(
      'href',
      '/c/electrical',
    )
    expect(within(categorySection).getByRole('link', { name: 'Wires & Cables' })).toHaveAttribute('href', '/c/wires-cables')

    for (const title of ['Today’s offers', 'Best sellers', 'Featured products', 'Fast delivery', 'Recently added']) {
      expect(await screen.findByRole('region', { name: title })).toBeInTheDocument()
    }
    // Each section asks the backend for its own slice; nothing is filtered in the browser.
    const sent = paramsSent(api.get, '/products/')
    expect(sent).toContainEqual(expect.objectContaining({ discount: '10', ordering: 'discount' }))
    expect(sent).toContainEqual(expect.objectContaining({ bestseller: 'true', ordering: 'popular' }))
    expect(sent).toContainEqual(expect.objectContaining({ fast_delivery: 'true' }))
    expect(sent).toContainEqual(expect.objectContaining({ ordering: 'newest' }))
    // "Recommended" needs a signed-in shopper with a wishlist.
    expect(screen.queryByRole('region', { name: 'Recommended for you' })).not.toBeInTheDocument()
  })

  it('hides product sections that have no products instead of padding them', async () => {
    mockApi({ get: catalogRoutes([]) })
    renderRoute('/')
    await screen.findByRole('region', { name: 'Shop by category' })
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Best sellers' })).not.toBeInTheDocument())
  })

  it('shows an error with retry when categories cannot load', async () => {
    mockApi({
      get: {
        '/categories/': httpError(500, 'Server error.'),
        '/products/': productPage([]),
      },
    })
    const { user } = renderRoute('/')
    expect(await screen.findByText('Couldn’t load categories')).toBeInTheDocument()
    const retry = screen.getAllByRole('button', { name: 'Retry' })[0]
    await user.click(retry!)
    expect(await screen.findByText('Couldn’t load categories')).toBeInTheDocument()
  })
})

describe('header', () => {
  it('logged out: offers Login / Register and loads categories into the navigation', async () => {
    mockApi({ get: catalogRoutes() })
    renderRoute('/')
    expect(screen.getByRole('link', { name: /Login \/ Register/ })).toHaveAttribute('href', '/login')
    const nav = await screen.findByRole('navigation', { name: 'Product categories' })
    expect(within(nav).getByRole('link', { name: 'Tools' })).toHaveAttribute('href', '/c/tools')
    expect(within(nav).getByRole('link', { name: /Drills/ })).toHaveAttribute('href', '/c/drills')
    expect(within(screen.getByRole('banner')).getByRole('link', { name: 'Cart' })).toHaveAttribute('href', '/cart')
  })

  it('logged in: shows the account menu with orders and logout, and the cart count', async () => {
    signIn()
    mockApi({
      get: {
        ...catalogRoutes(),
        '/auth/me/': customer,
        '/wishlist/': [],
        '/search/recent/': [],
        '/cart/': cart({
          items: [
            {
              id: 1,
              variant_id: 101,
              sku: 'DEMO-DRILL',
              product_id: 1,
              product_name: 'Impact Drill 650W',
              product_slug: 'impact-drill-650w',
              variant_name: '',
              quantity: 3,
              unit_price: '3200.00',
              unit_mrp: '4000.00',
              price_at_add: '3200.00',
              price_changed: false,
              line_total: '9600.00',
              available_quantity: 8,
              in_stock: true,
              purchasable: true,
            },
          ],
        }),
      },
    })
    renderRoute('/')
    const menu = (await screen.findByText('Account menu')).closest('details') as HTMLElement
    expect(within(menu).getByText('Asha')).toBeInTheDocument()
    expect(within(menu).getByRole('link', { name: 'Orders' })).toHaveAttribute('href', '/account/orders')
    expect(within(menu).getByRole('button', { name: 'Logout' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Login \/ Register/ })).not.toBeInTheDocument()
    expect(await screen.findByText('3')).toBeInTheDocument()
    expect(screen.getByText('items in cart')).toBeInTheDocument()
  })
})

describe('routing', () => {
  it('unknown paths render the 404 page', () => {
    mockApi({ get: catalogRoutes() })
    renderRoute('/definitely-not-a-page')
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
