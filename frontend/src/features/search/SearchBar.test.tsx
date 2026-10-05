import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { customer, facets, productPage, productSummary } from '@/test/fixtures'
import { mockApi, paramsSent } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const drill = productSummary()
const suggestions = {
  query: 'dri',
  products: [drill],
  categories: [{ name: 'Drills', slug: 'drills', parent_name: 'Tools' }],
  brands: [{ name: 'DrillCo', slug: 'drillco' }],
}

function routes(extra: Record<string, unknown> = {}) {
  return {
    '/categories/': [],
    '/products/': productPage([drill]),
    '/products/facets/': facets({ total: 1, specifications: [] }),
    '/search/suggest/': suggestions,
    ...extra,
  }
}

function searchBox() {
  return within(screen.getByRole('banner')).getByRole('combobox', { name: 'Search products' })
}

describe('search', () => {
  it('shows type-ahead suggestions for products, categories and brands', async () => {
    const api = mockApi({ get: routes() })
    const { user, router } = renderRoute('/')
    await user.type(searchBox(), 'dri')

    const list = await screen.findByRole('listbox', { name: 'Search suggestions' })
    expect(within(list).getByRole('option', { name: /Search for “dri”/ })).toBeInTheDocument()
    expect(await within(list).findByRole('option', { name: /Impact Drill 650W/ })).toBeInTheDocument()
    expect(within(list).getByRole('option', { name: /Drills\s*in Tools/ })).toBeInTheDocument()
    expect(within(list).getByRole('option', { name: /DrillCo/ })).toBeInTheDocument()
    expect(paramsSent(api.get, '/search/suggest/').at(-1)).toEqual({ q: 'dri' })

    // Keyboard: arrow down to the product and press Enter to jump straight to it.
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    await waitFor(() => expect(currentUrl(router)).toBe('/p/impact-drill-650w')) // the page loads on demand
  })

  it('submitting runs a backend search with a result count and relevance sort', async () => {
    const api = mockApi({ get: routes() })
    const { user, router } = renderRoute('/')
    await user.type(searchBox(), 'bosch drill{Enter}')

    await waitFor(() => expect(currentUrl(router)).toBe('/search?q=bosch%20drill'))
    expect(await screen.findByRole('heading', { level: 1, name: 'Results for “bosch drill”' })).toBeInTheDocument()
    expect(await screen.findByText('1 product')).toBeInTheDocument()
    expect(paramsSent(api.get, '/products/').at(-1)).toMatchObject({ q: 'bosch drill' })
    expect(screen.getByRole('combobox', { name: 'Sort products' })).toHaveValue('relevance')
    // The header box keeps the query so it can be refined.
    expect(searchBox()).toHaveValue('bosch drill')
  })

  it('clear button empties the box', async () => {
    mockApi({ get: routes() })
    const { user } = renderRoute('/')
    await user.type(searchBox(), 'pipe')
    await user.click(screen.getByRole('button', { name: 'Clear search' }))
    expect(searchBox()).toHaveValue('')
    expect(searchBox()).toHaveFocus()
  })

  it('no results shows a helpful empty state', async () => {
    mockApi({ get: routes({ '/products/': productPage([]), '/products/facets/': facets({ total: 0 }) }) })
    renderRoute('/search?q=zzzz')
    expect(await screen.findByText('No results for “zzzz”')).toBeInTheDocument()
    expect(screen.getByText(/Check the spelling/)).toBeInTheDocument()
  })

  it('tells the shopper when only some words matched', async () => {
    mockApi({
      get: routes({
        '/products/': { ...productPage([drill]), search: { query: 'drill unicorn', matched: 'some_terms' } },
      }),
    })
    renderRoute('/search?q=drill%20unicorn')
    expect(await screen.findByText(/No products match every word in “drill unicorn”/)).toBeInTheDocument()
  })

  it('explains meaning-based results: what we understood and why each product is shown', async () => {
    const related = productSummary({ match_type: 'related', match_reason: 'Suits “drilling”: it is a drill' })
    const exact = productSummary({
      id: 9,
      name: 'Drill Bit Set',
      slug: 'drill-bit-set',
      match_type: 'keyword',
      match_reason: 'Matches your search',
    })
    mockApi({
      get: routes({
        '/products/': {
          ...productPage([related, exact]),
          search: {
            query: 'machine for drilling',
            matched: 'related',
            mode: 'hybrid',
            related_terms: ['drill', 'drill bit'],
          },
        },
      }),
    })
    renderRoute('/search?q=machine%20for%20drilling')
    expect(await screen.findByText(/we searched for what you probably mean/)).toHaveTextContent(
      'We didn’t find those exact words in “machine for drilling”, so we searched for what you probably mean: drill, drill bit.',
    )
    expect(screen.getAllByTestId('match-reason')).toHaveLength(1) // obvious keyword matches need no explanation
    expect(screen.getByTestId('match-reason')).toHaveTextContent('Suits “drilling”: it is a drill')
  })

  it('type-ahead shows why a suggested product matches', async () => {
    mockApi({
      get: routes({
        '/search/suggest/': {
          ...suggestions,
          products: [productSummary({ match_reason: 'Suits “hole”: it is a drill' })],
        },
      }),
    })
    const { user } = renderRoute('/')
    await user.type(searchBox(), 'hole in wall')
    const list = await screen.findByRole('listbox', { name: 'Search suggestions' })
    expect(await within(list).findByRole('option', { name: /Impact Drill 650W.*Suits “hole”/ })).toBeInTheDocument()
  })

  it('signed-in shoppers see and can clear recent searches; searches are recorded', async () => {
    signIn()
    const api = mockApi({
      get: routes({
        '/auth/me/': customer,
        '/wishlist/': [],
        '/cart/': { id: 1, items: [], totals: {}, issues: [], can_checkout: false },
        '/search/recent/': [{ query: 'water tap', searched_at: '2026-09-20T10:00:00Z' }],
      }),
      post: { '/search/recent/': { query: 'pvc pipe', searched_at: '2026-09-24T10:00:00Z' } },
      delete: { '/search/recent/': null },
    })
    const { user } = renderRoute('/')
    await screen.findByText('Account menu')
    await user.click(searchBox())
    const list = await screen.findByRole('listbox', { name: 'Search suggestions' })
    expect(within(list).getByRole('option', { name: /water tap/ })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Clear' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/search/recent/'))

    await user.type(searchBox(), 'pvc pipe{Enter}')
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/search/recent/', { query: 'pvc pipe' }))
  })
})
