import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { SmartCart, SmartSuggestion } from '@/features/shopping/types'
import { cart, cartLine, customer, productSummary } from '@/test/fixtures'
import { mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

import { visibleSections } from './sections'

/* Smart cart sections added with co-purchases, pack sizes, kit completion and relevant free-delivery add-ons:
   each shows its reason, acts only on a click, and a section with nothing to act on is hidden. */

const shopGet = { '/categories/': [], '/wishlist/': [], '/search/recent/': [], '/addresses/': [] }
const screws = productSummary({ id: 31, name: 'Wood Screws', slug: 'wood-screws', default_variant_id: 310 })
const lines = [cartLine({ id: 1, variant_id: 11 }), cartLine({ id: 2, variant_id: 12 })]

function smart(sections: SmartCart['sections']): SmartCart {
  return { empty: false, summary: null, titles: {}, top_actions: [], sections }
}

function render(data: SmartCart) {
  signIn()
  const api = mockApi({
    get: { ...shopGet, '/auth/me/': customer, '/cart/': cart({ items: lines }), '/shopping/cart/': data },
    post: { '/cart/items/': cart({ items: lines }), '/cart/items/1/replace/': cart({ items: lines }) },
  })
  return { api, ...renderRoute('/cart') }
}

const gapOnly: SmartSuggestion = { type: 'free_delivery', message: 'Add ₹600 more for free delivery (saves the ₹40 fee).', action: null, priority: 50, gap: '600.00' }

describe('smart cart sections', () => {
  it('hides empty sections and a free-delivery gap with nothing relevant to add', () => {
    const data = smart([
      { key: 'also_bought', title: 'Customers also bought', items: [] },
      { key: 'free_delivery', title: 'Free delivery opportunity', items: [gapOnly] },
      { key: 'packs', title: 'Cheaper pack size', items: [{ type: 'pack_size', message: 'Box of 50 is cheaper.', action: 'replace', priority: 60, cart_item_id: 1, variant_id: 99, quantity: 1 }] },
    ])
    expect(visibleSections(data).map((s) => s.key)).toEqual(['packs'])
    expect(visibleSections(smart([{ key: 'free_delivery', title: 'Free delivery opportunity', items: [gapOnly] }]))).toEqual([])
  })

  it('renders nothing when every section is empty', async () => {
    render(smart([{ key: 'also_bought', title: 'Customers also bought', items: [] }]))
    await screen.findByLabelText('My budget (₹)')
    expect(screen.queryByRole('region', { name: 'Smart cart' })).not.toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Customers also bought' })).not.toBeInTheDocument()
  })

  it('shows the reason, changes to a cheaper pack size after confirming, and adds a kit’s missing lines', async () => {
    const { api, user } = render(
      smart([
        {
          key: 'packs',
          title: 'Cheaper pack size',
          items: [
            {
              type: 'pack_size',
              message: 'Steel Nails: 1 × 50 pcs costs ₹90 instead of ₹120 for 40 × Single (save ₹30).',
              reason: 'Same product in another pack size; covers 50 pcs for the 40 you have.',
              action: 'replace',
              priority: 60,
              cart_item_id: 1,
              variant_id: 99,
              quantity: 1,
              saving: '30.00',
            },
          ],
        },
        {
          key: 'bundles',
          title: 'Complete the set',
          items: [
            {
              type: 'complete_kit',
              message: 'Completing a wall drilling job? Add screws for ₹40.',
              reason: 'You have 2 of the 3 materials of the wall drilling kit.',
              action: 'add_lines',
              priority: 24,
              kit: { key: 'wall_drilling', name: 'Wall drilling' },
              lines: [{ product_id: 31, variant_id: 310, quantity: 1, label: 'Screws', name: 'Wood Screws', unit_price: '40.00', line_total: '40.00', product: screws }],
            },
          ],
        },
        {
          key: 'also_bought',
          title: 'Customers also bought',
          items: [{ type: 'add', message: 'Customers who bought the drill also bought this.', reason: 'Bought together in 3 orders (60% of orders with it).', action: 'add', priority: 32, product_id: 31, variant_id: 310, quantity: 1 }],
        },
      ]),
    )
    const packs = await screen.findByRole('list', { name: 'Cheaper pack size' })
    expect(packs).toHaveTextContent('Why: Same product in another pack size')
    await user.click(within(packs).getByRole('button', { name: 'Replace' }))
    expect(screen.getByText('Change to this pack size?')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Yes, replace' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/1/replace/', { variant_id: 99, quantity: 1 }))

    const set = screen.getByRole('list', { name: 'Complete the set' })
    expect(within(set).getByRole('list', { name: 'Missing from Wall drilling' })).toHaveTextContent('Wood Screws')
    await user.click(within(set).getByRole('button', { name: 'Add the missing items' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/', { variant_id: 310, quantity: 1 }))
    expect(screen.getByRole('list', { name: 'Customers also bought' })).toHaveTextContent('Bought together in 3 orders')
  })
})
