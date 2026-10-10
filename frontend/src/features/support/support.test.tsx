import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthState } from '@/features/auth/context'
import { conversation, staffGet } from '@/test/adminFixtures'
import { customer } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

import { ProductEnquiry } from './ProductEnquiry'
import { whatsappLink } from './whatsapp'

const env = vi.hoisted(() => ({ supportWhatsApp: '', appName: 'BoltRun', apiBaseUrl: 'http://localhost:8000/api' }))
vi.mock('@/lib/env', async (original) => {
  const actual = (await original()) as { env: Record<string, unknown> }
  return { env: new Proxy(actual.env, { get: (target, key: string) => (key in env ? env[key as keyof typeof env] : target[key]) }) }
})

afterEach(() => {
  env.supportWhatsApp = ''
})

function renderEnquiry(status: AuthState['status'] = 'authenticated') {
  const auth = { status, user: status === 'authenticated' ? customer : null } as AuthState
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter initialEntries={['/p/bwp-plywood-18-mm']}>
          <ProductEnquiry productId={5} productName="BWP Plywood 18 mm" />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
  return user
}

describe('ask about this product', () => {
  it('sends a signed-in customer’s question to the support inbox', async () => {
    const api = mockApi({ post: { '/support/product-enquiries/': { id: 9, subject: 'Question about BWP Plywood 18 mm', product: null } } })
    const user = renderEnquiry()
    await user.click(screen.getByRole('button', { name: 'Ask about this product' }))
    await user.type(screen.getByLabelText('Your question'), 'Is it termite proof?')
    await user.click(screen.getByRole('button', { name: 'Send question' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Your question was sent')
    expect(api.post).toHaveBeenCalledWith('/support/product-enquiries/', { product_id: 5, message: 'Is it termite proof?' })
  })

  it('shows the server’s error', async () => {
    mockApi({ post: { '/support/product-enquiries/': httpError(404, 'Product not found.') } })
    const user = renderEnquiry()
    await user.click(screen.getByRole('button', { name: 'Ask about this product' }))
    await user.type(screen.getByLabelText('Your question'), 'Hello?')
    await user.click(screen.getByRole('button', { name: 'Send question' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Product not found.')
  })

  it('asks visitors to sign in and hides WhatsApp when no number is configured', () => {
    renderEnquiry('anonymous')
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login?next=%2Fp%2Fbwp-plywood-18-mm')
    expect(screen.queryByRole('link', { name: 'Chat on WhatsApp' })).not.toBeInTheDocument()
  })

  it('offers WhatsApp with the product prefilled when the shop has a number', () => {
    env.supportWhatsApp = '+91 98123 45678'
    renderEnquiry()
    const link = screen.getByRole('link', { name: 'Chat on WhatsApp' })
    expect(link.getAttribute('href')).toMatch(/^https:\/\/wa\.me\/919812345678\?text=/)
    expect(decodeURIComponent(link.getAttribute('href')!)).toContain('question about BWP Plywood 18 mm')
    expect(whatsappLink('X', 'https://shop/p/x')).toContain('wa.me/919812345678')
  })
})

describe('support inbox attachments', () => {
  it('shows a WhatsApp photo through the staff endpoint and links the product', async () => {
    signIn()
    const createObjectURL = vi.fn(() => 'blob:photo-1')
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL }))
    const withPhoto = conversation({
      channel: 'whatsapp',
      product: { id: 5, name: 'Soft-close Hinge', slug: 'soft-close-hinge' },
      messages: [
        {
          id: 31,
          sender_type: 'customer',
          sender_name: 'Customer',
          body: 'Is this one available?',
          attachments: [{ type: 'image', media_id: 'm-1', mime_type: 'image/jpeg', caption: 'Is this one available?' }],
          created_at: '2026-10-09T06:00:00Z',
        },
        {
          id: 32,
          sender_type: 'customer',
          sender_name: 'Customer',
          body: '',
          attachments: [{ type: 'document', media_id: 'm-2', mime_type: 'audio/ogg', caption: '' }],
          created_at: '2026-10-09T06:01:00Z',
        },
      ],
    })
    const api = mockApi({
      get: staffGet('admin', {
        '/admin/support/12/': withPhoto,
        '/support/messages/31/attachments/0/': new Blob(['jpeg']),
      }),
    })
    renderRoute('/admin/support/12')
    const photo = await screen.findByRole('img', { name: 'Is this one available?' })
    expect(photo).toHaveAttribute('src', 'blob:photo-1')
    expect(api.get).toHaveBeenCalledWith('/support/messages/31/attachments/0/', { responseType: 'blob' })
    expect(screen.getByText(/audio\/ogg/)).toHaveTextContent('open it in WhatsApp Manager')
    expect(screen.getByRole('link', { name: 'Soft-close Hinge' })).toHaveAttribute('href', '/p/soft-close-hinge')
    vi.unstubAllGlobals()
  })

  it('explains when the provider can’t fetch the file', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', {
        '/admin/support/12/': conversation({
          messages: [
            {
              id: 31,
              sender_type: 'customer',
              sender_name: 'Customer',
              body: '',
              attachments: [{ type: 'image', media_id: 'm-1', mime_type: 'image/png', caption: '' }],
              created_at: '2026-10-09T06:00:00Z',
            },
          ],
        }),
        '/support/messages/31/attachments/0/': httpError(404, 'Not available'),
      }),
    })
    renderRoute('/admin/support/12')
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('can’t be shown here'))
  })
})
