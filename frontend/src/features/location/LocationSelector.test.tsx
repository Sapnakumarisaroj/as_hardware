import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { readPincode } from '@/features/delivery/location'
import type { Serviceability } from '@/features/delivery/types'
import { productPage } from '@/test/fixtures'
import { mockApi, paramsSent, type RequestInfo } from '@/test/mockApi'
import { renderRoute } from '@/test/utils'

function check(overrides: Partial<Serviceability> = {}): Serviceability {
  return {
    serviceable: true,
    postal_code: '411038',
    location_precision: 'pin',
    fast_delivery_available: true,
    label: 'Delivery in 24 minutes',
    fast_unavailable_reason: '',
    message: '⚡ Fast delivery available · Delivery in 24 minutes',
    stores: [],
    ...overrides,
  }
}

const REPLIES: Record<string, Serviceability> = {
  '411038': check(),
  '411001': check({
    postal_code: '411001',
    fast_delivery_available: false,
    label: 'Tomorrow, 10:00 AM – 12:00 PM',
    fast_unavailable_reason: 'Fast delivery isn’t offered in this area.',
    message: '🚚 Standard delivery · Tomorrow, 10:00 AM – 12:00 PM',
  }),
  '411014': check({ postal_code: '411014', serviceable: false, fast_delivery_available: false, label: '', message: 'We don’t deliver to PIN 411014 yet.' }),
}

function routes() {
  return {
    '/categories/': [],
    '/products/': productPage([]),
    '/products/facets/': { total: 0, categories: [], brands: [], price: { min: null, max: null }, ratings: [], discounts: [], availability: { in_stock: 0, fast_delivery: 0 }, specifications: [] },
    '/offers/': [],
    '/delivery/check/': ({ params }: RequestInfo) => REPLIES[params.postal_code!],
  }
}

describe('delivery location selector', () => {
  it('checks the PIN code with the backend and shows fast, standard and not-serviceable answers', async () => {
    const api = mockApi({ get: routes() })
    // Any page: the selector lives in the header (the homepage repeats the message in its own bar).
    const { user } = renderRoute('/products')
    await user.click((await screen.findAllByRole('button', { name: /Deliver to\s*Select location/ }))[0]!)
    const input = screen.getByLabelText('Delivery PIN code')

    await user.type(input, '123')
    await user.click(screen.getByRole('button', { name: 'Check' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a valid 6-digit PIN code.')
    expect(paramsSent(api.get, '/delivery/check/')).toHaveLength(0)

    await user.clear(input)
    await user.type(input, '411038')
    await user.click(screen.getByRole('button', { name: 'Check' }))
    expect(await screen.findByText('⚡ Fast delivery available · Delivery in 24 minutes')).toBeInTheDocument()
    expect(readPincode()).toBe('411038')
    expect(screen.getAllByRole('button', { name: /Deliver to\s*411038/ })).not.toHaveLength(0)
    // The header shows the engine's time for the chosen PIN under it.
    expect(screen.getByTestId('pin-summary')).toHaveTextContent('⚡ Delivery in 24 minutes')

    await user.clear(input)
    await user.type(input, '411001')
    await user.click(screen.getByRole('button', { name: 'Check' }))
    expect(await screen.findByText('🚚 Standard delivery · Tomorrow, 10:00 AM – 12:00 PM')).toBeInTheDocument()
    expect(screen.getByText(/Fast delivery unavailable — Fast delivery isn’t offered in this area\./)).toBeInTheDocument()

    await user.clear(input)
    await user.type(input, '411014')
    await user.click(screen.getByRole('button', { name: 'Check' }))
    expect(await screen.findByText('We don’t deliver to PIN 411014 yet.')).toBeInTheDocument()
    await waitFor(() =>
      expect(paramsSent(api.get, '/delivery/check/')).toEqual([
        { postal_code: '411038' },
        { postal_code: '411001' },
        { postal_code: '411014' },
      ]),
    )
    expect(screen.queryByText(/60 min/i)).not.toBeInTheDocument()
  })
})
