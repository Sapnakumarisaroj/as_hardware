import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { CreditEntry, Wallet } from '@/features/loyalty/api'
import { adminSession, staffGet } from '@/test/adminFixtures'
import { address, checkoutPreview, customer, orderDetail, TOTALS_800 } from '@/test/fixtures'
import { httpError, mockApi, paramsSent, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

/* Phase 17 on the customer and dashboard side: the wallet, using credits at checkout, credits and
   cashback on an order, and the loyalty controls. Every amount comes from the server's ledger. */

vi.mock('@/features/addresses/MapPinPicker', () => ({ default: () => <div data-testid="map" /> }))

function wallet(overrides: Partial<Wallet> = {}): Wallet {
  return {
    balance: '750.00',
    spendable: '750.00',
    pending: '120.00',
    eligible: '80.00',
    earned: '1000.00',
    restored: '50.00',
    used: '300.00',
    expired: '0.00',
    reversed: '40.00',
    expiring_soon: { amount: '250.00', first_expiry: '2026-10-15T10:00:00+05:30', within_days: 14 },
    rules: { enabled: true, max_order_share: '20.00', expiry_days: 90, never_cash: true, referral_reward: '0.00', referee_reward: '0.00', welcome_reward: '0.00' },
    referral: { code: 'ABCD2345', rewards_on: false, joined: 0, rewarded: 0, waiting: 0, credited: '0.00', pending: '0.00', used_code: false },
    welcome: null,
    ...overrides,
  }
}

function entry(overrides: Partial<CreditEntry> = {}): CreditEntry {
  return {
    id: 1,
    kind: 'cashback',
    kind_label: 'Cashback',
    status: 'available',
    status_label: 'Credited',
    amount: '400.00',
    remaining: '250.00',
    available_at: '2026-09-20T10:00:00+05:30',
    expires_at: '2026-12-19T10:00:00+05:30',
    order_number: 'OD1',
    reference: 'OD1',
    description: '2% cashback',
    created_at: '2026-09-10T10:00:00+05:30',
    ...overrides,
  }
}

const shopGet = { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/cart/': checkoutPreview().cart }

describe('wallet', () => {
  it('shows the balance, pending cashback, totals, expiry and the history from the ledger', async () => {
    signIn()
    const api = mockApi({
      get: {
        ...shopGet,
        '/loyalty/wallet/': wallet(),
        '/loyalty/ledger/': ({ params }: RequestInfo) => ({
          count: 3,
          next: null,
          previous: null,
          results:
            params.status === 'pending'
              ? [entry({ id: 3, status: 'pending', status_label: 'Pending', amount: '120.00', remaining: null, expires_at: null })]
              : [
                  entry(),
                  entry({ id: 2, kind: 'redemption', kind_label: 'Used on an order', status: 'posted', status_label: 'Posted', amount: '-300.00', remaining: null, expires_at: null }),
                  entry({ id: 4, status: 'reversed', status_label: 'Reversed', amount: '40.00', remaining: null }),
                ],
        }),
      },
    })
    const { user } = renderRoute('/account/wallet')
    expect(await screen.findByTestId('wallet-balance')).toHaveTextContent('₹750')
    expect(screen.getByRole('note')).toHaveTextContent('₹250 expires within 14 days')
    expect(screen.getByText(/Pays up to 20% of an order/)).toHaveTextContent('not cash')
    const stats = screen.getAllByRole('definition').map((d) => d.textContent)
    expect(stats).toEqual(expect.arrayContaining(['₹200', '₹1,000', '₹300', '₹50', '₹0', '₹40']))

    const rows = await screen.findAllByTestId('ledger-row')
    expect(rows[0]).toHaveTextContent('+₹400')
    expect(rows[0]).toHaveTextContent('₹250 left')
    expect(rows[1]).toHaveTextContent('−₹300')
    expect(rows[2]).toHaveTextContent('Reversed (order cancelled or items returned)')
    expect(within(rows[0]!).getByRole('link', { name: 'Order OD1' })).toHaveAttribute('href', '/account/orders/OD1')

    await user.click(screen.getByRole('button', { name: 'Pending' }))
    await waitFor(() => expect(paramsSent(api.get, '/loyalty/ledger/').at(-1)).toMatchObject({ status: 'pending', page: '1' }))
    expect(await screen.findByText(/becomes usable after delivery and the return window/)).toBeInTheDocument()
  })

  it('explains an empty wallet and offers a referral code', async () => {
    signIn()
    const empty = wallet({ balance: '0.00', spendable: '0.00', pending: '0.00', eligible: '0.00', earned: '0.00', used: '0.00', restored: '0.00', reversed: '0.00', expiring_soon: { amount: '0.00', first_expiry: null, within_days: 14 } })
    const api = mockApi({
      get: { ...shopGet, '/loyalty/wallet/': empty },
      post: { '/loyalty/referral/': ({ body }: RequestInfo) => ((body as { code: string }).code === 'BADCODE1' ? httpError(400, 'That referral code isn’t valid.', 'invalid_referral_code') : { referrer: 'Ravi' }) },
    })
    const { user } = renderRoute('/account/wallet')
    expect(await screen.findByText('No credits yet')).toBeInTheDocument()
    expect(screen.getByText('ABCD2345')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Joined with a friend’s code?'), 'badcode1')
    await user.click(screen.getByRole('button', { name: 'Save code' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That referral code isn’t valid.')
    expect(api.post).toHaveBeenCalledWith('/loyalty/referral/', { code: 'BADCODE1' })
    // Nothing to show: no referral counts, no welcome reward.
    expect(screen.queryByTestId('referral-summary')).not.toBeInTheDocument()
    expect(screen.queryByTestId('welcome-reward')).not.toBeInTheDocument()
  })

  it('shows referral status, the welcome reward and its history label from the server', async () => {
    signIn()
    mockApi({
      get: {
        ...shopGet,
        '/loyalty/wallet/': wallet({
          rules: { ...wallet().rules, referral_reward: '150.00', welcome_reward: '75.00' },
          referral: { code: 'ABCD2345', rewards_on: true, joined: 3, rewarded: 1, waiting: 2, credited: '150.00', pending: '0.00', used_code: true },
          welcome: { amount: '75.00', status: 'eligible', status_label: 'Eligible', available_at: '2026-10-20T10:00:00+05:30', order_number: 'OD1' },
        }),
        '/loyalty/ledger/': {
          count: 1,
          next: null,
          previous: null,
          results: [entry({ kind: 'promo', kind_label: 'Welcome reward', status: 'eligible', amount: '75.00', remaining: null, reference: 'welcome:OD1', description: 'Welcome reward: your first order was delivered' })],
        },
      },
    })
    renderRoute('/account/wallet')
    const summary = await screen.findByTestId('referral-summary')
    expect(summary).toHaveTextContent('Friends joined: 3')
    expect(summary).toHaveTextContent('Waiting for their first delivery: 2')
    expect(summary).toHaveTextContent('Earned you a reward: 1')
    expect(summary).toHaveTextContent('Referral credit received: ₹150')
    expect(summary).not.toHaveTextContent('Waiting for the return window')
    expect(screen.getByTestId('welcome-reward')).toHaveTextContent('Your ₹75 welcome reward is usable from')
    const rows = await screen.findAllByTestId('ledger-row')
    expect(rows[0]).toHaveTextContent('Welcome reward')
    expect(screen.queryByLabelText('Joined with a friend’s code?')).not.toBeInTheDocument()
  })

  it('offers the welcome reward before the first delivered order', async () => {
    signIn()
    mockApi({ get: { ...shopGet, '/loyalty/wallet/': wallet({ welcome: { amount: '50.00', status: 'offer', status_label: 'On your first delivered order' } }), '/loyalty/ledger/': { count: 0, next: null, previous: null, results: [] } } })
    renderRoute('/account/wallet')
    expect(await screen.findByTestId('welcome-reward')).toHaveTextContent('Get ₹50 credit when your first order is delivered')
  })

  it('asks visitors to sign in and shows errors with retry', async () => {
    mockApi({ get: { '/categories/': [] } })
    const first = renderRoute('/account/wallet')
    expect(await screen.findByText('Sign in to see your credits and cashback.')).toBeInTheDocument()
    first.unmount()

    signIn()
    mockApi({ get: { ...shopGet, '/loyalty/wallet/': httpError(500, 'Server error.') } })
    renderRoute('/account/wallet')
    expect(await screen.findByText('Couldn’t load your wallet')).toBeInTheDocument()
  })
})

describe('checkout credits', () => {
  const credits = (useCredits: boolean) => ({
    enabled: true,
    available: '1500.00',
    max_share_percent: '20.00',
    max_usable: '1000.00',
    usable: '1000.00',
    use_credits: useCredits,
    applied: useCredits ? '1000.00' : '0.00',
    remaining_to_pay: useCredits ? '4000.00' : '5000.00',
  })

  it('applies at most what the server allows and sends only the choice', async () => {
    signIn()
    const preview = ({ body }: RequestInfo) => {
      const on = Boolean((body as { use_credits?: boolean }).use_credits)
      return checkoutPreview({
        totals: { ...TOTALS_800, subtotal: '5000.00', grand_total: on ? '4000.00' : '5000.00', credit_discount: on ? '1000.00' : '0.00' },
        credits: credits(on),
        cashback: { amount: '80.00', rule: '2% cashback', summary: '2% cashback' },
      })
    }
    const api = mockApi({
      get: { ...shopGet, '/addresses/': [address()] },
      post: { '/checkout/preview/': preview, '/orders/': orderDetail({ order_number: 'ODCRED', credit_discount: '1000.00' }) },
    })
    const { user, router } = renderRoute('/checkout')
    const box = await screen.findByTestId('credits-box')
    expect(box).toHaveTextContent('Available credits₹1,500')
    expect(box).toHaveTextContent('Maximum for this order (20%)₹1,000')
    expect(box).toHaveTextContent('Credits applied₹0')
    expect(screen.getByTestId('cashback-note')).toHaveTextContent('You’ll earn ₹80 cashback')

    await user.click(within(box).getByRole('checkbox', { name: /Use my credits/ }))
    await waitFor(() => expect(screen.getByTestId('credits-box')).toHaveTextContent('Credits applied₹1,000'))
    expect(screen.getByTestId('credits-box')).toHaveTextContent('Remaining to pay₹4,000')
    expect(screen.getByTestId('credits-row')).toHaveTextContent('Credits used−₹1,000')
    const previews = api.post.mock.calls.filter(([url]) => url === '/checkout/preview/')
    expect(previews.at(-1)?.[1]).toMatchObject({ use_credits: true })

    await user.click(screen.getAllByRole('button', { name: /· ₹4,000/ })[0]!)
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        '/orders/',
        expect.objectContaining({ use_credits: true, expected_total: '4000.00' }),
        expect.anything(),
      ),
    )
    await waitFor(() => expect(currentUrl(router)).toMatch(/ODCRED/))
  })

  it('hides the credits step when there is nothing to use', async () => {
    signIn()
    mockApi({
      get: { ...shopGet, '/addresses/': [address()] },
      post: { '/checkout/preview/': checkoutPreview({ credits: { ...credits(false), available: '0.00', usable: '0.00' } }) },
    })
    renderRoute('/checkout')
    await screen.findByRole('region', { name: 'Total bill' })
    expect(screen.queryByTestId('credits-box')).not.toBeInTheDocument()
  })
})

describe('order credits and cashback', () => {
  it('shows credits used and the cashback state on the order', async () => {
    signIn()
    mockApi({
      get: {
        ...shopGet,
        '/orders/OD9/': orderDetail({
          order_number: 'OD9',
          credit_discount: '200.00',
          loyalty: {
            credits_used: '200.00',
            credits_restored: '0.00',
            earned: [{ kind: 'cashback', amount: '76.00', status: 'eligible', status_label: 'Eligible', available_at: '2026-10-20T10:00:00+05:30', description: '' }],
          },
        }),
      },
    })
    renderRoute('/account/orders/OD9')
    const section = await screen.findByRole('region', { name: 'Credits & cashback' })
    expect(section).toHaveTextContent('Credits used: ₹200')
    expect(section).toHaveTextContent('Cashback: ₹76 · Eligible (usable from')
  })
})

describe('dashboard loyalty', () => {
  const settings = { credits_enabled: true, max_order_share: '20.00', expiry_days: 90, referral_reward: '0.00', referee_reward: '0.00', welcome_reward: '0.00', updated_at: '2026-10-05T10:00:00+05:30' }

  it('saves settings and gives promotional credit only with a reason', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        '/admin/loyalty/settings/': settings,
        '/admin/loyalty/cashback-rules/': [],
        '/admin/customers/': { count: 1, next: null, previous: null, results: [{ id: 7, full_name: 'Asha Kulkarni', email: 'asha@example.com', phone: null, role: 'customer', is_active: true, email_verified: true, date_joined: '2026-01-01' }] },
      }),
      patch: { '/admin/loyalty/settings/': { ...settings, max_order_share: '15.00' } },
      post: { '/admin/loyalty/promo-credits/': entry({ kind: 'promo', amount: '250.00' }) },
    })
    const { user } = renderRoute('/admin/loyalty')
    const share = await screen.findByLabelText('Credits pay at most (%)')
    await user.clear(share)
    await user.type(share, '120')
    expect(screen.getByText('Between 0 and 100.')).toBeInTheDocument()
    await user.clear(share)
    await user.type(share, '15')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/loyalty/settings/', { max_order_share: '15' }))
    expect(screen.getByText('No cashback rules. Orders earn no cashback.')).toBeInTheDocument()

    const welcome = screen.getByLabelText('Welcome reward on a first delivered order (₹)')
    expect(welcome).toHaveValue('0.00') // off by default
    await user.clear(welcome)
    await user.type(welcome, '-5')
    expect(screen.getByText('Enter 0 or more.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    await user.clear(welcome)
    await user.type(welcome, '100')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/loyalty/settings/', { welcome_reward: '100' }))

    await user.click(screen.getByRole('tab', { name: 'Promotional credit' }))
    await user.type(screen.getByLabelText('Customer'), 'asha')
    await user.click(screen.getByRole('button', { name: 'Find' }))
    await user.click(await screen.findByRole('button', { name: /Asha Kulkarni/ }))
    await user.type(screen.getByLabelText('Amount (₹)'), '250')
    expect(screen.getByRole('button', { name: 'Give credit' })).toBeDisabled() // a reason is required
    await user.type(screen.getByLabelText('Reason'), 'Late delivery')
    await user.click(screen.getByRole('button', { name: 'Give credit' }))
    await user.click(await screen.findByRole('button', { name: 'Give ₹250' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/admin/loyalty/promo-credits/', { user: 7, amount: '250', reason: 'Late delivery' }),
    )
  })

  it('store managers are told the section is not for them', async () => {
    signIn()
    mockApi({ get: staffGet('manager') })
    renderRoute('/admin/loyalty')
    expect(await screen.findByText(/Loyalty/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Credits pay at most (%)')).not.toBeInTheDocument()
    expect(adminSession.sections).toContain('loyalty')
  })
})
