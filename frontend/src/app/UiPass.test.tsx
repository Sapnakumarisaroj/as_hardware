import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { categories, customer, productPage } from '@/test/fixtures'
import { httpError, mockApi, type RequestInfo } from '@/test/mockApi'
import { renderRoute } from '@/test/utils'

/* UI pass (2026-10-07): standalone sign-in pages with validation that mirrors the server, and a
   compact storefront header with exactly one search box. */

const shopGet = { '/categories/': categories, '/products/': productPage([]) }

describe('storefront header', () => {
  it('has exactly one search box, also on the home page', async () => {
    mockApi({ get: shopGet })
    renderRoute('/')
    await screen.findByRole('region', { name: 'Shop by department' })
    expect(screen.getAllByRole('combobox', { name: 'Search products' })).toHaveLength(1)
    expect(screen.getAllByRole('search')).toHaveLength(1)
  })

  it('groups the navigation into compact menus that open and close', async () => {
    mockApi({ get: shopGet })
    const { user } = renderRoute('/')
    const main = await screen.findByRole('navigation', { name: 'Main' })
    for (const name of ['Home', 'Deals', 'New', 'Brands', 'Orders']) {
      expect(within(main).getByRole('link', { name })).toBeInTheDocument()
    }
    const tools = within(main).getByRole('button', { name: 'Tools' })
    expect(tools).toHaveAttribute('aria-expanded', 'false')
    await user.click(tools)
    expect(tools).toHaveAttribute('aria-expanded', 'true')
    const panelId = tools.getAttribute('aria-controls')!
    const panel = document.getElementById(panelId)!
    expect(within(panel).getByRole('link', { name: /^Quantity calculator/ })).toHaveAttribute('href', '/quantity')
    expect(within(panel).getByRole('link', { name: /^Project builder/ })).toHaveAttribute('href', '/projects')
    await user.keyboard('{Escape}')
    expect(tools).toHaveAttribute('aria-expanded', 'false')
    expect(document.getElementById(panelId)).toBeNull()

    await user.click(within(main).getByRole('button', { name: 'Shop' }))
    const shop = await screen.findByRole('navigation', { name: 'Product categories' })
    expect(await within(shop).findByRole('link', { name: /^Electrical/ })).toHaveAttribute('href', '/c/electrical')
    expect(within(shop).getByRole('link', { name: 'All products' })).toHaveAttribute('href', '/products')
  })

  it('shows short category names from the API and full names on hover', async () => {
    mockApi({
      get: {
        ...shopGet,
        '/categories/': [{ ...categories[0], name: 'Plywood, MDF & HDHMR', short_name: 'Plywood & Boards', slug: 'plywood-mdf-hdhmr' }],
      },
    })
    const { user } = renderRoute('/')
    await user.click(await screen.findByRole('button', { name: 'Shop' }))
    const link = await within(await screen.findByRole('navigation', { name: 'Product categories' })).findByRole('link', { name: /^Plywood & Boards/ })
    expect(link).toHaveAttribute('title', 'Plywood, MDF & HDHMR')
  })
})

describe('login', () => {
  it('stands alone: no storefront header, navigation or search', async () => {
    mockApi({ get: shopGet })
    renderRoute('/login')
    expect(await screen.findByRole('heading', { level: 1, name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Search products' })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute('href', '/register?next=%2F')
    expect(screen.getByRole('link', { name: 'Forgot password?' })).toHaveAttribute('href', '/forgot-password')
  })

  it('requires both fields and checks the email before asking the server', async () => {
    const api = mockApi({ get: shopGet })
    const { user } = renderRoute('/login')
    await user.click(await screen.findByRole('button', { name: 'Login' }))
    expect(screen.getByText('Enter your email address.')).toBeInTheDocument()
    expect(screen.getByText('Enter your password.')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    await user.type(screen.getByLabelText('Email'), 'not-an-email')
    expect(screen.getByText(/Enter a valid email address/)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('shows and hides the password', async () => {
    mockApi({ get: shopGet })
    const { user } = renderRoute('/login')
    const password = await screen.findByLabelText('Password')
    expect(password).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('button', { name: 'Show password' }))
    expect(password).toHaveAttribute('type', 'text')
    await user.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(password).toHaveAttribute('type', 'password')
  })

  it('shows the server’s message when the details are wrong', async () => {
    mockApi({ get: shopGet, post: { '/auth/login/': httpError(401, 'Incorrect email or password.', 'invalid_credentials') } })
    const { user } = renderRoute('/login')
    await user.type(await screen.findByLabelText('Email'), 'asha@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong-pass1')
    await user.click(screen.getByRole('button', { name: 'Login' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
  })
})

describe('register', () => {
  it('requires all five fields with the server’s rules', async () => {
    const api = mockApi({ get: shopGet })
    const { user } = renderRoute('/register')
    await user.click(await screen.findByRole('button', { name: 'Create account' }))
    for (const message of ['Enter your full name.', 'Enter your email address.', 'Enter your mobile number.', 'Choose a password.', 'Type the password again.']) {
      expect(screen.getByText(message)).toBeInTheDocument()
    }
    await user.type(screen.getByLabelText('Mobile number'), '12345')
    await user.type(screen.getByLabelText('Password'), 'onlyletters')
    await user.type(screen.getByLabelText('Confirm password'), 'different1')
    expect(screen.getByText('Enter a valid 10-digit Indian mobile number.')).toBeInTheDocument()
    expect(screen.getByText('Use at least one letter and one number.')).toBeInTheDocument()
    expect(screen.getByText('The passwords don’t match.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('sends a normalised phone and shows server field errors inline', async () => {
    let sent: Record<string, unknown> = {}
    mockApi({
      get: shopGet,
      post: {
        '/auth/register/': ({ body }: RequestInfo) => {
          sent = body as Record<string, unknown>
          return httpError(400, 'Invalid input.', 'validation_error')
        },
      },
    })
    const { user } = renderRoute('/register')
    await user.type(await screen.findByLabelText('Full name'), 'Asha Kulkarni')
    await user.type(screen.getByLabelText('Email'), 'asha@example.com')
    await user.type(screen.getByLabelText('Mobile number'), '+91 98765 43210')
    await user.type(screen.getByLabelText('Password'), 'Hammer2026')
    await user.type(screen.getByLabelText('Confirm password'), 'Hammer2026')
    expect(screen.getByText('At least 8 characters')).toHaveTextContent('(done)')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(sent).toMatchObject({ phone: '9876543210', email: 'asha@example.com', full_name: 'Asha Kulkarni' }))
  })

  it('stands alone and links back to login', async () => {
    mockApi({ get: { ...shopGet, '/auth/me/': customer } })
    renderRoute('/register')
    expect(await screen.findByRole('heading', { level: 1, name: 'Create your account' })).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Search products' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Login' })).toHaveAttribute('href', '/login?next=%2F')
  })
})

describe('password reset', () => {
  it('sends the reset email without revealing whether the account exists', async () => {
    const api = mockApi({ get: shopGet, post: { '/auth/password/forgot/': null } })
    const { user } = renderRoute('/forgot-password')
    await user.type(await screen.findByLabelText('Email'), 'someone@example.com')
    await user.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(await screen.findByRole('status')).toHaveTextContent('If an account uses someone@example.com')
    expect(api.post).toHaveBeenCalledWith('/auth/password/forgot/', { email: 'someone@example.com' })
  })

  it('the link from the email opens a page to choose the new password', async () => {
    const api = mockApi({ get: shopGet, post: { '/auth/password/reset/': null } })
    const { user } = renderRoute('/reset-password?uid=MQ&token=abc-123')
    await user.type(await screen.findByLabelText('New password'), 'Chisel2026')
    await user.type(screen.getByLabelText('Confirm new password'), 'Chisel2026')
    await user.click(screen.getByRole('button', { name: 'Save new password' }))
    expect(await screen.findByText('Your password was changed.')).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/auth/password/reset/', {
      uid: 'MQ',
      token: 'abc-123',
      password: 'Chisel2026',
      password_confirm: 'Chisel2026',
    })
  })

  it('explains an incomplete link', async () => {
    mockApi({ get: shopGet })
    renderRoute('/reset-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('This link is incomplete')
  })
})
