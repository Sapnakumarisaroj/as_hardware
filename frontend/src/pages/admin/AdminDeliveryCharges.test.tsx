import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { DeliveryCharges } from '@/features/admin/types'
import { staffGet } from '@/test/adminFixtures'
import { mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const charges: DeliveryCharges = {
  distance_bands: [
    { up_to_km: '3', fee: '30.00' },
    { up_to_km: '5', fee: '50.00' },
    { up_to_km: '8', fee: '80.00' },
    { up_to_km: '12', fee: '120.00' },
  ],
  extra_per_km: null,
  free_first_orders: 3,
  unloading_fee: '199.00',
  updated_at: '2026-10-11T10:00:00+05:30',
  updated_by_name: null,
  routing: 'estimated (straight line)',
  open_coverage_reviews: 2,
  stores: [{ id: 1, name: 'AS Hardware and Plywood', has_coordinates: false, zones: [] }],
}

describe('delivery charges (dashboard)', () => {
  it('edits the distance bands, per-km rate and first-order free deliveries', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/delivery-charges/': charges }),
      patch: { '/admin/delivery-charges/': charges },
    })
    renderRoute('/admin/delivery-charges')
    expect(await screen.findByRole('heading', { name: 'Delivery charges' })).toBeInTheDocument()
    expect(screen.getByText(/Map location missing/)).toBeInTheDocument()
    expect(screen.getByText(/No delivery zone/)).toBeInTheDocument()
    expect(screen.getByText(/2 customer addresses are outside the delivery area/)).toBeInTheDocument()

    const fee = screen.getByLabelText('Band 4: fee')
    await userEvent.clear(fee)
    await userEvent.type(fee, '125')
    await userEvent.type(screen.getByLabelText(/extra per km/), '10')
    const free = screen.getByLabelText(/first … orders/)
    await userEvent.clear(free)
    await userEvent.type(free, '2')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith('/admin/delivery-charges/', {
        distance_bands: [...charges.distance_bands.slice(0, 3), { up_to_km: '12', fee: '125' }],
        extra_per_km: '10',
        free_first_orders: 2,
        unloading_fee: '199.00',
      }),
    )
  })

  it('refuses bands whose distances do not increase', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/admin/delivery-charges/': charges }) })
    renderRoute('/admin/delivery-charges')
    const km = await screen.findByLabelText('Band 2: up to km')
    await userEvent.clear(km)
    await userEvent.type(km, '2')
    expect(screen.getByRole('alert')).toHaveTextContent('increasing from row to row')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(api.patch).not.toHaveBeenCalled()
  })
})
