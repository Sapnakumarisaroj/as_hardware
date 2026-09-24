import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { CartLine } from '@/features/cart/api'
import { cart, customer } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const line: CartLine = {
  id: 9,
  variant_id: 201,
  sku: 'DEMO-WIRE-15-10',
  product_id: 5,
  product_name: 'FR PVC Insulated Copper Wire',
  product_slug: 'fr-pvc-copper-wire',
  variant_name: '1.5 sq mm × 10 m',
  quantity: 2,
  unit_price: '400.00',
  unit_mrp: '500.00',
  price_at_add: '400.00',
  price_changed: false,
  line_total: '800.00',
  available_quantity: 5,
  in_stock: true,
  purchasable: true,
}

const filled = cart({
  items: [line],
  totals: {
    subtotal: '800.00',
    mrp_total: '1000.00',
    discount_total: '0.00',
    delivery_fee: '0.00',
    tax_total: '122.03',
    grand_total: '800.00',
    savings_vs_mrp: '200.00',
  },
})

function routes(cartReply: unknown) {
  return { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/cart/': cartReply }
}

describe('cart page', () => {
  it('asks logged-out shoppers to sign in', async () => {
    mockApi({ get: { '/categories/': [] } })
    renderRoute('/cart')
    expect(await screen.findByText('Sign in to see your cart and add products.')).toBeInTheDocument()
  })

  it('shows server totals and updates quantity / removes lines through the cart API', async () => {
    signIn()
    const api = mockApi({
      get: routes(filled),
      patch: { '/cart/items/9/': cart({ ...filled, items: [{ ...line, quantity: 3, line_total: '1200.00' }] }) },
      delete: { '/cart/items/9/': cart() },
    })
    const { user } = renderRoute('/cart')
    expect(await screen.findByRole('heading', { name: 'Cart (1 item)' })).toBeInTheDocument()
    expect(screen.getByText('₹800', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.getByText('−₹200')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Increase quantity' }))
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

  it('shows an error with retry when the cart cannot load', async () => {
    signIn()
    mockApi({ get: routes(httpError(500, 'Server error.')) })
    renderRoute('/cart')
    expect(await screen.findByText('Couldn’t load your cart')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
