import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { cart, cartLine, categories, customer, productPage, productSummary } from '@/test/fixtures'
import { httpError, mockApi, paramsSent } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const drill = productSummary()
const tap = productSummary({ id: 2, name: 'Brass Pillar Tap', slug: 'brass-pillar-tap', default_variant_id: 102 })

function catalogRoutes(products = [drill, tap]) {
  return { '/categories/': categories, '/products/': productPage(products) }
}

describe('homepage', () => {
  it('shows search, departments from the API and sections fed by the listing API', async () => {
    const api = mockApi({ get: catalogRoutes() })
    renderRoute('/')

    expect(screen.getByRole('heading', { level: 1, name: /find the right hardware/i })).toBeInTheDocument()
    expect(screen.getByTestId('deliver-to-message')).toHaveTextContent('Choose your PIN code')
    const departments = await screen.findByRole('region', { name: 'Shop by department' })
    expect(await within(departments).findByRole('link', { name: /Electrical\s*14 products/ })).toHaveAttribute(
      'href',
      '/c/electrical',
    )
    expect(within(departments).getByRole('link', { name: /Tools/ })).toHaveTextContent('Drills')

    // Department rails are the catalogue's departments; curated-list fallbacks use live data.
    for (const title of ['Electrical', 'Tools', 'Best sellers', 'New arrivals', 'Bulk buying']) {
      expect(await screen.findByRole('region', { name: title })).toBeInTheDocument()
    }
    expect(screen.getByRole('region', { name: 'Not sure what you need?' })).toBeInTheDocument()
    const sent = paramsSent(api.get, '/products/')
    expect(sent).toContainEqual(expect.objectContaining({ category: 'electrical', ordering: 'popular' }))
    expect(sent).toContainEqual(expect.objectContaining({ bestseller: 'true', ordering: 'popular' }))
    expect(sent).toContainEqual(expect.objectContaining({ bulk_pricing: 'true' }))
    // No PIN: no fast-delivery section and no PIN sent; no history: no recently viewed / recommended.
    expect(sent.some((params) => 'fast_delivery' in params || 'postal_code' in params)).toBe(false)
    expect(screen.queryByRole('region', { name: 'Fast delivery to you' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Recently viewed' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Recommended for you' })).not.toBeInTheDocument()
  })

  it('shows the shop’s curated lists with their own names and the fast rail for a fast PIN', async () => {
    window.localStorage.setItem('boltrun.delivery-pincode', '411038')
    const api = mockApi({
      get: {
        ...catalogRoutes(),
        '/collections/': [
          { id: 1, name: 'Deals of the week', slug: 'deals', description: 'This week', rule: 'manual', starts_at: null, ends_at: null, products: [tap] },
          { id: 2, name: 'Bulk savings', slug: 'bulk', description: '', rule: 'bulk_pricing', starts_at: null, ends_at: null, products: [drill] },
        ],
        '/delivery/check/': {
          serviceable: true, postal_code: '411038', location_precision: 'pin', fast_delivery_available: true,
          label: 'Delivery in 18 minutes', fast_unavailable_reason: '', message: '⚡ Fast delivery available · Delivery in 18 minutes', stores: [],
        },
      },
    })
    renderRoute('/')
    expect(await screen.findByRole('region', { name: 'Deals of the week' })).toHaveTextContent('Brass Pillar Tap')
    expect(await screen.findByRole('region', { name: 'Bulk savings' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Bulk buying' })).not.toBeInTheDocument() // the shop's list replaces it
    expect(await screen.findByTestId('deliver-to-message')).toHaveTextContent('Delivery in 18 minutes')
    expect(await screen.findByRole('region', { name: 'Fast delivery to you' })).toHaveTextContent('Delivery in 18 minutes to 411038')
    expect(paramsSent(api.get, '/products/')).toContainEqual(
      expect.objectContaining({ fast_delivery: 'true', postal_code: '411038' }),
    )
    expect(paramsSent(api.get, '/collections/')).toContainEqual({ postal_code: '411038' })
  })

  it('shows recently viewed products, in viewing order, and recommends from them', async () => {
    window.localStorage.setItem('boltrun.recently-viewed', JSON.stringify(['brass-pillar-tap', 'impact-drill-650w']))
    const api = mockApi({ get: catalogRoutes() })
    renderRoute('/')
    const recent = await screen.findByRole('region', { name: 'Recently viewed' })
    const names = within(recent).getAllByRole('article').map((card) => within(card).getByRole('heading').textContent)
    expect(names).toEqual(['Brass Pillar Tap', 'Impact Drill 650W'])
    expect(paramsSent(api.get, '/products/')).toContainEqual(
      expect.objectContaining({ slugs: 'brass-pillar-tap,impact-drill-650w' }),
    )
    expect(await screen.findByRole('region', { name: 'Recommended for you' })).toBeInTheDocument()
  })

  it('hides product sections that have no products instead of padding them', async () => {
    mockApi({ get: catalogRoutes([]) })
    renderRoute('/')
    await screen.findByRole('region', { name: 'Shop by department' })
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Best sellers' })).not.toBeInTheDocument())
    expect(screen.queryByRole('region', { name: 'Electrical' })).not.toBeInTheDocument()
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
        '/cart/': cart({ items: [cartLine({ id: 1, quantity: 3 })] }),
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
