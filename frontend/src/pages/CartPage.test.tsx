import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  address,
  cart,
  cartLine,
  checkoutPreview,
  customer,
  deliveryQuote,
  standardQuote,
  TOTALS_800 as TOTALS,
  undeliverableQuote,
} from '@/test/fixtures'
import { httpError, mockApi, paramsSent } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const line = cartLine({ available_quantity: 5 })
const filled = cart({ items: [line], totals: TOTALS, can_checkout: true })

function routes(cartReply: unknown, extra: Record<string, unknown> = {}) {
  return {
    '/categories/': [],
    '/auth/me/': customer,
    '/wishlist/': [],
    '/search/recent/': [],
    '/cart/': cartReply,
    ...extra,
  }
}

function summary() {
  return screen.getByRole('region', { name: 'Price details' })
}

describe('cart page', () => {
  it('asks logged-out shoppers to sign in', async () => {
    mockApi({ get: { '/categories/': [] } })
    renderRoute('/cart')
    expect(await screen.findByText('Sign in to see your cart and add products.')).toBeInTheDocument()
  })

  it('shows variant, attributes, MRP, discount, stock and server totals', async () => {
    signIn()
    mockApi({ get: routes(filled) })
    renderRoute('/cart')
    expect(await screen.findByRole('heading', { name: 'Cart (2 items)' })).toBeInTheDocument()
    expect(screen.getByText('1.5 sq mm × 10 m')).toBeInTheDocument()
    expect(screen.getByText('size: 1.5 sq mm · length: 10 m')).toBeInTheDocument()
    expect(screen.getByText('VoltLine')).toBeInTheDocument()
    expect(screen.getByText('20% off')).toBeInTheDocument()
    expect(screen.getByText('Only 5 left')).toBeInTheDocument()
    expect(within(summary()).getByText('₹1,000')).toBeInTheDocument() // total MRP
    expect(within(summary()).getByText('Free')).toBeInTheDocument()
    expect(screen.getByText('You save ₹200 on this order')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Continue shopping' })).toHaveAttribute('href', '/products')
  })

  it('updates quantity and removes lines through the cart API', async () => {
    signIn()
    const api = mockApi({
      get: routes(filled),
      patch: { '/cart/items/9/': cart({ ...filled, items: [{ ...line, quantity: 3, line_total: '1200.00' }] }) },
      delete: { '/cart/items/9/': cart() },
    })
    const { user } = renderRoute('/cart')
    await user.click(await screen.findByRole('button', { name: 'Increase quantity' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/cart/items/9/', { quantity: 3 }))
    expect(await screen.findByText('₹1,200')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^Remove\s*FR PVC Insulated Copper Wire$/ }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/cart/items/9/'))
    expect(await screen.findByText('Your cart is empty')).toBeInTheDocument()
  })

  it('shows the backend stock error when an update is rejected', async () => {
    signIn()
    mockApi({
      get: routes(filled),
      patch: { '/cart/items/9/': httpError(409, 'Only 2 available.', 'insufficient_stock') },
    })
    const { user } = renderRoute('/cart')
    await user.click(await screen.findByRole('button', { name: 'Increase quantity' }))
    expect(await screen.findByText('Only 2 available.')).toBeInTheDocument()
  })

  it('stock conflict: explains the problem and blocks checkout', async () => {
    signIn()
    const conflict = cart({
      items: [cartLine({ quantity: 4, available_quantity: 2, in_stock: false, line_total: null })],
      totals: { ...TOTALS, subtotal: '0.00', grand_total: '0.00' },
      issues: ['Only 2 unit(s) of DEMO-WIRE-15-10 available.'],
      can_checkout: false,
    })
    mockApi({ get: routes(conflict) })
    renderRoute('/cart')
    expect(await screen.findByText('Please fix these before checkout:')).toBeInTheDocument()
    expect(screen.getByText('Only 2 available — reduce the quantity to continue.')).toBeInTheDocument()
    for (const button of screen.getAllByRole('button', { name: 'Proceed to checkout' })) expect(button).toBeDisabled()
  })

  it('save for later moves the item to the wishlist', async () => {
    signIn()
    const api = mockApi({
      get: routes(filled),
      post: { '/wishlist/': null },
      delete: { '/cart/items/9/': cart() },
    })
    const { user } = renderRoute('/cart')
    await user.click(await screen.findByRole('button', { name: /Save for later/ }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/wishlist/', { product_id: 5 }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/cart/items/9/'))
    expect(await screen.findByText(/Saved for later: FR PVC/)).toBeInTheDocument()
  })

  it('shows the delivery estimate for the default address', async () => {
    signIn()
    const api = mockApi({
      get: routes(filled, { '/addresses/': [address()], '/delivery/cart-estimate/': deliveryQuote() }),
    })
    renderRoute('/cart')
    const delivery = (await screen.findByRole('heading', { name: 'Delivery' })).closest('section')!
    await waitFor(() => expect(delivery).toHaveTextContent('To Asha Kulkarni, Kothrud 411038'))
    expect(delivery).toHaveTextContent('Fast delivery available')
    expect(delivery).toHaveTextContent('Estimated delivery: 38 minutes')
    expect(paramsSent(api.get, '/delivery/cart-estimate/')).toEqual([{ address_id: 31 }])
  })

  it('without an address it uses the PIN code, or asks for one', async () => {
    signIn()
    const api = mockApi({
      get: routes(filled, { '/addresses/': [], '/delivery/cart-estimate/': standardQuote({ location_precision: 'pin' }) }),
    })
    const { user } = renderRoute('/cart')
    const delivery = (await screen.findByRole('heading', { name: 'Delivery' })).closest('section')!
    expect(paramsSent(api.get, '/delivery/cart-estimate/')).toHaveLength(0)
    await user.type(within(delivery).getByLabelText(/Enter your PIN code/), '411001')
    await user.click(within(delivery).getByRole('button', { name: 'Check' }))
    await waitFor(() => expect(delivery).toHaveTextContent('To PIN 411001'))
    expect(delivery).toHaveTextContent('Fast delivery unavailable')
    expect(delivery).toHaveTextContent('Estimated delivery: Tomorrow, 10:00 AM – 12:00 PM')
    expect(paramsSent(api.get, '/delivery/cart-estimate/')).toEqual([{ postal_code: '411001' }])
  })

  it('says when the cart cannot be delivered to the address', async () => {
    signIn()
    mockApi({
      get: routes(filled, { '/addresses/': [address({ postal_code: '411014' })], '/delivery/cart-estimate/': undeliverableQuote() }),
    })
    renderRoute('/cart')
    const delivery = (await screen.findByRole('heading', { name: 'Delivery' })).closest('section')!
    expect(await within(delivery).findByRole('alert')).toHaveTextContent('We don’t deliver to PIN 411014 yet.')
  })

  it('proceeds to checkout', async () => {
    signIn()
    mockApi({
      get: routes(filled, { '/addresses/': [address()] }),
      post: { '/checkout/preview/': checkoutPreview() },
    })
    const { user, router } = renderRoute('/cart')
    await user.click((await screen.findAllByRole('button', { name: 'Proceed to checkout' }))[0]!)
    await waitFor(() => expect(currentUrl(router)).toBe('/checkout')) // lazy route: navigation completes after load
    expect(await screen.findByRole('heading', { name: 'Checkout' })).toBeInTheDocument()
  })

  it('shows an error with retry when the cart cannot load', async () => {
    signIn()
    mockApi({ get: routes(httpError(500, 'Server error.')) })
    renderRoute('/cart')
    expect(await screen.findByText('Couldn’t load your cart')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
