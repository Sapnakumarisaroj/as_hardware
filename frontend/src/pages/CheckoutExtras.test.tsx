import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { address, checkoutPreview, customer, TOTALS_800 } from '@/test/fixtures'
import { mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

vi.mock('@/features/addresses/MapPinPicker', () => ({ default: () => <div data-testid="map" /> }))

const home = address()

function get(extra: Record<string, unknown> = {}) {
  return {
    '/categories/': [],
    '/auth/me/': customer,
    '/wishlist/': [],
    '/search/recent/': [],
    '/cart/': checkoutPreview().cart,
    '/addresses/': [home],
    ...extra,
  }
}

const offered = { available: true, selected: false, fee: '199.00', message: 'Ground level only. Not included: carrying items upstairs.' }

function previewBodies(spy: ReturnType<typeof mockApi>['post']) {
  return spy.mock.calls.filter(([url]) => url === '/checkout/preview/').map(([, body]) => body as Record<string, unknown>)
}

describe('checkout extras', () => {
  it('adds and removes the unloading service through the server preview and shows it in the bill', async () => {
    signIn()
    const withUnloading = checkoutPreview({
      unloading: { ...offered, selected: true },
      totals: { ...TOTALS_800, unloading_fee: '199.00', grand_total: '999.00' },
    })
    const api = mockApi({
      get: get(),
      post: {
        '/checkout/preview/': ({ body }: { body: Record<string, unknown> }) =>
          body.unloading ? withUnloading : checkoutPreview({ unloading: offered }),
      },
    })
    renderRoute('/checkout')
    const card = await screen.findByTestId('unloading-card')
    expect(card).toHaveTextContent('Unloading service · ₹199')
    expect(card).toHaveTextContent('upstairs')
    await userEvent.click(within(card).getByRole('button', { name: 'Add unloading service' }))
    await waitFor(() => expect(previewBodies(api.post).at(-1)?.unloading).toBe(true))
    const bill = screen.getByRole('region', { name: 'Total bill' })
    expect(await within(bill).findByTestId('unloading-row')).toHaveTextContent('₹199')
    expect(within(screen.getByTestId('unloading-card')).getByRole('button', { name: 'Remove unloading service' })).toBeInTheDocument()
  })

  it('explains when unloading is not offered for the address', async () => {
    signIn()
    mockApi({
      get: get(),
      post: { '/checkout/preview/': checkoutPreview({ unloading: { ...offered, available: false, message: "Unloading isn't offered for this address." } }) },
    })
    renderRoute('/checkout')
    expect(await screen.findByText("Unloading isn't offered for this address.")).toBeInTheDocument()
    expect(screen.queryByTestId('unloading-card')).not.toBeInTheDocument()
  })

  it('shows the normal delivery charge and the first-orders waiver separately', async () => {
    signIn()
    const totals = {
      ...TOTALS_800,
      delivery_fee: '0.00',
      delivery_charge: '50.00',
      delivery_discount: '50.00',
      first_order_free_delivery: true,
      free_delivery_reason: 'Free delivery on your first 3 orders (1 of 3)',
    }
    mockApi({ get: get(), post: { '/checkout/preview/': checkoutPreview({ totals }) } })
    renderRoute('/checkout')
    const bill = await screen.findByRole('region', { name: 'Total bill' })
    expect(within(bill).getByText('Delivery charge').nextSibling).toHaveTextContent('₹50')
    expect(within(bill).getByTestId('delivery-waiver')).toHaveTextContent('Free delivery on your first 3 orders (1 of 3)−₹50')
  })

  it('validates the GSTIN format before saving it on the address', async () => {
    signIn()
    const api = mockApi({
      get: get(),
      post: { '/checkout/preview/': checkoutPreview() },
      patch: { '/addresses/31/': { ...home, gstin: '29ABCDE1234F1Z5' } },
    })
    renderRoute('/checkout')
    const field = await screen.findByLabelText(/GSTIN/)
    await userEvent.type(field, '29abc')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a valid 15-character GSTIN')
    expect(api.patch).not.toHaveBeenCalled()
    await userEvent.clear(field)
    await userEvent.type(field, '29abcde1234f1z5')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/addresses/31/', { gstin: '29ABCDE1234F1Z5' }))
    expect(screen.getByText(/isn’t verified with the GST portal/)).toBeInTheDocument()
  })

  it('changes quantities and removes items from checkout through the cart API', async () => {
    signIn()
    const api = mockApi({
      get: get(),
      post: { '/checkout/preview/': checkoutPreview() },
      patch: { '/cart/items/9/': checkoutPreview().cart },
      delete: { '/cart/items/9/': checkoutPreview().cart },
    })
    renderRoute('/checkout')
    await userEvent.click(await screen.findByRole('button', { name: /Increase quantity of/ }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/cart/items/9/', { quantity: 3 }))
    await userEvent.click(screen.getByRole('button', { name: /^Remove / }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/cart/items/9/'))
  })
})
