import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  adminCategories,
  assignedShipment,
  codRow,
  conversation,
  coupon,
  customerDetail,
  customerRow,
  offer,
  page,
  refund,
  returnRequest,
  rider,
  staffGet,
  staffShipment,
} from '@/test/adminFixtures'
import { httpError, mockApi, paramsSent, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

type Api = ReturnType<typeof mockApi>
const lastBody = (spy: Api['post'] | Api['patch'], url: string) => spy.mock.calls.filter(([called]) => called === url).at(-1)?.[1]

describe('delivery', () => {
  const shipments = ({ params }: RequestInfo) =>
    page(params.scope === 'active' ? [assignedShipment({ id: 32, order_number: 'OD260929ACTIVE' })] : [staffShipment()])

  it('shows shipments waiting for a rider, and those with a rider', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/delivery/shipments/': shipments }) })
    const { user, router } = renderRoute('/admin/delivery')
    const table = await screen.findByRole('table', { name: 'Shipments' })
    const row = within(within(table).getByRole('row', { name: /OD260929ABCDEF/ }))
    expect(row.getByText('Not assigned')).toBeInTheDocument()
    expect(row.getByRole('button', { name: 'Assign rider for order OD260929ABCDEF' })).toBeInTheDocument()
    expect(paramsSent(api.get, '/delivery/shipments/')[0]).toMatchObject({ scope: 'waiting' })

    await user.click(screen.getByRole('button', { name: 'With a rider' }))
    const active = within(await screen.findByRole('row', { name: /OD260929ACTIVE/ }))
    expect(active.getByText('Ravi Rider')).toBeInTheDocument()
    expect(currentUrl(router)).toBe('/admin/delivery?scope=active')
    expect(active.getByRole('button', { name: 'Reassign for order OD260929ACTIVE' })).toBeInTheDocument()
  })

  it('reassigns and unassigns through the delivery API', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        '/delivery/shipments/': shipments,
        '/delivery/shipments/32/eligible-partners/': [
          { partner_id: 6, full_name: 'Imran Shaikh', vehicle_type: 'van', same_store: true, active_assignments: 0, capacity: 3, distance_km: 0.4 },
        ],
      }),
      post: { '/delivery/shipments/32/reassign/': assignedShipment(), '/delivery/shipments/32/unassign/': staffShipment() },
    })
    const { user } = renderRoute('/admin/delivery?scope=active')
    await user.click(await screen.findByRole('button', { name: 'Reassign for order OD260929ACTIVE' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Reassign order OD260929ACTIVE' }))
    await user.click(await dialog.findByRole('radio', { name: /Imran Shaikh/ }))
    await user.type(dialog.getByLabelText('Reason (optional)'), 'Ravi’s scooter broke down')
    await user.click(dialog.getByRole('button', { name: 'Reassign' }))
    await waitFor(() =>
      expect(lastBody(api.post, '/delivery/shipments/32/reassign/')).toEqual({ partner_id: 6, reason: 'Ravi’s scooter broke down' }),
    )

    await user.click(await screen.findByRole('button', { name: 'Unassign order OD260929ACTIVE' }))
    const confirm = within(screen.getByRole('dialog', { name: 'Take order OD260929ACTIVE off the rider?' }))
    await user.click(confirm.getByRole('button', { name: 'Unassign' }))
    await waitFor(() => expect(lastBody(api.post, '/delivery/shipments/32/unassign/')).toEqual({ reason: '' }))
  })

  it('shows what the server says when a rider can’t be taken off a job', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', { '/delivery/shipments/': shipments }),
      post: { '/delivery/shipments/32/unassign/': httpError(409, 'The rider has already picked up the goods.', 'invalid_delivery_state') },
    })
    const { user } = renderRoute('/admin/delivery?scope=active')
    await user.click(await screen.findByRole('button', { name: 'Unassign order OD260929ACTIVE' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.click(dialog.getByRole('button', { name: 'Unassign' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('The rider has already picked up the goods.')
  })

  it('lists riders with status, load, cash and earnings', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        '/admin/riders/': page([
          rider(),
          rider({ partner_id: 9, full_name: 'New Rider', status: 'offline', is_verified: false, cash_in_hand: '0.00', can_take_jobs: false }),
        ]),
      }),
      patch: { '/admin/riders/9/': rider({ partner_id: 9, full_name: 'New Rider' }) },
    })
    const { user } = renderRoute('/admin/delivery?tab=riders')
    const table = await screen.findByRole('table', { name: 'Delivery partners' })
    const ravi = within(within(table).getByRole('row', { name: /Ravi Rider/ }))
    expect(ravi.getByText('Online')).toBeInTheDocument()
    expect(ravi.getByText('0 of 2')).toBeInTheDocument()
    expect(ravi.getByText('3 today · 1 failed')).toBeInTheDocument()
    expect(ravi.getByText('₹5,100')).toBeInTheDocument()
    expect(ravi.getByRole('link', { name: '₹1,200' })).toHaveAttribute('href', '/admin/delivery?tab=cod&handed_over=false&partner=4')

    const newcomer = within(within(table).getByRole('row', { name: /New Rider/ }))
    expect(newcomer.getByText('Not verified')).toBeInTheDocument()
    await user.click(newcomer.getByRole('button', { name: 'Verify New Rider' }))
    const dialog = within(screen.getByRole('dialog', { name: 'New Rider' }))
    await user.click(dialog.getByLabelText(/^Verified/))
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(lastBody(api.patch, '/admin/riders/9/')).toEqual({
        max_active_assignments: 2,
        home_store: 1,
        is_verified: true,
        is_active: true,
      }),
    )
  })

  it('a store manager sees riders but can’t verify or edit them', async () => {
    signIn()
    mockApi({ get: staffGet('manager', { '/admin/riders/': page([rider({ is_verified: false })]) }) })
    renderRoute('/admin/delivery?tab=riders')
    await screen.findByRole('table', { name: 'Delivery partners' })
    expect(screen.queryByRole('button', { name: /Verify|Edit/ })).not.toBeInTheDocument()
  })

  it('records cash handed over by a rider, after a confirmation', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/delivery/cod/': page([codRow(), codRow({ assignment_id: 6, order_number: 'OD260928UPIPAY', cod_method: 'upi', cod_reference: 'UPI123' })]) }),
      post: { '/delivery/cod/5/handover/': codRow({ handed_over: true }) },
    })
    const { user } = renderRoute('/admin/delivery?tab=cod&handed_over=false')
    const table = await screen.findByRole('table', { name: 'Cash-on-delivery collections' })
    expect(paramsSent(api.get, '/delivery/cod/')[0]).toMatchObject({ handed_over: 'false' })
    expect(within(within(table).getByRole('row', { name: /OD260928UPIPAY/ })).getByText('Paid to the store by UPI')).toBeInTheDocument()

    await user.click(within(table).getByRole('button', { name: 'Cash received for order OD260929ABCDEF' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Cash received from the rider?' }))
    expect(dialog.getByText('₹1,200')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
    await user.type(dialog.getByLabelText('Note (optional)'), 'Counted at the till')
    await user.click(dialog.getByRole('button', { name: 'Yes, cash received' }))
    await waitFor(() => expect(lastBody(api.post, '/delivery/cod/5/handover/')).toEqual({ note: 'Counted at the till' }))
  })

  it('shows failed and completed jobs', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        '/admin/jobs/': page([
          {
            id: 5, kind: 'delivery', kind_label: 'Delivery', status: 'failed', status_label: 'Delivery failed', partner_id: 4,
            partner_name: 'Ravi Rider', assigned_at: '2026-09-29T06:00:00Z', delivered_at: null, failed_at: '2026-09-29T07:00:00Z',
            failure_code: 'customer_unavailable', failure_reason: 'Nobody home', reject_reason: '', completed_without_otp: false,
            proof_available: false, cod_amount_due: '0.00', cod_collected_amount: null, earning_amount: '20.00',
            order_number: 'OD260929ABCDEF', order_status: 'delivery_failed', shipment_id: 31, store_name: 'Kothrud Store',
            return_number: null, distance_km: '2.70',
          },
        ]),
      }),
    }) // prettier-ignore
    const { user } = renderRoute('/admin/delivery?tab=jobs')
    const row = within(await screen.findByRole('row', { name: /OD260929ABCDEF/ }))
    expect(row.getByText('Delivery failed')).toBeInTheDocument()
    expect(row.getByText('Nobody home')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Status'), 'Failed')
    await waitFor(() => expect(paramsSent(api.get, '/admin/jobs/').at(-1)).toMatchObject({ status: 'failed' }))
  })
})

describe('offers and coupons', () => {
  const rulesGet = (extra: Record<string, unknown> = {}) => ({
    '/admin/categories/': adminCategories,
    '/admin/offers/': page([offer(), offer({ id: 4, name: 'Diwali sale', state: 'scheduled', summary: '₹200 off on the whole cart, from ₹2000' })]),
    '/admin/coupons/': page([coupon()]),
    ...extra,
  })

  it('lists offers with the discount in the server’s words', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', rulesGet()) })
    renderRoute('/admin/offers')
    const table = await screen.findByRole('table', { name: 'Offers' })
    const row = within(within(table).getByRole('row', { name: /Tools week/ }))
    expect(row.getByText('10% off (up to ₹400) on Tools')).toBeInTheDocument()
    expect(row.getByText('Running')).toBeInTheDocument()
    expect(within(within(table).getByRole('row', { name: /Diwali sale/ })).getByText('Scheduled')).toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalledWith('/admin/coupons/', expect.anything())
  })

  it('creates a percentage offer for a category, with minimum spend and dates', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', rulesGet()), post: { '/admin/offers/': offer() } })
    const { user } = renderRoute('/admin/offers')
    await user.click(await screen.findByRole('button', { name: 'Add offer' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Add offer' }))
    await user.type(dialog.getByLabelText(/^Name/), 'Monsoon sale')
    await user.type(dialog.getByLabelText(/^Percent off/), '15')
    await user.type(dialog.getByLabelText(/^At most/), '500')
    await user.type(dialog.getByLabelText(/^Minimum spend/), '1500')
    const starts = dialog.getByLabelText(/^Starts/)
    await user.clear(starts)
    await user.type(starts, '2026-10-01T09:00')
    await user.type(dialog.getByLabelText(/^Ends/), '2026-10-15T21:00')
    await user.selectOptions(dialog.getByLabelText('Add a category'), 'Tools')
    expect(dialog.getByText('Only the chosen categories and products.')).toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(lastBody(api.post, '/admin/offers/')).toEqual({
      name: 'Monsoon sale',
      description: '',
      discount_type: 'percent',
      value: '15',
      max_discount_amount: '500',
      min_order_value: '1500',
      starts_at: new Date('2026-10-01T09:00').toISOString(),
      ends_at: new Date('2026-10-15T21:00').toISOString(),
      is_active: true,
      priority: 100,
      categories: [10],
      products: [],
    })
  })

  it('refuses rules that make no sense before asking the server', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', rulesGet()), post: {} })
    const { user } = renderRoute('/admin/offers')
    await user.click(await screen.findByRole('button', { name: 'Add offer' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.type(dialog.getByLabelText(/^Name/), 'Too good')
    await user.type(dialog.getByLabelText(/^Percent off/), '120')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('A percentage can’t be more than 100.')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('creates a fixed-amount coupon that is shown at checkout', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', rulesGet()), post: { '/admin/coupons/': coupon() } })
    const { user } = renderRoute('/admin/coupons')
    const row = within(await screen.findByRole('row', { name: /WELCOME50/ }))
    expect(row.getByText('₹50 off on the whole cart, from ₹500')).toBeInTheDocument()
    expect(row.getByText('12 of 100')).toBeInTheDocument()
    expect(row.getByText('Shown')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add coupon' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Add coupon' }))
    await user.type(dialog.getByLabelText(/^Code/), 'festive100')
    await user.selectOptions(dialog.getByLabelText('Discount'), 'Fixed amount (₹)')
    expect(dialog.queryByLabelText(/^At most/)).not.toBeInTheDocument() // a cap is for percentages
    await user.type(dialog.getByLabelText(/^Amount off/), '100')
    await user.type(dialog.getByLabelText(/^Total uses/), '200')
    await user.click(dialog.getByLabelText(/^Show at checkout/))
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(lastBody(api.post, '/admin/coupons/')).toMatchObject({
      code: 'FESTIVE100',
      discount_type: 'fixed',
      value: '100',
      max_discount_amount: null,
      min_order_value: '0',
      usage_limit: 200,
      per_customer_limit: 1,
      show_in_checkout: true,
      categories: [],
      products: [],
    })
  })

  it('switches a rule off, and explains why a used coupon can’t be deleted', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', rulesGet()),
      patch: { '/admin/coupons/6/': coupon({ is_active: false, state: 'inactive' }) },
      delete: { '/admin/coupons/6/': httpError(409, 'This coupon has been used, so it is kept for the records. Deactivate it instead.', 'coupon_in_use') },
    })
    const { user } = renderRoute('/admin/coupons')
    await user.click(await screen.findByRole('button', { name: 'Switch off WELCOME50' }))
    await waitFor(() => expect(lastBody(api.patch, '/admin/coupons/6/')).toEqual({ is_active: false }))

    await user.click(screen.getByRole('button', { name: 'Delete WELCOME50' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Delete WELCOME50?' }))
    await user.click(dialog.getByRole('button', { name: 'Delete coupon' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('This coupon has been used')
  })

  it('edits an offer with its targets filled in', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', rulesGet()), patch: { '/admin/offers/3/': offer() } })
    const { user } = renderRoute('/admin/offers')
    await user.click(await screen.findByRole('button', { name: 'Edit Tools week' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Edit offer' }))
    expect(dialog.getByLabelText(/^Name/)).toHaveValue('Tools week')
    expect(dialog.getByLabelText(/^Percent off/)).toHaveValue('10.00')
    await user.click(dialog.getByRole('button', { name: /Tools.*remove/ }))
    expect(dialog.getByText(/^The whole cart/)).toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(lastBody(api.patch, '/admin/offers/3/')).toMatchObject({ name: 'Tools week', categories: [] }))
  })
})

describe('customers', () => {
  it('lists customers with orders and spend, and never a password', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/customers/': page([customerRow(), customerRow({ id: 8, full_name: 'Ravi Shah', email: 'ravi.s@example.com', is_active: false, order_count: 0, total_spend: '0.00', last_order_at: null })]) }),
    })
    const { user, container } = renderRoute('/admin/customers')
    const table = await screen.findByRole('table', { name: 'Customers' })
    const asha = within(within(table).getByRole('row', { name: /Asha Kulkarni/ }))
    expect(asha.getByText('asha@example.com')).toBeInTheDocument()
    expect(asha.getByText('9')).toBeInTheDocument()
    expect(asha.getByText('₹18,450')).toBeInTheDocument()
    expect(asha.getByText('Active')).toBeInTheDocument()
    expect(within(within(table).getByRole('row', { name: /Ravi Shah/ })).getByText('Deactivated')).toBeInTheDocument()
    expect(container.textContent?.toLowerCase()).not.toContain('password hash')
    expect(container.querySelector('input[type="password"]')).toBeNull()

    await user.type(screen.getByLabelText('Search by name, email or phone'), '98765{Enter}')
    await user.selectOptions(screen.getByLabelText('Sort'), 'Highest spend')
    await waitFor(() => expect(paramsSent(api.get, '/admin/customers/').at(-1)).toMatchObject({ q: '98765', ordering: '-total_spend' }))
  })

  it('shows a customer with contact details, totals and recent orders', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/customers/7/': customerDetail() }) })
    renderRoute('/admin/customers/7')
    expect(await screen.findByRole('heading', { name: 'Asha Kulkarni', level: 1 })).toBeInTheDocument()
    const contact = within(screen.getByRole('region', { name: 'Contact' }))
    expect(contact.getByRole('link', { name: '9876543210' })).toHaveAttribute('href', 'tel:9876543210')
    expect(contact.getByText('Kothrud, Pune, 411038')).toBeInTheDocument()
    const orders = within(screen.getByRole('region', { name: 'Recent orders' }))
    expect(orders.getByRole('link', { name: 'OD260927ZZZZZZ' })).toHaveAttribute('href', '/admin/orders/OD260927ZZZZZZ')
    expect(orders.getByRole('link', { name: 'All orders' })).toHaveAttribute('href', '/admin/orders?customer=7')
  })

  it('deactivates an account after a confirmation', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/customers/7/': customerDetail() }),
      patch: { '/admin/users/7/': { id: 7, is_active: false } },
    })
    const { user } = renderRoute('/admin/customers/7')
    await user.click(await screen.findByRole('button', { name: 'Deactivate account' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Deactivate Asha Kulkarni?' }))
    expect(api.patch).not.toHaveBeenCalled()
    await user.click(dialog.getByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(lastBody(api.patch, '/admin/users/7/')).toEqual({ is_active: false }))
  })

  it('changes a role, and shows the server’s refusal', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/customers/7/': customerDetail() }),
      patch: { '/admin/users/7/': httpError(409, 'This person still has an active delivery.', 'active_delivery') },
    })
    const { user } = renderRoute('/admin/customers/7')
    const change = await screen.findByRole('button', { name: 'Change role' })
    expect(change).toBeDisabled()
    await user.selectOptions(screen.getByLabelText('Role'), 'Store manager')
    await user.click(change)
    const dialog = within(screen.getByRole('dialog', { name: 'Make Asha Kulkarni store manager?' }))
    await user.click(dialog.getByRole('button', { name: 'Change role' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('This person still has an active delivery.')
    expect(lastBody(api.patch, '/admin/users/7/')).toEqual({ role: 'store_manager' })
  })

  it('doesn’t offer changes to one’s own account', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/customers/1/': customerDetail({ id: 1, full_name: 'Meera Owner', role: 'admin' }) }) })
    renderRoute('/admin/customers/1')
    expect(await screen.findByText(/This is your own account/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Deactivate account' })).not.toBeInTheDocument()
  })
})

describe('returns and refunds', () => {
  it('approves a return request', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/returns/': page([returnRequest()]) }),
      post: { '/returns/RT260929AAAAAA/approve/': returnRequest({ status: 'approved', status_label: 'Approved' }) },
    })
    const { user } = renderRoute('/admin/returns?status=open')
    const row = within(await screen.findByRole('row', { name: /RT260929AAAAAA/ }))
    expect(paramsSent(api.get, '/returns/')[0]).toMatchObject({ status: 'open' })
    expect(row.getByText('1 × Impact Drill 650W')).toBeInTheDocument()
    expect(row.getByText('₹3,200')).toBeInTheDocument()
    expect(row.queryByRole('button', { name: /Items received/ })).not.toBeInTheDocument() // not approved yet

    await user.click(row.getByRole('button', { name: 'Approve RT260929AAAAAA' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Approve this return?' }))
    expect(dialog.getByText('“The chuck is cracked.”')).toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(lastBody(api.post, '/returns/RT260929AAAAAA/approve/')).toEqual({ note: '' }))
  })

  it('needs a reason to reject', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/returns/': page([returnRequest()]) }),
      post: { '/returns/RT260929AAAAAA/reject/': returnRequest({ status: 'rejected', status_label: 'Rejected' }) },
    })
    const { user } = renderRoute('/admin/returns')
    await user.click(await screen.findByRole('button', { name: 'Reject RT260929AAAAAA' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Reject this return?' }))
    expect(dialog.getByLabelText(/^Reason/)).toBeRequired()
    await user.type(dialog.getByLabelText(/^Reason/), 'Used and outside the return window')
    await user.click(dialog.getByRole('button', { name: 'Reject' }))
    await waitFor(() =>
      expect(lastBody(api.post, '/returns/RT260929AAAAAA/reject/')).toEqual({ note: 'Used and outside the return window' }),
    )
  })

  it('receives items without restocking damaged goods, and never sends an amount', async () => {
    signIn()
    const approved = returnRequest({ status: 'approved', status_label: 'Approved' })
    const api = mockApi({
      get: staffGet('admin', { '/returns/': page([approved]) }),
      post: { '/returns/RT260929AAAAAA/receive/': returnRequest({ status: 'received', status_label: 'Received', refund_status: 'pending' }) },
    })
    const { user } = renderRoute('/admin/returns')
    await user.click(await screen.findByRole('button', { name: 'Items received RT260929AAAAAA' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Items received back?' }))
    expect(dialog.getByText(/The amount is what the customer paid for these units; it can’t be changed here/)).toBeInTheDocument()
    expect(dialog.queryByRole('spinbutton')).not.toBeInTheDocument() // no amount to type
    expect(dialog.getByLabelText(/^Put the items back on sale/)).not.toBeChecked() // damaged
    await user.click(dialog.getByRole('button', { name: 'Items received' }))
    await waitFor(() => expect(lastBody(api.post, '/returns/RT260929AAAAAA/receive/')).toEqual({ note: '', restock: false }))
    expect(await screen.findByText('Return RT260929AAAAAA received. The refund has been started.')).toBeInTheDocument()
  })

  it('sends a failed refund again', async () => {
    signIn()
    const id = refund().public_id
    const api = mockApi({
      get: staffGet('admin', { '/payments/refunds/': page([refund()]) }),
      post: { [`/payments/refunds/${id}/retry/`]: refund({ status: 'processed', processed_at: '2026-09-29T08:00:00Z' }) },
    })
    const { user } = renderRoute('/admin/refunds?status=failed')
    const row = within(await screen.findByRole('row', { name: /Asha Kulkarni/ }))
    expect(row.getByText('₹900')).toBeInTheDocument()
    expect(row.getByText('Gateway timeout (1 attempt)')).toBeInTheDocument()
    await user.click(row.getByRole('button', { name: 'Try again refund for order OD260927ZZZZZZ' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Send this refund again?' }))
    await user.click(dialog.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(lastBody(api.post, `/payments/refunds/${id}/retry/`)).toEqual({}))
    expect(await screen.findByText('Refund sent.')).toBeInTheDocument()
  })

  it('records a cash refund paid by hand, with a reference', async () => {
    signIn()
    const manual = refund({ status: 'pending', is_manual: true, payment_provider: 'cod', failure_reason: '' })
    const api = mockApi({
      get: staffGet('admin', { '/payments/refunds/': page([manual]) }),
      post: { [`/payments/refunds/${manual.public_id}/mark-processed/`]: refund({ status: 'processed', is_manual: true }) },
    })
    const { user } = renderRoute('/admin/refunds')
    const row = within(await screen.findByRole('row', { name: /Asha Kulkarni/ }))
    expect(row.getByText('Paid by the store')).toBeInTheDocument()
    expect(row.queryByRole('button', { name: /Try again/ })).not.toBeInTheDocument()
    await user.click(row.getByRole('button', { name: 'Paid by hand refund for order OD260927ZZZZZZ' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Refund paid by hand?' }))
    expect(dialog.getByLabelText(/^Reference/)).toBeRequired()
    await user.type(dialog.getByLabelText(/^Reference/), 'UPI 4521')
    await user.click(dialog.getByRole('button', { name: 'Record as paid' }))
    await waitFor(() =>
      expect(lastBody(api.post, `/payments/refunds/${manual.public_id}/mark-processed/`)).toEqual({ reference: 'UPI 4521' }),
    )
  })

  it('a refund that is paid has nothing left to do', async () => {
    signIn()
    mockApi({
      get: staffGet('manager', { '/payments/refunds/': page([refund({ status: 'processed', processed_at: '2026-09-29T08:00:00Z', provider_refund_id: 'rfnd_1' })]) }),
    })
    renderRoute('/admin/refunds')
    const row = within(await screen.findByRole('row', { name: /Asha Kulkarni/ }))
    expect(row.getByText('Processed')).toBeInTheDocument()
    expect(row.queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('support', () => {
  it('lists the conversations that are waiting', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/admin/support/': page([conversation()]) }) })
    const { user } = renderRoute('/admin/support')
    const row = within(await screen.findByRole('row', { name: /Wrong size delivered/ }))
    expect(row.getByText('Asha Kulkarni')).toBeInTheDocument()
    expect(row.getByText('Needs a reply')).toBeInTheDocument()
    expect(row.getByRole('link', { name: 'OD260927ZZZZZZ' })).toHaveAttribute('href', '/admin/orders/OD260927ZZZZZZ')
    expect(paramsSent(api.get, '/admin/support/')[0]).toMatchObject({ status: 'active' })

    await user.selectOptions(screen.getByLabelText('Handled by'), 'Me')
    await waitFor(() => expect(paramsSent(api.get, '/admin/support/').at(-1)).toMatchObject({ mine: 'true' }))
  })

  it('shows the messages and sends a reply', async () => {
    signIn()
    let current = conversation()
    const api = mockApi({
      get: staffGet('admin', { '/admin/support/12/': () => current }),
      post: {
        '/admin/support/12/reply/': ({ body }: RequestInfo) => {
          current = conversation({
            status: 'waiting_customer',
            status_label: 'Waiting for customer',
            assigned_to: 1,
            assigned_to_name: 'Meera Owner',
            waiting_for_reply: false,
            messages: [
              ...conversation().messages,
              { id: 2, sender_type: 'agent', sender_name: 'Meera Owner', body: (body as { body: string }).body, created_at: '2026-09-29T06:10:00Z' },
            ],
          })
          return current
        },
      },
    })
    const { user } = renderRoute('/admin/support/12')
    expect(await screen.findByText('I got the 10 mm, I ordered 12 mm.')).toBeInTheDocument()
    const send = screen.getByRole('button', { name: 'Send reply' })
    expect(send).toBeDisabled()
    await user.type(screen.getByLabelText(/^Your reply/), 'Sorry about that. We’ll exchange it today.')
    await user.click(send)
    await waitFor(() => expect(lastBody(api.post, '/admin/support/12/reply/')).toEqual({ body: 'Sorry about that. We’ll exchange it today.' }))
    expect(await screen.findByText('Sorry about that. We’ll exchange it today.', { selector: 'p' })).toBeInTheDocument()
    expect(screen.getByLabelText(/^Your reply/)).toHaveValue('')
    expect(screen.getByLabelText('Status')).toHaveValue('waiting_customer')
  })

  it('changes the status and takes over a conversation', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('manager', { '/admin/support/12/': conversation() }),
      patch: { '/admin/support/12/': conversation({ status: 'resolved', status_label: 'Resolved' }) },
    })
    const { user } = renderRoute('/admin/support/12')
    await user.click(await screen.findByRole('button', { name: 'I’ll handle this' }))
    await waitFor(() => expect(lastBody(api.patch, '/admin/support/12/')).toEqual({ assign_to_me: true }))
    await user.selectOptions(screen.getByLabelText('Status'), 'Resolved')
    await waitFor(() => expect(lastBody(api.patch, '/admin/support/12/')).toEqual({ status: 'resolved' }))
  })

  it('a closed conversation has no reply box', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/support/12/': conversation({ status: 'closed', status_label: 'Closed' }) }) })
    renderRoute('/admin/support/12')
    expect(await screen.findByText('This conversation is closed. Reopen it to reply.')).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Your reply/)).not.toBeInTheDocument()
  })

  it('shows “not found” for a conversation of another store', async () => {
    signIn()
    mockApi({ get: staffGet('manager', { '/admin/support/99/': httpError(404, 'Not found.', 'not_found') }) })
    const { router } = renderRoute('/admin/support/99')
    expect(await screen.findByRole('heading', { name: /not found|can’t find|couldn’t find/i })).toBeInTheDocument()
    expect(currentUrl(router)).toBe('/admin/support/99')
  })
})
