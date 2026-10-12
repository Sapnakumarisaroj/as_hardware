import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { User } from '@/features/auth/api'
import type { Earnings, Job, RiderProfile } from '@/features/rider/types'
import { customer } from '@/test/fixtures'
import { httpError, mockApi, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const riderUser: User = { ...customer, id: 21, email: 'ravi@example.com', full_name: 'Ravi Rider', role: 'delivery_partner' }

function profile(overrides: Partial<RiderProfile> = {}): RiderProfile {
  return {
    full_name: 'Ravi Rider',
    email: 'ravi@example.com',
    phone: '9123456780',
    vehicle_type: 'scooter',
    vehicle_number: 'MH12AB1234',
    home_store_name: 'Demo Store — Kothrud',
    status: 'available',
    is_verified: true,
    is_active: true,
    max_active_assignments: 1,
    active_assignments: 0,
    cash_in_hand: '0.00',
    last_location_at: null,
    ...overrides,
  }
}

const earnings: Earnings = {
  delivered_count: 12,
  total_earnings: '510.40',
  today_earnings: '82.40',
  last_7_days_earnings: '300.00',
  today_delivered_count: 2,
  failed_count: 1,
  cash_in_hand: '1200.00',
  cash_deliveries_pending_handover: 1,
}

const STORE = {
  name: 'Demo Store — Kothrud',
  address: '1 Paud Road, Kothrud, Pune, 411038',
  phone: '02012345678',
  latitude: '18.507400',
  longitude: '73.807700',
  map_url: 'https://www.openstreetmap.org/?mlat=18.507400&mlon=73.807700#map=17/18.507400/73.807700',
  directions_url: 'https://www.openstreetmap.org/directions?to=18.507400%2C73.807700',
  geo_uri: 'geo:18.507400,73.807700?q=18.507400,73.807700',
}
const CUSTOMER = {
  name: 'Asha Kumar',
  phone: '9876543210',
  address: '12 MG Road, Kothrud, Pune, 411038',
  area: 'Kothrud',
  city: 'Pune',
  landmark: 'Blue gate',
  postal_code: '411038',
  latitude: '18.525400',
  longitude: '73.807700',
  note: 'Call before delivery',
  map_url: 'https://www.openstreetmap.org/?mlat=18.525400&mlon=73.807700#map=17/18.525400/73.807700',
  directions_url: 'https://www.openstreetmap.org/directions?to=18.525400%2C73.807700',
  geo_uri: 'geo:18.525400,73.807700?q=18.525400,73.807700',
}

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 7,
    kind: 'delivery',
    kind_label: 'Delivery to the customer',
    status: 'assigned',
    status_label: 'Assigned',
    order_number: 'OD260928ABCDEF',
    order_status: 'assigned',
    payment_method: 'cod',
    shipment_sequence: 1,
    return_number: null,
    amount_to_collect: '1200.00',
    cod: {
      amount_due: '1200.00',
      collected: false,
      collected_amount: null,
      method: null,
      collected_at: null,
      handed_over: false,
      handed_over_at: null,
    },
    pickup: STORE,
    drop: CUSTOMER,
    items: [{ name: 'Impact Drill 650W', variant: '', sku: 'DEMO-DRILL', quantity: 2 }],
    otp_state: 'none',
    proof_uploaded: false,
    proof_required: false,
    received_by: '',
    next_actions: ['accept', 'reject'],
    assigned_at: '2026-09-28T08:00:00Z',
    accepted_at: null,
    picked_up_at: null,
    out_for_delivery_at: null,
    delivered_at: null,
    failed_at: null,
    failure_code: '',
    failure_reason: '',
    rejected_at: null,
    reject_reason: '',
    distance_km: '2.70',
    earning_amount: '0.00',
    delivery_notes: '',
    status_history: [{ from_status: '', to_status: 'assigned', note: 'Assigned by store', created_at: '2026-09-28T08:00:00Z' }],
    ...overrides,
  }
}

const accepted = (o: Partial<Job> = {}) => job({ status: 'accepted', status_label: 'Accepted', next_actions: ['pickup', 'reject'], ...o })
const pickedUp = (o: Partial<Job> = {}) => job({ status: 'picked_up', status_label: 'Picked up', next_actions: ['start', 'fail'], ...o })
const onTheWay = (o: Partial<Job> = {}) =>
  job({
    status: 'out_for_delivery',
    status_label: 'Out for delivery',
    otp_state: 'active',
    next_actions: ['proof', 'complete', 'fail'],
    ...o,
  })
const delivered = (o: Partial<Job> = {}) =>
  job({
    status: 'delivered',
    status_label: 'Delivered',
    otp_state: 'used',
    next_actions: [],
    amount_to_collect: null,
    delivered_at: '2026-09-28T09:00:00Z',
    earning_amount: '41.20',
    drop: { area: 'Kothrud', city: 'Pune' },
    cod: { ...job().cod!, collected: true, collected_amount: '1200.00', method: 'cash', collected_at: '2026-09-28T09:00:00Z' },
    ...o,
  })

function page(results: Job[], count = results.length) {
  return { count, next: null, previous: null, results }
}

function riderGet(extra: Record<string, unknown> = {}) {
  return {
    '/auth/me/': riderUser,
    '/delivery/me/': profile(),
    '/delivery/earnings/': earnings,
    '/delivery/assignments/': ({ params }: RequestInfo) => page(params.scope === 'active' ? [job()] : [delivered({ id: 3 })]),
    '/delivery/assignments/7/': job(),
    ...extra,
  }
}

function lastBody(spy: ReturnType<typeof mockApi>['post'], url: string) {
  return spy.mock.calls.filter(([called]) => called === url).at(-1)?.[1]
}

describe('rider app: access', () => {
  it('asks for a login, and sends delivery partners to the rider app after it', async () => {
    const api = mockApi({
      get: { ...riderGet(), '/categories/': [] },
      post: { '/auth/login/': { access: 'a', refresh: 'r', user: riderUser } },
    })
    const { user, router } = renderRoute('/rider')
    expect(await screen.findByText('Sign in with your delivery partner account.')).toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalledWith('/delivery/me/')

    await user.click(screen.getByRole('link', { name: 'Login' }))
    await user.click(await screen.findByRole('link', { name: 'Sign in with email and password' }))
    await user.type(await screen.findByLabelText('Email'), 'ravi@example.com')
    await user.type(screen.getByLabelText('Password'), 'S3cure-pass!')
    await user.click(screen.getByRole('button', { name: 'Login' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/rider'))
    expect(await screen.findByRole('heading', { name: 'Rider app' })).toBeInTheDocument()
  })

  it('a delivery partner who logs in from the shop lands in the rider app', async () => {
    mockApi({
      get: { ...riderGet(), '/categories/': [], '/wishlist/': [], '/cart/': { items: [] }, '/search/recent/': [] },
      post: { '/auth/login/': { access: 'a', refresh: 'r', user: riderUser } },
    })
    const { user, router } = renderRoute('/login?method=email')
    await user.type(await screen.findByLabelText('Email'), 'ravi@example.com')
    await user.type(screen.getByLabelText('Password'), 'S3cure-pass!')
    await user.click(screen.getByRole('button', { name: 'Login' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/rider'))
  })

  it('customers are told the area is not for them and no rider data is requested', async () => {
    signIn()
    const api = mockApi({ get: { '/auth/me/': customer } })
    renderRoute('/rider/jobs/7')
    expect(await screen.findByText('For delivery partners only')).toBeInTheDocument()
    expect(api.get.mock.calls.filter(([url]) => String(url).startsWith('/delivery/'))).toHaveLength(0)
  })
})

describe('rider app: dashboard', () => {
  it('shows profile, availability, active jobs, earnings and cash to hand over', async () => {
    signIn()
    const api = mockApi({ get: riderGet() })
    renderRoute('/rider')
    const me = (await screen.findByRole('heading', { name: 'Ravi Rider' })).closest('section')!
    expect(me).toHaveTextContent('Demo Store — Kothrud · scooter MH12AB1234 · 9123456780')
    expect(me).toHaveTextContent('Online · available · 0 of 1 active job')

    const row = await screen.findByRole('link', { name: /Delivery · order OD260928ABCDEF/ })
    expect(row).toHaveAttribute('href', '/rider/jobs/7')
    expect(row).toHaveTextContent('2 item(s) · Kothrud, Pune · 2.7 km')
    expect(row).toHaveTextContent('Collect ₹1,200')
    expect(api.get).toHaveBeenCalledWith('/delivery/assignments/', { params: { scope: 'active', page: 1, page_size: 10 } })

    const money = screen.getByRole('heading', { name: 'Earnings and cash' }).closest('section')!
    expect(money).toHaveTextContent('Today₹82.402 jobs done')
    expect(money).toHaveTextContent('All time₹510.4012 done · 1 failed')
    expect(money).toHaveTextContent('Cash to hand over₹1,200From 1 delivery. Give it to the store.')
  })

  it('goes offline and online', async () => {
    signIn()
    const api = mockApi({
      get: riderGet({ '/delivery/assignments/': page([]) }),
      patch: { '/delivery/me/': ({ body }: RequestInfo) => profile({ status: (body as { status: 'offline' }).status }) },
    })
    const { user } = renderRoute('/rider')
    expect(await screen.findByText('No active jobs')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Go offline' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/delivery/me/', { status: 'offline' }))
    expect(await screen.findByRole('button', { name: 'Go online' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText('Offline')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Go online' }))
    await waitFor(() => expect(api.patch).toHaveBeenLastCalledWith('/delivery/me/', { status: 'available' }))
  })

  it('cannot go offline with an active job, or online before verification', async () => {
    signIn()
    mockApi({ get: riderGet({ '/delivery/me/': profile({ status: 'busy', active_assignments: 1 }) }) })
    const first = renderRoute('/rider')
    expect(await screen.findByRole('button', { name: 'Go offline' })).toBeDisabled()
    expect(screen.getByText('Finish your active job before going offline.')).toBeInTheDocument()
    expect(screen.getByText('Online · on a job')).toBeInTheDocument()
    first.unmount()

    mockApi({ get: riderGet({ '/delivery/me/': profile({ status: 'offline', is_verified: false }) }) })
    renderRoute('/rider')
    expect(await screen.findByRole('button', { name: 'Go online' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('waiting for verification')
  })

  it('shows the server’s reason when availability cannot change', async () => {
    signIn()
    mockApi({
      get: riderGet({ '/delivery/assignments/': page([]) }),
      patch: { '/delivery/me/': httpError(409, 'Finish your active delivery before changing availability.', 'active_delivery') },
    })
    const { user } = renderRoute('/rider')
    await user.click(await screen.findByRole('button', { name: 'Go offline' }))
    expect(await screen.findByText('Finish your active delivery before changing availability.')).toBeInTheDocument()
  })

  it('history lists finished jobs with what was earned', async () => {
    signIn()
    const api = mockApi({
      get: riderGet({
        '/delivery/assignments/': page(
          [
            delivered({ id: 3 }),
            job({ id: 4, status: 'failed', status_label: 'Delivery failed', next_actions: [], amount_to_collect: null }),
          ],
          14,
        ),
      }),
    })
    const { user } = renderRoute('/rider/history')
    expect(await screen.findByRole('heading', { name: 'Delivery history' })).toBeInTheDocument()
    const rows = await screen.findAllByRole('link', { name: /order OD260928ABCDEF/ })
    expect(rows[0]).toHaveTextContent('Delivered')
    expect(rows[0]).toHaveTextContent('Earned ₹41.20')
    expect(rows[1]).toHaveTextContent('Delivery failed')
    await user.click(screen.getByRole('button', { name: 'Page 2' }))
    await waitFor(() =>
      expect(api.get).toHaveBeenLastCalledWith('/delivery/assignments/', { params: { scope: 'history', page: 2, page_size: 10 } }),
    )
  })
})

describe('rider app: a delivery', () => {
  it('shows where to collect and deliver, with navigation and call links, the items and the cash', async () => {
    signIn()
    mockApi({ get: riderGet() })
    renderRoute('/rider/jobs/7')
    expect(await screen.findByRole('heading', { name: 'Delivery · OD260928ABCDEF' })).toBeInTheDocument()
    expect(screen.getByText(/Cash on delivery: collect/)).toHaveTextContent('₹1,200')
    expect(screen.getByRole('status', { name: '' })).toBeDefined()

    const store = screen.getByRole('region', { name: 'Collect from (store)' })
    expect(store).toHaveTextContent('Demo Store — Kothrud')
    expect(within(store).getByRole('link', { name: 'Navigate' })).toHaveAttribute('href', STORE.geo_uri)
    expect(within(store).getByRole('link', { name: 'Open map' })).toHaveAttribute('href', STORE.directions_url)
    expect(within(store).getByRole('link', { name: /Call store/ })).toHaveAttribute('href', 'tel:02012345678')

    const door = screen.getByRole('region', { name: 'Deliver to (customer)' })
    expect(door).toHaveTextContent('Asha Kumar')
    expect(door).toHaveTextContent('12 MG Road, Kothrud, Pune, 411038')
    expect(door).toHaveTextContent('Near Blue gate')
    expect(door).toHaveTextContent('Customer’s note: Call before delivery')
    expect(within(door).getByRole('link', { name: /Call customer/ })).toHaveAttribute('href', 'tel:9876543210')
    expect(within(door).getByRole('link', { name: 'Navigate' })).toHaveAttribute('href', CUSTOMER.geo_uri)

    const items = screen.getByRole('region', { name: 'Items' })
    expect(items).toHaveTextContent('Items to deliver (2)')
    expect(items).toHaveTextContent('Impact Drill 650W')
    expect(items).not.toHaveTextContent('₹') // no prices
  })

  it('accept → pick up → start, each confirmed by the server', async () => {
    signIn()
    const api = mockApi({
      get: riderGet(),
      post: {
        '/delivery/assignments/7/accept/': accepted(),
        '/delivery/assignments/7/pickup/': pickedUp(),
        '/delivery/assignments/7/start/': onTheWay(),
      },
    })
    const { user } = renderRoute('/rider/jobs/7')
    expect(await screen.findByText('Accept the job, then collect the order at the store.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Accept job' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/delivery/assignments/7/accept/', {}))

    await user.click(await screen.findByRole('button', { name: 'I have picked up the order' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/delivery/assignments/7/pickup/', {}))
    expect(screen.queryByRole('button', { name: 'I can’t take this job' })).not.toBeInTheDocument()

    await user.click(await screen.findByRole('button', { name: 'Start delivery' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/delivery/assignments/7/start/', {}))
    expect(await screen.findByRole('heading', { name: 'Complete the delivery' })).toBeInTheDocument()
    expect(screen.getByText('Out for delivery', { selector: 'span' })).toBeInTheDocument()
  })

  it('shows the server’s refusal, e.g. when the order is not packed yet', async () => {
    signIn()
    mockApi({
      get: riderGet({ '/delivery/assignments/7/': accepted() }),
      post: { '/delivery/assignments/7/pickup/': httpError(409, 'The store hasn’t finished packing this order yet.', 'order_not_packed') },
    })
    const { user } = renderRoute('/rider/jobs/7')
    await user.click(await screen.findByRole('button', { name: 'I have picked up the order' }))
    expect(await screen.findByText('The store hasn’t finished packing this order yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'I have picked up the order' })).toBeEnabled()
  })

  it('rejects a job with a reason', async () => {
    signIn()
    const api = mockApi({
      get: riderGet(),
      post: {
        '/delivery/assignments/7/reject/': job({
          status: 'rejected',
          status_label: 'Rejected by the delivery partner',
          next_actions: [],
          reject_reason: 'Flat tyre',
          drop: { area: 'Kothrud', city: 'Pune' },
        }),
      },
    })
    const { user } = renderRoute('/rider/jobs/7')
    await user.click(await screen.findByRole('button', { name: 'I can’t take this job' }))
    const dialog = await screen.findByRole('dialog', { name: 'Reject this job?' })
    await user.click(within(dialog).getByRole('button', { name: 'Reject job' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Tell the store why')
    expect(api.post).not.toHaveBeenCalled()
    await user.type(within(dialog).getByLabelText('Reason'), 'Flat tyre')
    await user.click(within(dialog).getByRole('button', { name: 'Reject job' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/delivery/assignments/7/reject/', { reason: 'Flat tyre' }))
    expect(await screen.findByText('You rejected this job: Flat tyre')).toBeInTheDocument()
    // The customer's details are gone once the job is over.
    expect(screen.getByRole('region', { name: 'Deliver to (customer)' })).toHaveTextContent('Contact details are shown only while the job is active')
    expect(screen.queryByRole('link', { name: /Call customer/ })).not.toBeInTheDocument()
  })

  it('completes a cash-on-delivery order with the customer’s code and the exact amount', async () => {
    signIn()
    const api = mockApi({
      get: riderGet({ '/delivery/assignments/7/': onTheWay() }),
      post: { '/delivery/assignments/7/complete/': delivered({ received_by: 'Asha' }) },
    })
    const { user } = renderRoute('/rider/jobs/7')
    const form = (await screen.findByRole('heading', { name: 'Complete the delivery' })).closest('form')!
    const submit = within(form).getByRole('button', { name: 'Complete delivery' })

    await user.click(submit)
    expect(within(form).getByRole('alert')).toHaveTextContent('Enter the 6-digit code from the customer.')
    await user.type(within(form).getByLabelText('Delivery code from the customer'), '48 29-13')
    expect(within(form).getByLabelText('Delivery code from the customer')).toHaveValue('482913')
    await user.click(submit)
    expect(within(form).getByRole('alert')).toHaveTextContent('Collect ₹1,200 from the customer and tick the box.')
    expect(api.post).not.toHaveBeenCalled()

    await user.click(within(form).getByRole('checkbox', { name: /I have received ₹1,200/ }))
    await user.type(within(form).getByLabelText(/Received by/), 'Asha')
    await user.click(submit)
    await waitFor(() =>
      expect(lastBody(api.post, '/delivery/assignments/7/complete/')).toEqual({
        otp: '482913',
        cod_collected: true,
        cod_amount: '1200.00',
        cod_method: 'cash',
        cod_reference: '',
        received_by: 'Asha',
      }),
    )
    const outcome = await screen.findByText(/You earned ₹41.20 for this job/)
    expect(outcome.closest('div')).toHaveTextContent('Collected ₹1,200 (cash). Hand this cash over to the store.')
    expect(screen.queryByRole('heading', { name: 'Complete the delivery' })).not.toBeInTheDocument()
  })

  it('a wrong code is reported, the field is cleared and the delivery stays open', async () => {
    signIn()
    const api = mockApi({
      get: riderGet({ '/delivery/assignments/7/': onTheWay() }),
      post: { '/delivery/assignments/7/complete/': httpError(400, 'That code is not correct. 4 tries left.', 'otp_invalid') },
    })
    const { user } = renderRoute('/rider/jobs/7')
    const form = (await screen.findByRole('heading', { name: 'Complete the delivery' })).closest('form')!
    await user.type(within(form).getByLabelText('Delivery code from the customer'), '111111')
    await user.click(within(form).getByRole('checkbox', { name: /I have received/ }))
    await user.click(within(form).getByRole('button', { name: 'Complete delivery' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent('That code is not correct. 4 tries left.')
    expect(within(form).getByLabelText('Delivery code from the customer')).toHaveValue('')
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('heading', { name: 'Complete the delivery' })).toBeInTheDocument()
  })

  it('tells the rider what to do about a blocked code, and never shows the code', async () => {
    signIn()
    mockApi({ get: riderGet({ '/delivery/assignments/7/': onTheWay({ otp_state: 'locked' }) }) })
    renderRoute('/rider/jobs/7')
    expect(await screen.findByText(/blocked after too many wrong tries/)).toHaveTextContent(
      'Ask the customer to get a new code on their order page.',
    )
    expect(screen.getByLabelText('Delivery code from the customer')).toHaveValue('')
  })

  it('UPI payment and an online-paid order', async () => {
    signIn()
    const api = mockApi({
      get: riderGet({ '/delivery/assignments/7/': onTheWay() }),
      post: { '/delivery/assignments/7/complete/': delivered() },
    })
    const first = renderRoute('/rider/jobs/7')
    const form = (await screen.findByRole('heading', { name: 'Complete the delivery' })).closest('form')!
    await first.user.type(within(form).getByLabelText('Delivery code from the customer'), '482913')
    await first.user.click(within(form).getByRole('radio', { name: 'UPI to the store' }))
    await first.user.type(within(form).getByLabelText(/UPI reference/), 'UPI778899')
    await first.user.click(within(form).getByRole('checkbox', { name: /I have received/ }))
    await first.user.click(within(form).getByRole('button', { name: 'Complete delivery' }))
    await waitFor(() =>
      expect(lastBody(api.post, '/delivery/assignments/7/complete/')).toMatchObject({ cod_method: 'upi', cod_reference: 'UPI778899' }),
    )
    first.unmount()

    const paid = onTheWay({ payment_method: 'online', amount_to_collect: null, cod: null })
    const api2 = mockApi({
      get: riderGet({ '/delivery/assignments/7/': paid }),
      post: { '/delivery/assignments/7/complete/': delivered({ cod: null }) },
    })
    const second = renderRoute('/rider/jobs/7')
    expect(await screen.findByText('Already paid online. Do not collect money.')).toBeInTheDocument()
    const form2 = screen.getByRole('heading', { name: 'Complete the delivery' }).closest('form')!
    expect(within(form2).queryByRole('checkbox')).not.toBeInTheDocument()
    await second.user.type(within(form2).getByLabelText('Delivery code from the customer'), '482913')
    await second.user.click(within(form2).getByRole('button', { name: 'Complete delivery' }))
    await waitFor(() => expect(lastBody(api2.post, '/delivery/assignments/7/complete/')).toEqual({ otp: '482913', received_by: '' }))
  })

  it('uploads a proof-of-delivery photo, and requires it when the store says so', async () => {
    signIn()
    const api = mockApi({
      get: riderGet({ '/delivery/assignments/7/': onTheWay({ proof_required: true, amount_to_collect: null, cod: null }) }),
      post: {
        '/delivery/assignments/7/proof/': onTheWay({ proof_required: true, proof_uploaded: true, amount_to_collect: null, cod: null }),
      },
    })
    const { user } = renderRoute('/rider/jobs/7')
    const form = (await screen.findByRole('heading', { name: 'Complete the delivery' })).closest('form')!
    expect(within(form).getByText('No photo yet.')).toBeInTheDocument()
    await user.type(within(form).getByLabelText('Delivery code from the customer'), '482913')
    await user.click(within(form).getByRole('button', { name: 'Complete delivery' }))
    expect(within(form).getByRole('alert')).toHaveTextContent('Take a photo of the delivery first.')

    const file = new File(['jpeg-bytes'], 'door.jpg', { type: 'image/jpeg' })
    await user.upload(within(form).getByLabelText(/Photo of the delivery/), file)
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
    const [url, body] = api.post.mock.calls[0]!
    expect(url).toBe('/delivery/assignments/7/proof/')
    expect((body as FormData).get('photo')).toBe(file)
    expect(await within(form).findByText('Photo saved. Choose another to replace it.')).toBeInTheDocument()
  })

  it('reports a failed delivery with a reason', async () => {
    signIn()
    const api = mockApi({
      get: riderGet({ '/delivery/assignments/7/': onTheWay() }),
      post: {
        '/delivery/assignments/7/fail/': job({
          status: 'failed',
          status_label: 'Delivery failed',
          next_actions: [],
          amount_to_collect: null,
          failed_at: '2026-09-28T09:10:00Z',
          failure_code: 'customer_unavailable',
          failure_reason: 'Customer not available: Rang three times',
        }),
      },
    })
    const { user } = renderRoute('/rider/jobs/7')
    await user.click(await screen.findByRole('button', { name: 'Delivery not possible' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delivery not possible?' })
    expect(dialog).toHaveTextContent('Bring the goods back to the store')
    await user.click(within(dialog).getByRole('button', { name: 'Report failed' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Choose a reason.')
    await user.click(within(dialog).getByRole('radio', { name: 'Other' }))
    await user.click(within(dialog).getByRole('button', { name: 'Report failed' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Describe what happened.')

    await user.click(within(dialog).getByRole('radio', { name: 'Customer not available' }))
    await user.type(within(dialog).getByLabelText(/Details/), 'Rang three times')
    await user.click(within(dialog).getByRole('button', { name: 'Report failed' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/delivery/assignments/7/fail/', {
        reason: 'customer_unavailable',
        note: 'Rang three times',
      }),
    )
    expect(await screen.findByText('Customer not available: Rang three times')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Complete the delivery' })).not.toBeInTheDocument()
  })

  it('saves a delivery note', async () => {
    signIn()
    const api = mockApi({
      get: riderGet({ '/delivery/assignments/7/': accepted() }),
      patch: { '/delivery/assignments/7/notes/': accepted({ delivery_notes: 'Gate 2, ring twice' }) },
    })
    const { user } = renderRoute('/rider/jobs/7')
    const field = await screen.findByLabelText(/Delivery note for the store/)
    expect(screen.getByRole('button', { name: 'Save note' })).toBeDisabled()
    await user.type(field, 'Gate 2, ring twice')
    await user.click(screen.getByRole('button', { name: 'Save note' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/delivery/assignments/7/notes/', { notes: 'Gate 2, ring twice' }))
    expect(await screen.findByText('Note saved')).toBeInTheDocument()
  })

  it('a finished delivery shows cash handed over and no actions', async () => {
    signIn()
    mockApi({
      get: riderGet({
        '/delivery/assignments/7/': delivered({
          cod: { ...delivered().cod!, handed_over: true, handed_over_at: '2026-09-28T12:00:00Z' },
          delivery_notes: 'Left with the guard',
        }),
      }),
    })
    renderRoute('/rider/jobs/7')
    const outcome = (await screen.findByText(/You earned ₹41.20/)).closest('div')!
    expect(outcome).toHaveTextContent('Collected ₹1,200 (cash). Handed over to the store 28 Sept, 5:30 pm.')
    expect(screen.getByText('Left with the guard')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Accept|pick|Start|Complete|not possible|Save note/ })).not.toBeInTheDocument()
  })

  it('someone else’s job or an unknown one is not found', async () => {
    signIn()
    mockApi({ get: riderGet({ '/delivery/assignments/99/': httpError(404, 'Not found.', 'not_found') }) })
    const first = renderRoute('/rider/jobs/99')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    first.unmount()
    renderRoute('/rider/jobs/abc')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})

describe('rider app: a return pickup', () => {
  const pickupJob = (o: Partial<Job> = {}) =>
    job({
      kind: 'return_pickup',
      kind_label: 'Return pickup from the customer',
      return_number: 'RT260928ABCDEF',
      amount_to_collect: null,
      cod: null,
      pickup: CUSTOMER,
      drop: STORE,
      items: [{ name: 'Impact Drill 650W', variant: '', sku: 'DEMO-DRILL', quantity: 1 }],
      ...o,
    })

  it('collects from the customer and hands over at the store, without code or cash', async () => {
    signIn()
    const collected = pickupJob({ status: 'picked_up', status_label: 'Picked up', next_actions: ['proof', 'complete', 'fail'] })
    const api = mockApi({
      get: riderGet({ '/delivery/assignments/7/': pickupJob({ status: 'accepted', status_label: 'Accepted', next_actions: ['pickup', 'reject', 'fail'] }) }),
      post: {
        '/delivery/assignments/7/pickup/': collected,
        '/delivery/assignments/7/complete/': pickupJob({
          status: 'delivered',
          status_label: 'Delivered',
          next_actions: [],
          delivered_at: '2026-09-28T09:00:00Z',
          earning_amount: '41.20',
          pickup: { area: 'Kothrud', city: 'Pune' },
        }),
      },
    })
    const { user } = renderRoute('/rider/jobs/7')
    expect(await screen.findByRole('heading', { name: 'Return pickup · OD260928ABCDEF' })).toBeInTheDocument()
    expect(screen.getByText(/return RT260928ABCDEF/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Collect from (customer)' })).toHaveTextContent('Asha Kumar')
    expect(screen.getByRole('region', { name: 'Bring to (store)' })).toHaveTextContent('Demo Store — Kothrud')
    expect(screen.getByRole('region', { name: 'Items' })).toHaveTextContent('Items to collect (1)')
    expect(screen.queryByText(/Do not collect money|Cash on delivery/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pickup not possible' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'I have collected the items' }))
    const form = (await screen.findByRole('heading', { name: 'Hand over at the store' })).closest('form')!
    expect(within(form).queryByLabelText(/Delivery code/)).not.toBeInTheDocument()
    expect(within(form).getByLabelText(/Photo of the collected items/)).toBeInTheDocument()
    await user.click(within(form).getByRole('button', { name: 'Handed over at the store' }))
    await waitFor(() => expect(lastBody(api.post, '/delivery/assignments/7/complete/')).toEqual({ received_by: '' }))
    expect(await screen.findByText(/Handed over at the store 28 Sept/)).toBeInTheDocument()
  })
})
