import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { categories, facets, productPage, productSummary } from '@/test/fixtures'
import { httpError, mockApi, paramsSent } from '@/test/mockApi'
import { currentUrl, renderRoute } from '@/test/utils'

const electrical = categories[0]!
const wire = productSummary({ id: 5, name: 'FR Copper Wire', slug: 'fr-copper-wire', variant_count: 3 })
const switchItem = productSummary({ id: 6, name: 'Modular Switch 6A', slug: 'modular-switch-6a', default_variant_id: 601 })

function routes(overrides: Record<string, unknown> = {}) {
  return {
    '/categories/': categories,
    '/categories/electrical/': electrical,
    '/products/': productPage([wire, switchItem]),
    '/products/facets/': facets(),
    ...overrides,
  }
}

function lastParams(spy: ReturnType<typeof mockApi>['get'], url = '/products/') {
  return paramsSent(spy, url).at(-1)
}

describe('category page and product listing', () => {
  it('loads the category by slug with subcategory navigation, counts and products', async () => {
    const api = mockApi({ get: routes() })
    renderRoute('/c/electrical')

    expect(await screen.findByRole('heading', { level: 1, name: 'Electrical' })).toBeInTheDocument()
    const subnav = screen.getByRole('navigation', { name: 'Electrical subcategories' })
    expect(within(subnav).getByRole('link', { name: /Wires & Cables\s*\(5\)/ })).toHaveAttribute('href', '/c/wires-cables')
    expect(await screen.findByRole('link', { name: 'FR Copper Wire' })).toBeInTheDocument()
    expect(screen.getByText('2 products')).toBeInTheDocument()
    expect(lastParams(api.get)).toMatchObject({ category: 'electrical', page: '1', page_size: '24' })
    expect(document.title).toContain('Electrical')
  })

  it('filters by brand, availability and specification through backend params', async () => {
    const api = mockApi({ get: routes() })
    const { user, router } = renderRoute('/c/electrical')
    await screen.findByRole('link', { name: 'FR Copper Wire' })
    const filters = screen.getByRole('complementary', { name: 'Filters' })

    // Spec filters come from the facets API, so only relevant ones appear for this category.
    expect(within(filters).getByRole('group', { name: 'Cross-sectional area' })).toBeInTheDocument()

    await user.click(within(filters).getByRole('checkbox', { name: /VoltLine/ }))
    await waitFor(() => expect(lastParams(api.get)).toMatchObject({ category: 'electrical', brand: 'voltline' }))

    await user.click(within(filters).getByRole('checkbox', { name: /In stock only/ }))
    await user.click(within(filters).getByRole('checkbox', { name: /1\.5 sq mm/ }))
    await waitFor(() =>
      expect(lastParams(api.get)).toMatchObject({
        brand: 'voltline',
        availability: 'in_stock',
        spec_cross_sectional_area: '1.5',
      }),
    )
    // Facet counts are requested with the same filters (minus sorting/paging).
    expect(lastParams(api.get, '/products/facets/')).toMatchObject({ brand: 'voltline', category: 'electrical' })
    expect(currentUrl(router)).toContain('brand=voltline')

    // Active filters are shown as removable chips.
    await user.click(screen.getByRole('button', { name: 'Remove filter VoltLine' }))
    await waitFor(() => expect(lastParams(api.get)?.brand).toBeUndefined())
  })

  it('sorts on the server', async () => {
    const api = mockApi({ get: routes() })
    const { user } = renderRoute('/c/electrical')
    await screen.findByRole('link', { name: 'FR Copper Wire' })
    const sort = screen.getByRole('combobox', { name: 'Sort products' })
    for (const [label, value] of [
      ['Price: low to high', 'price'],
      ['Price: high to low', '-price'],
      ['Newest first', 'newest'],
      ['Customer rating', 'rating'],
      ['Biggest discount', 'discount'],
    ] as const) {
      await user.selectOptions(sort, label)
      await waitFor(() => expect(lastParams(api.get)).toMatchObject({ ordering: value }))
    }
    // "Relevance" only makes sense when searching.
    expect(within(sort).queryByRole('option', { name: 'Relevance' })).not.toBeInTheDocument()
  })

  it('paginates with backend pages', async () => {
    const api = mockApi({ get: routes({ '/products/': productPage([wire, switchItem], 60) }) })
    const { user } = renderRoute('/c/electrical')
    await screen.findByRole('link', { name: 'FR Copper Wire' })
    const pagination = screen.getByRole('navigation', { name: 'Pagination' })
    expect(within(pagination).getByRole('button', { name: 'Page 3' })).toBeInTheDocument()
    await user.click(within(pagination).getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(lastParams(api.get)).toMatchObject({ page: '2', page_size: '24' }))
  })

  it('shows an empty state with a clear-filters action', async () => {
    mockApi({ get: routes({ '/products/': productPage([]), '/products/facets/': facets({ total: 0 }) }) })
    const { user } = renderRoute('/c/electrical?brand=voltline')
    expect(await screen.findByText('No products found')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Clear filters' })[0]!)
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove filter VoltLine' })).not.toBeInTheDocument())
  })

  it('shows loading skeletons, then an error with retry', async () => {
    let calls = 0
    mockApi({
      get: routes({
        '/products/': () => (++calls === 1 ? httpError(500, 'Server error.') : productPage([wire])),
      }),
    })
    const { user } = renderRoute('/c/electrical')
    expect(await screen.findByRole('status', { name: 'Loading products' })).toBeInTheDocument()
    expect(await screen.findByText('Couldn’t load products')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('link', { name: 'FR Copper Wire' })).toBeInTheDocument()
  })

  it('unknown category slug renders not found', async () => {
    mockApi({ get: routes({ '/categories/nope/': httpError(404, 'Not found.') }) })
    renderRoute('/c/nope')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('mobile filter drawer opens with the same filters', async () => {
    mockApi({ get: routes() })
    const { user } = renderRoute('/c/electrical')
    await screen.findByRole('link', { name: 'FR Copper Wire' })
    await user.click(screen.getByRole('button', { name: /^Filters/ }))
    const drawer = await screen.findByRole('dialog', { name: 'Filters' })
    expect(within(drawer).getByRole('checkbox', { name: /VoltLine/ })).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: 'Show 2 results' })).toBeInTheDocument()
  })
})
