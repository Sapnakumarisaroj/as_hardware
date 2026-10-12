import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { approvedCategories, cart, cartLine, customer, productPage, productSummary } from '@/test/fixtures'
import { httpError, mockApi, paramsSent } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const drill = productSummary()
const tap = productSummary({ id: 2, name: 'Brass Pillar Tap', slug: 'brass-pillar-tap', default_variant_id: 102 })

function catalogRoutes(products = [drill, tap]) {
  return { '/categories/': approvedCategories, '/products/': productPage(products) }
}

describe('homepage', () => {
  it('shows search, departments from the API and sections fed by the listing API', async () => {
    const api = mockApi({ get: { ...catalogRoutes(), '/delivery/promise/': { fast_delivery_max_minutes: 60 } } })
    renderRoute('/')

    expect(screen.getByRole('heading', { level: 1, name: 'Hardware for every project' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Shop now/ })).toHaveAttribute('href', '/products')
    expect(screen.getByRole('link', { name: 'Browse categories' })).toHaveAttribute('href', '#categories')
    // Delivery lives in the header's selector; there is no separate delivery bar on the page.
    expect(within(screen.getByRole('banner')).getByRole('button', { name: /Deliver to\s*Select location/ })).toBeInTheDocument()
    expect(screen.queryByTestId('deliver-to-message')).not.toBeInTheDocument()
    const groups = await screen.findByRole('region', { name: 'Shop by category' })
    expect(within(groups).getByRole('link', { name: 'Tools & Safety' })).toHaveAttribute('href', '/shop/tools-safety')
    expect(within(groups).getByRole('link', { name: 'Hinges, Channels & Handles' })).toHaveAttribute('href', '/c/hinges-channels-handles')

    // Curated-list fallbacks and the popular grid use live data (three general rows at most); departments are reached through the category cards.
    for (const title of ['Best sellers', 'New arrivals', 'Popular hardware', 'Bulk buying']) {
      expect(await screen.findByRole('region', { name: title })).toBeInTheDocument()
    }
    expect(screen.queryByRole('region', { name: 'Plywood, MDF & HDHMR' })).not.toBeInTheDocument()
    const tools = screen.getByRole('region', { name: 'Smarter way to buy hardware' })
    expect(within(tools).getByRole('link', { name: /AI assistant/ })).toHaveAttribute('href', '/ai-assistant')
    expect(within(tools).getAllByRole('link')).toHaveLength(6)
    expect(screen.getByRole('region', { name: 'Fast hardware delivery across Bengaluru' })).toHaveTextContent('Fast delivery within 60 mins')
    const trust = screen.getByRole('region', { name: 'Why shop with us' })
    expect(trust).toHaveTextContent('Within 60 mins where eligible')
    expect(trust).toHaveTextContent('Bulk pricing') // products with bulk prices exist
    expect(trust).not.toHaveTextContent('Cash on delivery') // decided per shop, store and zone at checkout
    const sent = paramsSent(api.get, '/products/')
    expect(sent).toContainEqual(expect.objectContaining({ ordering: 'popular', in_stock: 'true' }))
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
        '/delivery/promise/': { fast_delivery_max_minutes: 60 },
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
    expect(await screen.findByTestId('pin-summary')).toHaveTextContent('Delivery in 18 minutes')
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
    await screen.findByRole('region', { name: 'Shop by category' })
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Best sellers' })).not.toBeInTheDocument())
    expect(screen.queryByRole('region', { name: 'Plywood, MDF & HDHMR' })).not.toBeInTheDocument()
  })

  it('with the API down keeps the shop’s groups and leaves out every section it can’t fill', async () => {
    mockApi({
      get: {
        '/categories/': httpError(500, 'Server error.'),
        '/products/': httpError(500, 'Server error.'),
      },
    })
    renderRoute('/')
    // The four groups from the shop's own table, linking to the real category pages.
    const groups = await screen.findByRole('region', { name: 'Shop by category' })
    expect(within(groups).getByRole('link', { name: 'Tools & Safety' })).toHaveAttribute('href', '/shop/tools-safety')
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Popular hardware' })).not.toBeInTheDocument())
    for (const title of ['Best sellers', 'New arrivals', 'Bulk buying', 'Fast delivery to you']) {
      expect(screen.queryByRole('region', { name: title })).not.toBeInTheDocument()
    }
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    // No delivery promise configured/loaded: nothing about fast delivery is claimed.
    expect(screen.getByRole('region', { name: 'Hardware delivery across Bengaluru' })).not.toHaveTextContent(/fast/i)
    expect(screen.getByRole('region', { name: 'Why shop with us' })).not.toHaveTextContent('Fast delivery')
    expect(screen.getByTestId('hero-delivery')).not.toHaveTextContent(/fast/i)
    expect(screen.queryByTestId('fast-badge')).not.toBeInTheDocument()
  })

  it('caps the general product rows at three, the shop’s curated lists first', async () => {
    const list = (id: number, name: string) => ({
      id, name, slug: `list-${id}`, description: '', rule: 'manual', starts_at: null, ends_at: null, products: [tap],
    })
    mockApi({ get: { ...catalogRoutes(), '/collections/': [list(1, 'Deals'), list(2, 'Essentials'), list(3, 'Plumbing picks'), list(4, 'Fourth list')] } })
    renderRoute('/')
    for (const title of ['Deals', 'Essentials', 'Plumbing picks']) {
      expect(await screen.findByRole('region', { name: title })).toBeInTheDocument()
    }
    expect(screen.queryByRole('region', { name: 'Fourth list' })).not.toBeInTheDocument()
    // Best sellers / new arrivals aren't curated but the cap is reached, so they aren't added.
    expect(screen.queryByRole('region', { name: 'Best sellers' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Popular hardware' })).not.toBeInTheDocument()
  })

  it('a PIN we don’t serve: no fast claims, a clear message, and every card says so', async () => {
    window.localStorage.setItem('boltrun.delivery-pincode', '999999')
    mockApi({
      get: {
        ...catalogRoutes(),
        '/delivery/promise/': { fast_delivery_max_minutes: 60 },
        '/delivery/check/': {
          serviceable: false, postal_code: '999999', location_precision: 'pin', fast_delivery_available: false,
          label: '', fast_unavailable_reason: '', message: 'We don’t deliver to 999999 yet.', stores: [],
        },
      },
    })
    renderRoute('/')
    await waitFor(() => expect(screen.getByTestId('hero-delivery')).toHaveTextContent('We don’t deliver to 999999 yet.'))
    expect(screen.getByTestId('hero-delivery')).not.toHaveTextContent(/fast/i)
    expect(screen.queryByTestId('fast-badge')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Why shop with us' })).not.toHaveTextContent('Fast delivery')
    const best = await screen.findByRole('region', { name: 'Best sellers' })
    await waitFor(() => expect(within(best).getAllByTestId('not-served')[0]).toHaveTextContent('We don’t deliver to 999999 yet'))
    expect(within(best).queryByTestId('pin-prompt')).not.toBeInTheDocument()
  })
})

describe('header', () => {
  it('logged out: offers Login and loads categories into the navigation', async () => {
    mockApi({ get: catalogRoutes() })
    const { user } = renderRoute('/')
    expect(screen.getByRole('link', { name: 'Login' })).toHaveAttribute('href', '/login')
    expect(screen.queryByRole('link', { name: /register|sign up|create an account/i })).not.toBeInTheDocument()
    const main = await screen.findByRole('navigation', { name: 'Main' })
    const tools = await within(main).findByRole('button', { name: 'Tools & Safety' })
    await user.click(tools)
    const panel = document.getElementById(tools.getAttribute('aria-controls')!)!
    expect(within(panel).getByRole('link', { name: /^Power Tools\s/ })).toHaveAttribute('href', '/c/power-tools')
    expect(within(panel).getByRole('link', { name: /^Safety Tools/ })).toHaveAttribute('href', '/c/safety')
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
