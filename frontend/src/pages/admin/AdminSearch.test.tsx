import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { SearchExplanation, SearchIndexStatus } from '@/features/admin/types'
import { staffGet } from '@/test/adminFixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

function indexStatus(overrides: Partial<SearchIndexStatus> = {}): SearchIndexStatus {
  return {
    embedder: {
      kind: 'sentence_transformers',
      key: 'st:paraphrase-multilingual-MiniLM-L12-v2',
      available: true,
      dimensions: 384,
      model: 'paraphrase-multilingual-MiniLM-L12-v2',
      loaded: true,
    },
    search_backend: 'hybrid',
    products: 39,
    indexed: 38,
    missing: 1,
    stale: 0,
    other_embedder: 0,
    last_updated: '2026-10-01T10:00:00Z',
    ready: true,
    ...overrides,
  }
}

const explanation: SearchExplanation = {
  mode: 'hybrid',
  embedder: 'sentence_transformers',
  terms: ['diwar', 'hole'],
  related_terms: ['drill', 'wall plug'],
  matched: 'related',
  results: [
    {
      product_id: 4,
      name: 'Corded Impact Drill 650W',
      keyword: 0,
      related: 24,
      semantic: 0.61,
      cosine: 0.72,
      final: 39,
      reason: { type: 'related', text: 'For “hole”: drill' },
    },
  ],
}

describe('admin: search index', () => {
  it('shows the index status, updates it and explains how a query is ranked', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/search/index/': indexStatus(), '/admin/search/explain/': explanation }),
      post: {
        '/admin/search/index/rebuild/': {
          result: { embedded: 1, unchanged: 38, removed: 0, failed: [] },
          status: indexStatus({ indexed: 39, missing: 0 }),
        },
        '/admin/search/index/products/4/': { status: indexStatus() },
      },
    })
    const { user } = renderRoute('/admin/search')

    expect(await screen.findByRole('heading', { name: 'Search', level: 1 })).toBeInTheDocument()
    expect(screen.getByText('Needs an update')).toBeInTheDocument()
    expect(screen.getByText('paraphrase-multilingual-MiniLM-L12-v2')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Update index' }))
    expect(await screen.findByText('Index updated: 1 embedded, 38 unchanged, 0 removed.')).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/admin/search/index/rebuild/', { force: false })

    await user.type(screen.getByLabelText('Re-index one product (ID)'), '4')
    await user.click(screen.getByRole('button', { name: 'Re-index' }))
    expect(await screen.findByText('Product 4 re-indexed.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('What a customer might type'), 'diwar me hole')
    await user.click(screen.getByRole('button', { name: 'Explain' }))
    const table = await screen.findByRole('table', { name: 'Ranking' })
    const row = within(table).getByRole('row', { name: /Corded Impact Drill 650W/ })
    expect(row).toHaveTextContent('For “hole”: drill')
    expect(row).toHaveTextContent('0.72')
    expect(screen.getByText(/understood as: drill, wall plug/)).toBeInTheDocument()
  })

  it('a full rebuild asks first', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/search/index/': indexStatus({ missing: 0, indexed: 39 }) }),
      post: {
        '/admin/search/index/rebuild/': {
          result: { embedded: 39, unchanged: 0, removed: 0, failed: [] },
          status: indexStatus({ missing: 0, indexed: 39 }),
        },
      },
    })
    const { user } = renderRoute('/admin/search')
    expect(await screen.findByText('Up to date')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Rebuild everything' }))
    const dialog = await screen.findByRole('dialog', { name: 'Rebuild the whole search index?' })
    expect(api.post).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Rebuild' }))
    expect(await screen.findByText('Rebuilt: 39 products embedded.')).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/admin/search/index/rebuild/', { force: true })
  })

  it('says keyword search keeps working when the model is unavailable, and disables the updates', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', {
        '/admin/search/index/': indexStatus({
          embedder: { kind: 'sentence_transformers', key: 'st:x', available: false, dimensions: 0, model: 'x' },
          ready: false,
        }),
      }),
    })
    renderRoute('/admin/search')
    expect(await screen.findByText('Keyword search only')).toBeInTheDocument()
    expect(screen.getByText(/Customers get keyword search meanwhile/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Update index' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Rebuild everything' })).toBeDisabled()
  })

  it('shows a retry when the status cannot be loaded', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/search/index/': httpError(500, 'Server error', 'server_error') }) })
    renderRoute('/admin/search')
    expect(await screen.findByText('Couldn’t load the search index')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
