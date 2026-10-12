import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/lib/api/errors'
import { customer } from '@/test/fixtures'
import { mockApi, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute } from '@/test/utils'

// SMS-code sign-in is off until a real SMS gateway is live; these tests switch it on.
vi.mock('@/lib/env', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/env')>()
  return { env: { ...actual.env, otpLoginEnabled: true } }
})

const sent = { phone: '+91 ******1234', expires_in: 300, resend_in: 30, length: 6, sms_sent: true }
const shopGet = { '/categories/': [], '/search/recent/': [] }
const fail = (status: number, code: string, message: string, details: Record<string, unknown> = {}) =>
  new ApiError({ status, code, message, details })
const signedIn = { access: 'a', refresh: 'r', user: { ...customer, phone: '9876501234' } }

describe('sign in with mobile number and OTP', () => {
  it('sends a code to the customer’s own number, verifies it and signs in', async () => {
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': signedIn.user },
      post: { '/auth/otp/request/': sent, '/auth/otp/verify/': signedIn },
    })
    const { user, router } = renderRoute('/login?method=otp&next=%2Faccount')
    expect(await screen.findByRole('combobox', { name: 'Country code' })).toHaveValue('+91')
    await user.type(screen.getByLabelText('Mobile number'), '+91 98765 01234')
    await user.click(screen.getByRole('button', { name: 'Send OTP' }))
    expect(api.post).toHaveBeenCalledWith('/auth/otp/request/', { phone: '9876501234', country_code: '+91' })
    expect(await screen.findByText('+91 ******1234')).toBeInTheDocument()
    expect(screen.getByText(/Code sent to/)).toBeInTheDocument()
    expect(screen.getByText(/Resend OTP in \d+s/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resend OTP' })).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('One-time code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Verify and continue' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/account'))
    expect(api.post).toHaveBeenCalledWith('/auth/otp/verify/', {
      phone: '9876501234',
      code: '123456',
      country_code: '+91',
      full_name: '',
      email: '',
    })
  })

  it('checks the number before asking the server', async () => {
    const api = mockApi({ get: shopGet })
    const { user } = renderRoute('/login?method=otp')
    await user.type(await screen.findByLabelText('Mobile number'), '12345')
    await user.click(screen.getByRole('button', { name: 'Send OTP' }))
    expect(await screen.findByText('Enter a valid 10-digit Indian mobile number.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('a new number is asked for a name and keeps the same code', async () => {
    let calls = 0
    mockApi({
      get: { ...shopGet, '/auth/me/': signedIn.user },
      post: {
        '/auth/otp/request/': sent,
        '/auth/otp/verify/': ({ body }: RequestInfo) => {
          calls += 1
          if (!(body as { full_name: string }).full_name) {
            throw fail(400, 'name_required', 'Welcome! Tell us your name to create your account.')
          }
          return signedIn
        },
      },
    })
    const { user } = renderRoute('/login?method=otp')
    await user.type(await screen.findByLabelText('Mobile number'), '9876501234')
    await user.click(screen.getByRole('button', { name: 'Send OTP' }))
    await user.type(await screen.findByLabelText('One-time code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Verify and continue' }))
    expect(await screen.findByText('Welcome! Enter your name to create your account.')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Full name'), 'Ravi Kumar')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(calls).toBe(2))
  })

  it('shows the server’s message for a wrong code', async () => {
    mockApi({
      get: shopGet,
      post: {
        '/auth/otp/request/': sent,
        '/auth/otp/verify/': () => {
          throw fail(400, 'otp_invalid', "That code isn't right. 4 attempts left.", { attempts_left: 4 })
        },
      },
    })
    const { user } = renderRoute('/login?method=otp')
    await user.type(await screen.findByLabelText('Mobile number'), '9876501234')
    await user.click(screen.getByRole('button', { name: 'Send OTP' }))
    await user.type(await screen.findByLabelText('One-time code'), '000000')
    await user.click(screen.getByRole('button', { name: 'Verify and continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("That code isn't right. 4 attempts left.")
  })

  it('offers Resend OTP once the countdown is over, and reports a cooldown', async () => {
    let requests = 0
    const api = mockApi({
      get: shopGet,
      post: {
        '/auth/otp/request/': () => {
          requests += 1
          if (requests === 1) return { ...sent, resend_in: 0 }
          throw fail(429, 'otp_cooldown', 'Please wait 25 seconds before asking for a new code.', { retry_after: 25 })
        },
      },
    })
    const { user } = renderRoute('/login?method=otp')
    await user.type(await screen.findByLabelText('Mobile number'), '9876501234')
    await user.click(screen.getByRole('button', { name: 'Send OTP' }))
    await user.click(await screen.findByRole('button', { name: 'Resend OTP' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('alert')).toHaveTextContent('Please wait 25 seconds')
    expect(screen.getByText(/Resend OTP in \d+s/)).toBeInTheDocument()
  })

  it('explains when SMS sign-in is unavailable and offers email sign-in', async () => {
    mockApi({
      get: shopGet,
      post: {
        '/auth/otp/request/': () => {
          throw fail(503, 'sms_unavailable', "Sign-in by SMS code isn't available right now. Please sign in with your email instead.")
        },
      },
    })
    const { user } = renderRoute('/login?method=otp')
    await user.type(await screen.findByLabelText('Mobile number'), '9876501234')
    await user.click(screen.getByRole('button', { name: 'Send OTP' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("isn't available right now")
    expect(screen.getByRole('link', { name: 'Sign in with email and password' })).toBeInTheDocument()
  })

  it('never says “Code sent” when the development mock sent no SMS', async () => {
    mockApi({ get: shopGet, post: { '/auth/otp/request/': { ...sent, sms_sent: false } } })
    const { user } = renderRoute('/login?method=otp')
    await user.type(await screen.findByLabelText('Mobile number'), '9876501234')
    await user.click(screen.getByRole('button', { name: 'Send OTP' }))
    expect(await screen.findByText(/Development only: no SMS was sent/)).toBeInTheDocument()
    expect(screen.queryByText(/Code sent/)).not.toBeInTheDocument()
  })

  it('the mobile number + password form stays the default', async () => {
    mockApi({ get: shopGet })
    renderRoute('/login')
    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign in with an SMS code instead' })).toHaveAttribute('href', '/login?method=otp&next=%2F')
  })

})
