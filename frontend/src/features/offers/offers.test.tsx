import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  address,
  cart,
  cartLine,
  categories,
  checkoutPreview,
  customer,
  orderDetail,
  productPage,
  productSummary,
  TOTALS_800,
  wireDetail,
} from '@/test/fixtures'
import { mockApi, type RequestInfo } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const toolsOffer = { id: 3, name: 'Tools week', badge: '10% off (up to ₹400)', min_order_value: '1500.00' }
const facets = {
  total: 1,
  categories: [],
  brands: [],
  price: { min: null, max: null },
  ratings: [],
  discounts: [],
  availability: { in_stock: 1, fast_delivery: 1 },
  specifications: [],
}
const signedIn = { '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [] }

describe('automatic offers', () => {
  it('product cards show the offer badge (not on out-of-stock items)', async () => {
    mockApi({
      get: {
        '/categories/': [],
        '/products/': productPage([
          productSummary({ offer: toolsOffer }),
          productSummary({ id: 2, name: 'Sold out drill', slug: 'sold-out', stock_status: 'out_of_stock', offer: toolsOffer }),
        ]),
        '/products/facets/': facets,
      },
    })
    renderRoute('/products')
    const [first, second] = await screen.findAllByRole('article')
    expect(within(first!).getByText('10% off (up to ₹400)')).toBeInTheDocument()
    expect(within(first!).getByText('Offer:')).toBeInTheDocument() // screen-reader prefix: not colour alone
    expect(within(second!).queryByText('10% off (up to ₹400)')).not.toBeInTheDocument()
  })

  it('product page explains the offer is applied in the cart automatically', async () => {
    mockApi({
      get: {
        '/categories/': [],
        '/products/fr-pvc-copper-wire/': wireDetail({ offer: toolsOffer }),
        '/products/fr-pvc-copper-wire/reviews/': { count: 0, next: null, previous: null, results: [] },
        '/products/': productPage([]),
      },
    })
    renderRoute('/p/fr-pvc-copper-wire')
    const note = await screen.findByRole('note')
    expect(note).toHaveTextContent('Offer: Tools week — 10% off (up to ₹400)')
    expect(note).toHaveTextContent('when eligible items total ₹1,500 or more')
    expect(note).toHaveTextContent('No code needed')
  })

  it('homepage lists live offers with a link to shop them', async () => {
    mockApi({
      get: {
        '/categories/': categories,
        '/products/': productPage([]),
        '/offers/': [
          {
            id: 3,
            name: 'Tools week',
            description: '10% off all tools',
            badge: '10% off',
            min_order_value: '0.00',
            ends_at: null,
            applies_to_everything: false,
            categories: [{ name: 'Tools', slug: 'tools' }],
            products: [],
          },
        ],
      },
    })
    renderRoute('/')
    const section = await screen.findByRole('region', { name: 'Offers running now' })
    expect(within(section).getByText('Tools week')).toBeInTheDocument()
    expect(within(section).getByRole('link', { name: /Shop Tools/ })).toHaveAttribute('href', '/c/tools')
  })

  it('cart shows applied offers in the summary and how much more unlocks another', async () => {
    signIn()
    mockApi({
      get: {
        ...signedIn,
        '/categories/': [],
        '/cart/': cart({
          items: [cartLine()],
          can_checkout: true,
          totals: { ...TOTALS_800, offer_discount: '80.00', discount_total: '80.00', grand_total: '720.00' },
          offers: {
            applied: [{ id: 3, name: 'Tools week', description: '', badge: '10% off', discount: '80.00', variant_ids: [201] }],
            missed: [{ id: 4, name: 'Safety first', badge: '₹50 off', min_order_value: '500.00', shortfall: '120.00' }],
          },
        }),
      },
    })
    renderRoute('/cart')
    expect(await screen.findByText(/applied — you save ₹80/)).toBeInTheDocument()
    expect(screen.getByText(/Add ₹120 more of eligible items to unlock/)).toHaveTextContent('Safety first')
    const summary = screen.getByRole('region', { name: 'Price details' })
    expect(within(summary).getByText('Offer: Tools week')).toBeInTheDocument()
    expect(within(summary).getByText('−₹80')).toBeInTheDocument()
    expect(within(summary).queryByText(/Coupon discount/)).not.toBeInTheDocument()
  })

  it('checkout lists available coupons; applicable ones apply in one tap, others explain why', async () => {
    signIn()
    const withBoth = checkoutPreview({
      totals: { ...TOTALS_800, offer_discount: '80.00', coupon_discount: '72.00', discount_total: '152.00', grand_total: '648.00' },
      coupon: { code: 'DEMO10', description: '10% off', discount: '72.00' },
      offers: {
        applied: [{ id: 3, name: 'Tools week', description: '', badge: '10% off', discount: '80.00', variant_ids: [201] }],
        missed: [],
      },
    })
    const api = mockApi({
      get: {
        ...signedIn,
        '/categories/': [],
        '/cart/': checkoutPreview().cart,
        '/addresses/': [address()],
        '/coupons/available/': [
          { code: 'DEMO10', description: '', badge: '10% off (up to ₹200)', min_order_value: '500.00', ends_at: null, applicable: true, discount: '72.00', message: '' },
          { code: 'BIG500', description: '', badge: '₹500 off', min_order_value: '5000.00', ends_at: null, applicable: false, discount: null, message: 'Add ₹4280.00 more to use this coupon (minimum order ₹5000.00).' },
        ],
      },
      post: {
        '/checkout/preview/': ({ body }: RequestInfo) =>
          (body as { coupon_code: string }).coupon_code === 'DEMO10' ? withBoth : checkoutPreview(),
      },
    })
    const { user } = renderRoute('/checkout')
    expect(await screen.findByText('Available coupons')).toBeInTheDocument()
    expect(screen.getByText(/Add ₹4280.00 more to use this coupon/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Apply\s*coupon BIG500/ })).toBeDisabled()
    expect(screen.getByText('Saves ₹72 on this order')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Apply\s*coupon DEMO10/ }))
    expect(await screen.findByText(/applied — you save/)).toBeInTheDocument()
    await waitFor(() =>
      expect(api.post).toHaveBeenLastCalledWith('/checkout/preview/', { address_id: 31, coupon_code: 'DEMO10' }),
    )
    const summary = screen.getByRole('region', { name: 'Order summary' })
    expect(within(summary).getByText('Offer: Tools week')).toBeInTheDocument()
    expect(within(summary).getByText('Coupon discount (DEMO10)')).toBeInTheDocument()
    expect(within(summary).getByText('−₹72')).toBeInTheDocument()
  })

  it('order detail shows the offers and coupon recorded on the order', async () => {
    signIn()
    const order = orderDetail({
      offer_discount: '80.00',
      coupon_discount: '72.00',
      discount_total: '152.00',
      grand_total: '648.00',
      coupon_code: 'DEMO10',
      applied_offers: [{ id: 3, name: 'Tools week', badge: '10% off', discount: '80.00', skus: ['DEMO-WIRE-15-10'] }],
      items: [{ ...orderDetail().items[0]!, offer_discount: '80.00' }],
    })
    mockApi({ get: { ...signedIn, '/categories/': [], '/cart/': cart(), [`/orders/${order.order_number}/`]: order } })
    renderRoute(`/account/orders/${order.order_number}`)
    const summary = await screen.findByRole('region', { name: 'Price details' })
    expect(within(summary).getByText('Offer: Tools week')).toBeInTheDocument()
    expect(within(summary).getByText('Coupon discount (DEMO10)')).toBeInTheDocument()
    expect(screen.getByText('Offer saving ₹80')).toBeInTheDocument()
  })
})
