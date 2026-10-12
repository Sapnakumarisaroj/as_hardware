import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { orderMessage, validateOrder, whatsappUrl } from '@/features/whatsapp/order'
import { cart, cartLine, customer } from '@/test/fixtures'
import { mockApi } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const shopGet = { '/categories/': [], '/search/recent/': [], '/wishlist/': [] }

const form = {
  name: 'Ravi Kumar',
  mobile: '98765 01234',
  address: '12, 3rd Cross, Near Temple',
  area: 'Kalkere',
  instructions: 'Call before delivery & use gate #2',
  lines: [
    { name: 'Hettich Soft Close Hinge', quantity: '4' },
    { name: 'Fevicol SH 1 kg', quantity: '2' },
  ],
}

describe('WhatsApp order message', () => {
  it('follows the shop’s format exactly', () => {
    expect(orderMessage(form)).toBe(
      [
        'Hello AS Hardware and Plywood,',
        '',
        'I would like to place a hardware order.',
        '',
        'Customer Name: Ravi Kumar',
        'Mobile: +91 9876501234',
        'Delivery Address: 12, 3rd Cross, Near Temple',
        'Area: Kalkere',
        '',
        'Products:',
        '1. Hettich Soft Close Hinge × 4',
        '2. Fevicol SH 1 kg × 2',
        '',
        'Delivery Instructions: Call before delivery & use gate #2',
        '',
        'Please confirm product availability, total price, delivery charges, and estimated delivery time.',
        '',
        'Thank you.',
      ].join('\n'),
    )
  })

  it('encodes the text for wa.me (spaces, line breaks, &, #, ×, ₹)', () => {
    const url = whatsappUrl(orderMessage({ ...form, subtotal: '₹1,000' }))
    expect(url.startsWith('https://wa.me/917338192616?text=')).toBe(true)
    const text = url.split('?text=')[1] ?? ''
    expect(text).not.toMatch(/[ \n&#×₹]/)
    expect(decodeURIComponent(text)).toBe(orderMessage({ ...form, subtotal: '₹1,000' }))
  })

  it('rejects missing details, bad numbers and zero or negative quantities', () => {
    const errors = validateOrder({
      ...form,
      name: '',
      mobile: '12345',
      address: 'short',
      area: '',
      lines: [
        { name: 'Hinge', quantity: '0' },
        { name: '', quantity: '3' },
        { name: 'Screws', quantity: '-2' },
      ],
    })
    expect(errors.name && errors.mobile && errors.address && errors.area).toBeTruthy()
    expect(errors.line?.[0]?.quantity).toBe('Enter a quantity of 1 or more.')
    expect(errors.line?.[1]?.name).toBe('Enter the product name.')
    expect(errors.line?.[2]?.quantity).toBe('Enter a quantity of 1 or more.')
    expect(validateOrder({ ...form, lines: [{ name: '', quantity: '' }] }).lines).toBe('Add at least one product.')
    expect(validateOrder(form)).toEqual({})
  })
})

describe('Order on WhatsApp page', () => {
  it('validates, then opens WhatsApp with the order and says it is not confirmed yet', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    mockApi({ get: { ...shopGet, '/products/': { count: 0, next: null, previous: null, results: [] } } })
    const { user } = renderRoute('/order-on-whatsapp?product=Ebco%20Drawer%20Channel&qty=3')
    expect(await screen.findByRole('heading', { name: 'Order Hardware & Plywood on WhatsApp' })).toBeInTheDocument()
    expect(screen.getByText('Share your requirements and delivery address. Our team will contact you to confirm your order.')).toBeInTheDocument()
    expect(screen.getByLabelText('Product 1')).toHaveValue('Ebco Drawer Channel')
    expect(screen.getByLabelText('Quantity')).toHaveValue(3)

    await user.click(screen.getByRole('button', { name: 'Send order on WhatsApp' }))
    expect(open).not.toHaveBeenCalled()
    expect(screen.getByText('Enter your name.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Customer name'), 'Ravi Kumar')
    await user.type(screen.getByLabelText('Mobile number'), '9876501234')
    await user.type(screen.getByLabelText('Delivery address'), '12, 3rd Cross, Near Temple')
    await user.type(screen.getByLabelText('Area / locality in Bengaluru'), 'Kalkere')
    await user.click(screen.getByRole('button', { name: '+ Add Product' }))
    await user.type(screen.getByLabelText('Product 2'), 'Fevicol SH')
    await user.click(screen.getByRole('button', { name: 'Send order on WhatsApp' }))

    expect(open).toHaveBeenCalledTimes(1)
    const url = String(open.mock.calls[0]?.[0])
    const text = decodeURIComponent(url.split('?text=')[1] ?? '')
    expect(url.startsWith('https://wa.me/917338192616?text=')).toBe(true)
    expect(text).toContain('1. Ebco Drawer Channel × 3\n2. Fevicol SH × 1')
    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('not confirmed yet')
    expect(status).toHaveTextContent('Nothing has been charged')
    open.mockRestore()
  })

  it('from the cart: brings in every item, quantity and the website subtotal', async () => {
    signIn()
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const twoLines = cart({
      items: [
        cartLine(),
        cartLine({ id: 10, variant_id: 202, product_name: 'Hinge', variant_name: '', quantity: 6, unit_price: '50.00', line_total: '300.00' }),
      ],
    })
    mockApi({ get: { ...shopGet, '/auth/me/': customer, '/cart/': twoLines } })
    const { user } = renderRoute('/order-on-whatsapp?from=cart')
    await waitFor(() => expect(screen.getByLabelText('Product 2')).toHaveValue('Hinge'))
    expect(screen.getByText(/Estimated subtotal from your cart/)).toHaveTextContent(/₹/)
    await user.type(screen.getByLabelText('Customer name'), 'Asha')
    await user.type(screen.getByLabelText('Mobile number'), '9876501234')
    await user.type(screen.getByLabelText('Delivery address'), '264, 2nd Cross Road')
    await user.type(screen.getByLabelText('Area / locality in Bengaluru'), 'Kalkere')
    await user.click(screen.getByRole('button', { name: 'Send order on WhatsApp' }))
    const text = decodeURIComponent(String(open.mock.calls[0]?.[0]).split('?text=')[1] ?? '')
    expect(text).toMatch(/2\. Hinge × 6 \(₹50(\.00)? each, ₹300(\.00)? on the website\)/)
    expect(text).toContain('Estimated subtotal (website prices, before delivery):')
    open.mockRestore()
  })

  it('the floating WhatsApp button opens click-to-chat and sits above the cart’s action bar', async () => {
    mockApi({ get: { ...shopGet, '/products/': { count: 0, next: null, previous: null, results: [] } } })
    renderRoute('/order-on-whatsapp')
    const float = await screen.findByTestId('whatsapp-float')
    expect(float.getAttribute('href')).toMatch(/^https:\/\/wa\.me\/917338192616\?text=/)
    expect(float).toHaveAttribute('target', '_blank')
    expect(float.className).toContain('bottom-5')
    expect(within(document.body).queryByText(/OTP|card details/i)?.textContent ?? '').toMatch(/Never share OTPs or card details/)
  })
})
