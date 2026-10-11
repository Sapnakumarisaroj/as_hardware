import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { adminProduct, staffGet } from '@/test/adminFixtures'
import { mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const draft = adminProduct({
  is_published: false,
  state: 'draft',
  variants: [
    {
      id: 101, sku: 'PLY-6', name: '6 mm / 8 x 4', attributes: {}, mrp: '2077.00', price: '1246.00', is_default: true,
      is_active: false, price_approved: false, price_source: 'Reference list 10-Oct-2026', sort_order: 0,
      stock_available: 0, stock_reserved: 0,
    },
    {
      id: 102, sku: 'PLY-8', name: '8 mm / 8 x 4', attributes: {}, mrp: '2499.00', price: '1999.00', is_default: false,
      is_active: true, price_approved: true, price_source: '', sort_order: 1, stock_available: 0, stock_reserved: 0,
    },
  ],
  images: [{ id: 7, image: '/media/p.webp', alt_text: 'Plywood sheet', is_primary: true, sort_order: 0, source_type: 'unverified' }],
})

describe('draft product preview (staff only)', () => {
  it('labels the draft, marks the unapproved price and the unverified picture, and offers no purchase', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/products/1/': draft }) })
    renderRoute('/admin/products/1/preview')

    const banner = await screen.findByRole('alert')
    expect(within(banner).getByText('DRAFT — NOT FOR SALE')).toBeInTheDocument()
    expect(within(banner).getByText('1 of 2 options have prices that are not approved.')).toBeInTheDocument()
    expect(within(banner).getByText('1 picture with usage rights not confirmed.')).toBeInTheDocument()
    expect(within(banner).getByText('No stock entered.')).toBeInTheDocument()

    expect(screen.getByText('Unverified picture — usage rights not confirmed')).toBeInTheDocument()
    const unapproved = screen.getByTestId('unapproved-price')
    expect(unapproved).toHaveTextContent('Price not approved — not shown to customers')
    expect(unapproved).toHaveTextContent('Source: Reference list 10-Oct-2026')
    expect(screen.getByRole('button', { name: 'Not for sale (draft)' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: '8 mm / 8 x 4' }))
    expect(screen.queryByTestId('unapproved-price')).not.toBeInTheDocument()
    expect(screen.getByText('20% off')).toBeInTheDocument()
  })
})
