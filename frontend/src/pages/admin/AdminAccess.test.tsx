import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { adminUser, analytics, managerUser, page, riderUser, staffGet, storeRow } from '@/test/adminFixtures'
import { customer } from '@/test/fixtures'
import { httpError, mockApi } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const staffCalls = (api: ReturnType<typeof mockApi>) =>
  api.get.mock.calls.map(([url]) => String(url)).filter((url) => !url.startsWith('/auth/'))

describe('dashboard: who gets in', () => {
  it('asks a visitor to sign in and requests nothing from the staff API', async () => {
    const api = mockApi({ get: {} })
    renderRoute('/admin/orders')
    expect(await screen.findByText('Sign in with your staff account to open the dashboard.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Login / Register' })).toHaveAttribute('href', '/login?next=%2Fadmin%2Forders')
    expect(staffCalls(api)).toEqual([])
  })

  it.each([
    ['a customer', customer, 'Go to the shop', '/'],
    ['a delivery partner', riderUser, 'Go to the rider app', '/rider'],
  ])('turns %s away without asking the staff API for anything', async (_who, user, link, href) => {
    signIn()
    const api = mockApi({ get: { '/auth/me/': user } })
    renderRoute('/admin/customers')
    expect(await screen.findByText('For store staff only')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: link })).toHaveAttribute('href', href)
    expect(screen.queryByRole('navigation', { name: 'Admin sections' })).not.toBeInTheDocument()
    expect(staffCalls(api)).toEqual([])
  })

  it('shows the error when the server refuses the session, with a retry', async () => {
    signIn()
    mockApi({ get: { '/auth/me/': adminUser, '/admin/session/': httpError(403, 'Staff access required.', 'permission_denied') } })
    renderRoute('/admin')
    expect(await screen.findByText('Couldn’t open the dashboard')).toBeInTheDocument()
    expect(screen.getByText('Staff access required.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it.each([
    ['an administrator', adminUser, '/admin'],
    ['a store manager', managerUser, '/admin'],
    ['a customer', customer, '/'],
  ])('after login %s lands in the right place', async (_who, user, home) => {
    mockApi({
      get: {
        ...staffGet(user.role === 'admin' ? 'admin' : 'manager'),
        '/categories/': [],
        '/wishlist/': [],
        '/cart/': { items: [] },
        '/search/recent/': [],
      },
      post: { '/auth/login/': { access: 'a', refresh: 'r', user } },
    })
    const { user: actor, router } = renderRoute('/login')
    await actor.type(await screen.findByLabelText('Email'), user.email)
    await actor.type(screen.getByLabelText('Password'), 'S3cure-pass!')
    await actor.click(screen.getByRole('button', { name: 'Login' }))
    await waitFor(() => expect(currentUrl(router)).toBe(home))
  })
})

describe('dashboard: navigation', () => {
  it('an administrator sees every section', async () => {
    signIn()
    mockApi({ get: staffGet() })
    renderRoute('/admin')
    const menu = await screen.findByRole('navigation', { name: 'Admin sections' })
    const links = within(menu).getAllByRole('link').map((link) => [link.textContent, link.getAttribute('href')])
    expect(links).toEqual([
      ['Dashboard', '/admin'],
      ['Analytics', '/admin/analytics'],
      ['Orders', '/admin/orders'],
      ['Returns', '/admin/returns'],
      ['Refunds', '/admin/refunds'],
      ['Customers', '/admin/customers'],
      ['Support', '/admin/support'],
      ['Products', '/admin/products'],
      ['Categories', '/admin/categories'],
      ['Brands', '/admin/brands'],
      ['Product options', '/admin/options'],
      ['Curated lists', '/admin/collections'],
      ['Search', '/admin/search'],
      ['Offers', '/admin/offers'],
      ['Coupons', '/admin/coupons'],
      ['Free delivery', '/admin/free-delivery'],
      ['Cash on delivery', '/admin/payment-settings'],
      ['Loyalty & cashback', '/admin/loyalty'],
      ['Inventory', '/admin/inventory'],
      ['Delivery', '/admin/delivery'],
      ['Stores', '/admin/stores'],
      ['Warehouses', '/admin/warehouses'],
    ])
    expect(within(menu).getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText('Administrator')).toBeInTheDocument()
  })

  it('a store manager sees only their sections and their store', async () => {
    signIn()
    mockApi({ get: staffGet('manager') })
    renderRoute('/admin')
    const menu = await screen.findByRole('navigation', { name: 'Admin sections' })
    const names = within(menu).getAllByRole('link').map((link) => link.textContent)
    expect(names).toEqual(['Dashboard', 'Analytics', 'Orders', 'Returns', 'Refunds', 'Support', 'Inventory', 'Delivery', 'Stores'])
    expect(screen.getByText('Store manager · Kothrud Store')).toBeInTheDocument()
  })

  it.each([
    ['/admin/customers', 'Customer accounts'],
    ['/admin/customers/7', 'Customer accounts'],
    ['/admin/offers', 'Offers'],
    ['/admin/coupons', 'Coupons'],
    ['/admin/search', 'The search index'],
    ['/admin/products/new', 'Products'],
    ['/admin/stores/new', 'Stores and warehouses'],
  ])('a store manager who types %s is told it is for administrators, and no data is requested', async (path, what) => {
    signIn()
    const api = mockApi({ get: staffGet('manager') })
    renderRoute(path)
    expect(await screen.findByText('For administrators only')).toBeInTheDocument()
    expect(screen.getByText(new RegExp(`^${what} can be managed by an administrator`))).toBeInTheDocument()
    const asked = staffCalls(api).filter((url) => !['/admin/session/', '/admin/summary/'].includes(url))
    expect(asked).toEqual([])
  })

  it('moves between sections, with breadcrumbs back to the dashboard', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/stores/': page([storeRow()]), '/admin/analytics/': analytics() }) })
    const { user, router } = renderRoute('/admin')
    const menu = await screen.findByRole('navigation', { name: 'Admin sections' })
    await user.click(within(menu).getByRole('link', { name: 'Stores' }))
    expect(await screen.findByRole('heading', { name: 'Stores', level: 1 })).toBeInTheDocument()
    expect(currentUrl(router)).toBe('/admin/stores')
    expect(await screen.findByRole('link', { name: 'Kothrud Store' })).toHaveAttribute('href', '/admin/stores/1')

    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(crumbs).getByText('Stores')).toHaveAttribute('aria-current', 'page')
    await user.click(within(crumbs).getByRole('link', { name: 'Dashboard' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/admin'))
  })

  it('opens the menu in a drawer on small screens and closes it after choosing', async () => {
    signIn()
    mockApi({ get: staffGet('admin', { '/admin/analytics/': analytics() }) })
    const { user, router } = renderRoute('/admin')
    await user.click(await screen.findByRole('button', { name: 'Menu' }))
    const drawer = screen.getByRole('dialog', { name: 'Menu' })
    await user.click(within(drawer).getByRole('link', { name: 'Analytics' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/admin/analytics'))
    expect(screen.queryByRole('dialog', { name: 'Menu' })).not.toBeInTheDocument()
  })

  it('lists what is waiting under “To do” and links to it', async () => {
    signIn()
    mockApi({ get: staffGet() })
    const { user } = renderRoute('/admin/nowhere')
    const button = await screen.findByRole('button', { name: /To do/ })
    await waitFor(() => expect(button).toHaveAccessibleName('To do: 8 waiting'))
    await user.click(button)
    const list = document.getElementById('admin-notifications')!
    expect(within(list).getByRole('link', { name: /Packed shipments without a rider/ })).toHaveAttribute(
      'href',
      '/admin/delivery?tab=shipments',
    )
    expect(within(list).getByRole('link', { name: /Refunds that failed/ })).toHaveAttribute('href', '/admin/refunds?status=failed')
  })

  it('finds an order from the top bar', async () => {
    signIn()
    const api = mockApi({ get: staffGet('admin', { '/admin/orders/': page([]) }) })
    const { user, router } = renderRoute('/admin')
    await user.type(await screen.findByLabelText('Find an order'), '9876543210{Enter}')
    await waitFor(() => expect(currentUrl(router)).toBe('/admin/orders?q=9876543210'))
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/admin/orders/', { params: { page_size: '20', page: '1', q: '9876543210' } }))
  })

  it('shows “not found” for an unknown dashboard page', async () => {
    signIn()
    mockApi({ get: staffGet() })
    renderRoute('/admin/nowhere')
    expect(await screen.findByRole('navigation', { name: 'Admin sections' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: /not found|can’t find|couldn’t find/i })).toBeInTheDocument()
  })
})
