import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import {
  address,
  checkoutPreview,
  customer,
  deliveryQuote,
  orderDetail,
  pendingOnlineOrder,
  standardQuote,
  undeliverableQuote,
} from '@/test/fixtures'
import { httpError, mockApi, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

// The Leaflet map itself needs a real browser; the form around it is what is tested here. Tapping the stand-in
// drops a pin the way a tap on the real map does.
vi.mock('@/features/addresses/MapPinPicker', () => ({
  default: ({ onChange }: { onChange: (p: { latitude: number; longitude: number }) => void }) => (
    <button type="button" data-testid="map" onClick={() => onChange({ latitude: 12.9716, longitude: 77.5946 })}>
      Drop test pin
    </button>
  ),
}))

const home = address()
const site = address({ id: 32, name: 'Site office', address_line1: 'Plot 7, MIDC', address_type: 'site', is_default: false })

function baseGet(extra: Record<string, unknown> = {}) {
  return {
    '/categories/': [],
    '/auth/me/': customer,
    '/wishlist/': [],
    '/search/recent/': [],
    '/cart/': checkoutPreview().cart,
    '/addresses/': [home, site],
    ...extra,
  }
}

function summaryBox() {
  return screen.getByRole('region', { name: 'Total bill' })
}

function lastPreviewBody(spy: ReturnType<typeof mockApi>['post']) {
  const calls = spy.mock.calls.filter(([url]) => url === '/checkout/preview/')
  return calls.at(-1)?.[1] as { address_id: number | null; coupon_code: string }
}

describe('checkout page', () => {
  it('pre-selects the default address, shows delivery info, items and the server order summary', async () => {
    signIn()
    const api = mockApi({ get: baseGet(), post: { '/checkout/preview/': checkoutPreview() } })
    renderRoute('/checkout')

    expect(await screen.findByRole('heading', { name: 'Checkout' })).toBeInTheDocument()
    const addresses = screen.getByRole('radiogroup', { name: 'Delivery address' })
    expect(within(addresses).getByRole('radio', { name: /Deliver to Asha Kulkarni/ })).toBeChecked()
    expect(lastPreviewBody(api.post)).toEqual({ address_id: 31, coupon_code: '', use_credits: false, unloading: false })

    const delivery = screen.getByRole('heading', { name: /Delivery information/ }).closest('section')!
    expect(delivery).toHaveTextContent('Fast delivery available')
    expect(delivery).toHaveTextContent('Estimated delivery: 38 minutes')
    expect(delivery).toHaveTextContent('From Demo Store — Kothrud · about 10 min to pack')
    expect(delivery).toHaveTextContent('Delivery fee: Free')
    expect(screen.queryByText(/60 min/i)).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Order items \(1\)/ })).toBeInTheDocument()

    const summary = summaryBox()
    expect(within(summary).getByText('Items subtotal')).toBeInTheDocument()
    expect(within(summary).getByText('Includes GST of ₹122.03')).toBeInTheDocument()
    expect(within(summary).getAllByText('₹800').length).toBeGreaterThan(0)
  })

  it('standard delivery: says fast delivery is unavailable, why, and shows the next option and zone fee', async () => {
    signIn()
    const preview = checkoutPreview({
      delivery: standardQuote({ fee: '60.00', free_delivery_min_order: '999.00', amount_to_free_delivery: '199.00' }),
    })
    mockApi({ get: baseGet(), post: { '/checkout/preview/': preview } })
    renderRoute('/checkout')
    const delivery = (await screen.findByRole('heading', { name: /Delivery information/ })).closest('section')!
    expect(delivery).toHaveTextContent('Fast delivery unavailable — No delivery partner is available right now.')
    expect(delivery).toHaveTextContent('Standard delivery')
    expect(delivery).toHaveTextContent('Estimated delivery: Tomorrow, 10:00 AM – 12:00 PM')
    expect(delivery).toHaveTextContent('Delivery fee: ₹60')
    expect(delivery).toHaveTextContent('Add ₹199 more for free delivery (orders from ₹999).')
    expect(delivery).not.toHaveTextContent('Fast delivery available')
  })

  it('an address outside the delivery zones blocks the order and says so', async () => {
    signIn()
    const message = 'We don’t deliver to PIN 411014 yet.'
    const preview = checkoutPreview({
      delivery: undeliverableQuote(),
      can_place_order: false,
      blocking_issues: [{ code: 'not_deliverable', message }],
    })
    const api = mockApi({ get: baseGet(), post: { '/checkout/preview/': preview } })
    renderRoute('/checkout')
    const delivery = (await screen.findByRole('heading', { name: /Delivery information/ })).closest('section')!
    expect(within(delivery).getByRole('alert')).toHaveTextContent(message)
    expect(delivery).toHaveTextContent('Choose or add another delivery address to continue.')
    expect(delivery).not.toHaveTextContent('Estimated delivery')
    for (const button of screen.getAllByRole('button', { name: /Place order|Continue to payment/ })) expect(button).toBeDisabled()
    expect(api.post.mock.calls.filter(([url]) => url === '/orders/')).toHaveLength(0)
  })

  it('items coming from two stores are listed per store', async () => {
    signIn()
    const quote = deliveryQuote()
    const preview = checkoutPreview({
      delivery: deliveryQuote({
        shipments: [
          quote.shipments[0]!,
          { ...quote.shipments[0]!, sequence: 2, store_name: 'Demo Dark Store — Baner', line_count: 2, label: 'Delivery in 52 minutes' },
        ],
      }),
    })
    mockApi({ get: baseGet(), post: { '/checkout/preview/': preview } })
    renderRoute('/checkout')
    const delivery = (await screen.findByRole('heading', { name: /Delivery information/ })).closest('section')!
    expect(delivery).toHaveTextContent('Your items come from 2 stores and may arrive separately')
    expect(delivery).toHaveTextContent('1 item from Demo Store — Kothrud · Delivery in 38 minutes')
    expect(delivery).toHaveTextContent('2 items from Demo Dark Store — Baner · Delivery in 52 minutes')
  })

  it('the address form can carry a map pin (latitude and longitude)', async () => {
    signIn()
    const created = address({ id: 40, name: 'New Home', latitude: '18.507400', longitude: '73.807700' })
    const api = mockApi({
      get: baseGet({ '/addresses/': [] }),
      post: { '/checkout/preview/': checkoutPreview({ address_id: null, can_place_order: false }), '/addresses/': created },
    })
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: {
        getCurrentPosition: (ok: (p: unknown) => void) => ok({ coords: { latitude: 18.5074, longitude: 73.8077 } }),
      },
    })
    const { user } = renderRoute('/checkout')
    await user.click(await screen.findByRole('button', { name: 'Add delivery address' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a delivery address' })
    expect(within(dialog).getByText('No pin set yet')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Use my current location' }))
    expect(await within(dialog).findByText('Pin set at 18.507400, 73.807700')).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText(/Full name/), 'New Home')
    await user.click(within(dialog).getByRole('button', { name: 'Save address' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        '/addresses/',
        expect.objectContaining({ name: 'New Home', latitude: '18.507400', longitude: '73.807700' }),
      ),
    )
  })

  it('changing the address asks the server for a new preview', async () => {
    signIn()
    const api = mockApi({ get: baseGet(), post: { '/checkout/preview/': checkoutPreview() } })
    const { user } = renderRoute('/checkout')
    await user.click(await screen.findByRole('radio', { name: /Deliver to Site office/ }))
    await waitFor(() => expect(lastPreviewBody(api.post)).toEqual({ address_id: 32, coupon_code: '', use_credits: false, unloading: false }))
  })

  it('without saved addresses the shopper adds one and it becomes the delivery address', async () => {
    signIn()
    const created = address({ id: 40, name: 'New Home' })
    let saved = false
    const api = mockApi({
      get: baseGet({ '/addresses/': () => (saved ? [created] : []) }),
      post: {
        '/checkout/preview/': ({ body }: RequestInfo) =>
          (body as { address_id: number | null }).address_id
            ? checkoutPreview({ address_id: 40 })
            : checkoutPreview({
                address_id: null,
                can_place_order: false,
                blocking_issues: [{ code: 'address_required', message: 'Add or choose a delivery address.' }],
              }),
        '/addresses/': () => ((saved = true), created),
      },
    })
    const { user } = renderRoute('/checkout')
    expect(await screen.findByText('Add or choose a delivery address.')).toBeInTheDocument()
    for (const button of screen.getAllByRole('button', { name: /Place order|Continue to payment/ })) expect(button).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Add delivery address' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a delivery address' })
    await user.type(within(dialog).getByLabelText(/Full name/), 'New Home')
    await user.type(within(dialog).getByLabelText(/Mobile number/), '9876543210')
    await user.type(within(dialog).getByLabelText(/House \/ flat/), '5 Hill Road')
    await user.type(within(dialog).getByLabelText(/PIN code/), '411001')
    await user.type(within(dialog).getByLabelText(/City/), 'Pune')
    await user.type(within(dialog).getByLabelText(/State/), 'Maharashtra')
    await user.click(within(dialog).getByRole('button', { name: 'Drop test pin' }))
    await user.click(within(dialog).getByRole('button', { name: 'Save address' }))

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        '/addresses/',
        expect.objectContaining({ name: 'New Home', postal_code: '411001', latitude: '12.971600', longitude: '77.594600' }),
      ),
    )
    expect(await screen.findByRole('radio', { name: /Deliver to New Home/ })).toBeChecked()
    await waitFor(() => expect(lastPreviewBody(api.post)).toEqual({ address_id: 40, coupon_code: '', use_credits: false, unloading: false }))
  })

  it('address form shows the server’s validation message', async () => {
    signIn()
    mockApi({
      get: baseGet({ '/addresses/': [] }),
      post: {
        '/checkout/preview/': checkoutPreview({ address_id: null, can_place_order: false }),
        '/addresses/': httpError(400, 'Invalid input.', 'validation_error'),
      },
    })
    const { user } = renderRoute('/checkout')
    await user.click(await screen.findByRole('button', { name: 'Add delivery address' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Drop test pin' }))
    await user.click(within(dialog).getByRole('button', { name: 'Save address' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Invalid input.')
  })

  it('an address can’t be saved without its map pin', async () => {
    signIn()
    const api = mockApi({
      get: baseGet({ '/addresses/': [] }),
      post: { '/checkout/preview/': checkoutPreview({ address_id: null, can_place_order: false }) },
    })
    const { user } = renderRoute('/checkout')
    await user.click(await screen.findByRole('button', { name: 'Add delivery address' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a delivery address' })
    // The map opens straight away for a new address, and the location is marked as required.
    expect(within(dialog).getByRole('button', { name: 'Drop test pin' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Remove pin' })).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Save address' }))
    expect(await within(dialog).findByText('Select your delivery location on the map before saving.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalledWith('/addresses/', expect.anything())
  })

  it('an old address without a pin is flagged, and checkout offers to add the pin', async () => {
    signIn()
    const old = address({ id: 31, latitude: null, longitude: null })
    const pinned = { ...old, latitude: '12.971600', longitude: '77.594600' }
    let fixed = false
    const api = mockApi({
      get: baseGet({ '/addresses/': () => [fixed ? pinned : old] }),
      post: {
        '/checkout/preview/': () =>
          fixed
            ? checkoutPreview({ address_id: 31 })
            : checkoutPreview({
                address_id: 31,
                can_place_order: false,
                blocking_issues: [
                  {
                    code: 'address_location_required',
                    message: 'Select this address’s location on the map (edit the address and drop the pin).',
                  },
                ],
              }),
      },
      patch: { '/addresses/31/': () => ((fixed = true), pinned) },
    })
    const { user } = renderRoute('/checkout')
    expect(await screen.findByTestId('address-pin-missing')).toHaveTextContent('Map pin missing')
    expect(screen.getByRole('button', { name: /^Add map pin\s*address for/ })).toBeInTheDocument()
    expect(await screen.findByText(/Select this address’s location on the map/)).toBeInTheDocument()
    for (const button of screen.getAllByRole('button', { name: /Place order|Continue to payment/ })) expect(button).toBeDisabled()

    // The prompt next to the message opens the address editor, which needs the pin before it saves.
    await user.click(screen.getByRole('button', { name: 'Add map pin' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit address' })
    await user.click(within(dialog).getByRole('button', { name: 'Drop test pin' }))
    await user.click(within(dialog).getByRole('button', { name: 'Save address' }))
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith('/addresses/31/', expect.objectContaining({ latitude: '12.971600', longitude: '77.594600' })),
    )
    await waitFor(() => expect(screen.queryByTestId('address-pin-missing')).not.toBeInTheDocument())
    await waitFor(() => expect(screen.queryByText(/Select this address’s location on the map/)).not.toBeInTheDocument())
  })

  it('applies a valid coupon (server discount) and explains an invalid one', async () => {
    signIn()
    const withCoupon = checkoutPreview({
      coupon: { code: 'TOOLS10', description: '10% off tools', discount: '80.00' },
      totals: { ...checkoutPreview().totals, discount_total: '80.00', coupon_discount: '80.00', grand_total: '720.00' },
    })
    const api = mockApi({
      get: baseGet(),
      post: {
        '/checkout/preview/': ({ body }: RequestInfo) => {
          const code = (body as { coupon_code: string }).coupon_code
          if (code === 'TOOLS10') return withCoupon
          if (code === 'BIG')
            return checkoutPreview({
              coupon_error: { code: 'coupon_min_order', message: 'Add ₹4200 more to use this coupon (minimum order ₹5000).', details: {} },
            })
          return checkoutPreview()
        },
      },
    })
    const { user } = renderRoute('/checkout')
    const input = await screen.findByLabelText('Coupon code')

    await user.type(input, 'big')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(await screen.findByText('Add ₹4200 more to use this coupon (minimum order ₹5000).')).toBeInTheDocument()
    expect(within(summaryBox()).queryByText(/Coupon discount/)).not.toBeInTheDocument()

    await user.clear(input)
    await user.type(input, 'tools10')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(await screen.findByText(/applied — you save/)).toBeInTheDocument()
    expect(within(summaryBox()).getByText('Coupon discount (TOOLS10)')).toBeInTheDocument()
    expect(within(summaryBox()).getByText('−₹80')).toBeInTheDocument()
    expect(lastPreviewBody(api.post)).toEqual({ address_id: 31, coupon_code: 'TOOLS10', use_credits: false, unloading: false })

    await user.click(screen.getByRole('button', { name: /Remove\s*coupon TOOLS10/ }))
    await waitFor(() => expect(lastPreviewBody(api.post)).toEqual({ address_id: 31, coupon_code: '', use_credits: false, unloading: false }))
  })

  it('places a COD order once (idempotency key + shown total) and shows the confirmation', async () => {
    signIn()
    let resolveOrder: (value: unknown) => void = () => {}
    const api = mockApi({
      get: baseGet({ '/orders/OD260924ABCDEF/': orderDetail() }),
      post: {
        '/checkout/preview/': checkoutPreview(),
        '/orders/': () => new Promise((resolve) => (resolveOrder = resolve)),
      },
    })
    const { user, router } = renderRoute('/checkout')
    await user.click(await screen.findByRole('radio', { name: /Cash on delivery/ }))
    await user.type(screen.getByLabelText(/Delivery note/), 'Call first')
    const button = screen.getAllByRole('button', { name: 'Place order · ₹800' })[0]!
    await user.click(button)
    await user.click(button) // double click while the first request is in flight
    expect(await screen.findAllByRole('button', { name: 'Placing order…' })).not.toHaveLength(0)
    resolveOrder(orderDetail())

    await waitFor(() => expect(currentUrl(router)).toBe('/order-confirmation/OD260924ABCDEF'))
    const orderCalls = api.post.mock.calls.filter(([url]) => url === '/orders/')
    expect(orderCalls).toHaveLength(1)
    const [, body, config] = orderCalls[0]!
    expect(body).toEqual({
      address_id: 31,
      payment_method: 'cod',
      coupon_code: '',
      customer_note: 'Call first',
      expected_total: '800.00',
      use_credits: false, // the customer didn't choose credits; the server decides any amount
      unloading: false,
    })
    expect((config as { headers: Record<string, string> }).headers['Idempotency-Key']).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
    expect(await screen.findByRole('heading', { name: 'Thank you! Your order is placed.' })).toBeInTheDocument()
  })

  it('online payment goes to the payment step', async () => {
    signIn()
    mockApi({
      get: baseGet({ '/orders/OD260924ABCDEF/': pendingOnlineOrder() }),
      post: { '/checkout/preview/': checkoutPreview(), '/orders/': pendingOnlineOrder() },
    })
    const { user, router } = renderRoute('/checkout')
    expect(await screen.findByRole('radio', { name: /Mock online payment/ })).toBeChecked()
    await user.click(screen.getAllByRole('button', { name: 'Continue to payment · ₹800' })[0]!)
    await waitFor(() => expect(currentUrl(router)).toBe('/orders/OD260924ABCDEF/pay'))
  })

  it('offers cash on delivery next to Razorpay, and shows (never hides) COD when a shop rule turns it off', async () => {
    signIn()
    const online = { value: 'online' as const, label: 'Pay online — Razorpay test mode (no real money)', test_mode: true, provider: 'razorpay', available: true }
    const cod = { value: 'cod' as const, label: 'Cash on delivery', test_mode: false, available: true, max_order_value: null }
    let codOff = false
    mockApi({
      get: baseGet(),
      post: {
        '/checkout/preview/': () =>
          checkoutPreview({
            payment_methods: [
              online,
              codOff
                ? { ...cod, available: false, reason_code: 'cod_limit', message: 'Cash on Delivery isn’t available for orders above ₹2,500.' }
                : cod,
            ],
          }),
      },
    })
    const { user } = renderRoute('/checkout')
    const codRadio = await screen.findByRole('radio', { name: /Cash on delivery/ })
    expect(codRadio).toBeEnabled()
    expect(screen.getByRole('radio', { name: /Razorpay test mode/ })).toBeEnabled()
    await user.click(codRadio)
    expect(codRadio).toBeChecked()

    codOff = true
    renderRoute('/checkout')
    await waitFor(() => expect(screen.getAllByRole('radio', { name: /Cash on delivery/ }).some((r) => (r as HTMLInputElement).disabled)).toBe(true))
    expect(screen.getByText('Cash on Delivery isn’t available for orders above ₹2,500.')).toBeInTheDocument()
  })

  it('Razorpay test mode is described as Razorpay, not as the development mock', async () => {
    signIn()
    const preview = checkoutPreview()
    preview.payment_methods = preview.payment_methods.map((m) =>
      m.value === 'online' ? { ...m, label: 'Pay online — Razorpay test mode (no real money)', provider: 'razorpay' } : m,
    )
    mockApi({ get: baseGet(), post: { '/checkout/preview/': preview } })
    renderRoute('/checkout')
    expect(await screen.findByRole('radio', { name: /Razorpay test mode/ })).toBeInTheDocument()
    expect(screen.getByText(/pay with Razorpay’s test cards or UPI/)).toBeInTheDocument()
    expect(screen.queryByText(/you choose success, failure or cancellation/)).not.toBeInTheDocument()
  })

  it('a price change is reported and the new total is fetched instead of ordering', async () => {
    signIn()
    let changed = false
    const api = mockApi({
      get: baseGet(),
      post: {
        '/checkout/preview/': () =>
          changed ? checkoutPreview({ totals: { ...checkoutPreview().totals, grand_total: '900.00' } }) : checkoutPreview(),
        '/orders/': () => {
          changed = true
          return httpError(409, 'Prices or your order total changed.', 'totals_changed')
        },
      },
    })
    const { user } = renderRoute('/checkout')
    await user.click((await screen.findAllByRole('button', { name: /Continue to payment · ₹800/ }))[0]!)
    expect(await screen.findByText(/Prices changed since you opened checkout/)).toBeInTheDocument()
    expect(await screen.findAllByRole('button', { name: /Continue to payment · ₹900/ })).not.toHaveLength(0)
    expect(api.post.mock.calls.filter(([url]) => url === '/orders/')).toHaveLength(1)
  })

  it('stock problems send the shopper back to the cart', async () => {
    signIn()
    mockApi({
      get: baseGet(),
      post: {
        '/checkout/preview/': checkoutPreview({
          cart: { ...checkoutPreview().cart, issues: ['Only 1 unit(s) available.'], can_checkout: false },
          can_place_order: false,
        }),
      },
    })
    const { router } = renderRoute('/checkout')
    await waitFor(() => expect(currentUrl(router)).toBe('/cart'))
  })

  it('shows an error with retry when checkout cannot load', async () => {
    signIn()
    mockApi({ get: baseGet(), post: { '/checkout/preview/': httpError(500, 'Server error.') } })
    const first = renderRoute('/checkout')
    expect(await screen.findByText('Couldn’t load checkout')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    first.unmount()
  })

  it('asks anonymous shoppers to sign in before checkout', async () => {
    const api = mockApi({ get: { '/categories/': [] } })
    renderRoute('/checkout')
    expect(await screen.findByText('Sign in to check out.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })
})
