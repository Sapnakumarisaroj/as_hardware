import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { approvedCategories, categories, customer, productPage } from '@/test/fixtures'
import { httpError, mockApi, paramsSent, type RequestInfo } from '@/test/mockApi'
import { renderRoute } from '@/test/utils'

/* UI pass (2026-10-07): standalone sign-in pages with validation that mirrors the server, and a
   compact storefront header with exactly one search box. */

const shopGet = { '/categories/': categories, '/products/': productPage([]) }

describe('storefront header', () => {
  const groupNames = ['Wood & Adhesives', 'Furniture Hardware', 'Door & Glass Hardware', 'Tools & Safety']
  const approvedGet = { ...shopGet, '/categories/': approvedCategories }

  it('has exactly one search box, also on the home page', async () => {
    mockApi({ get: approvedGet })
    renderRoute('/')
    await screen.findByRole('region', { name: 'Shop by category' })
    expect(screen.getAllByRole('combobox', { name: 'Search products' })).toHaveLength(1)
    expect(screen.getAllByRole('search')).toHaveLength(1)
  })

  it('main navigation is Home and the four product groups only', async () => {
    mockApi({ get: approvedGet })
    renderRoute('/')
    const main = await screen.findByRole('navigation', { name: 'Main' })
    await within(main).findByRole('button', { name: 'Tools & Safety' })
    const items = [...main.querySelectorAll(':scope > ul > li')].map((li) => li.querySelector('a, button')?.textContent)
    expect(items).toEqual(['Home', ...groupNames])
    for (const gone of ['Deals', 'New', 'Brands', 'Orders', 'AI', 'Tools', 'Shop', 'Electrical']) {
      expect(within(main).queryByRole('link', { name: gone })).not.toBeInTheDocument()
      expect(within(main).queryByRole('button', { name: gone })).not.toBeInTheDocument()
    }
  })

  it('shows the four groups and their departments even when the category API is unreachable', async () => {
    mockApi({ get: { ...shopGet, '/categories/': httpError(503, 'Cannot reach the server.') } })
    const { user } = renderRoute('/')
    const main = screen.getByRole('navigation', { name: 'Main' })
    const items = [...main.querySelectorAll(':scope > ul > li')].map((li) => li.querySelector('a, button')?.textContent)
    expect(items).toEqual(['Home', ...groupNames])
    const wood = within(main).getByRole('button', { name: 'Wood & Adhesives' })
    await user.click(wood)
    const panel = document.getElementById(wood.getAttribute('aria-controls')!)!
    expect(within(panel).getByRole('link', { name: 'Plywood, MDF & HDHMR' })).toHaveAttribute('href', '/c/plywood-mdf-hdhmr')
    expect(within(panel).getByRole('link', { name: 'Fevicol' })).toHaveAttribute('href', '/c/fevicol')
  })

  it('a group opens a dropdown of its departments, by their exact names, with their own subcategories', async () => {
    mockApi({ get: approvedGet })
    const { user } = renderRoute('/')
    const main = await screen.findByRole('navigation', { name: 'Main' })
    const furniture = await within(main).findByRole('button', { name: 'Furniture Hardware' })
    expect(furniture).toHaveAttribute('aria-expanded', 'false')
    await user.click(furniture)
    expect(furniture).toHaveAttribute('aria-expanded', 'true')
    const panelId = furniture.getAttribute('aria-controls')!
    const panel = document.getElementById(panelId)!
    expect(within(panel).getByRole('link', { name: /^Hinges, Channels & Handles\s+7 products/ })).toHaveAttribute('href', '/c/hinges-channels-handles')
    expect(within(panel).getByRole('link', { name: 'Hinges' })).toHaveAttribute('href', '/c/hinges')
    expect(within(panel).getByRole('link', { name: 'Drawer Channels' })).toHaveAttribute('href', '/c/drawer-channels')
    expect(within(panel).getByRole('link', { name: /View all/ })).toHaveAttribute('href', '/shop/furniture-hardware')
    expect(panel.querySelector('img')).toHaveAttribute('src', '/media/products/hinge.jpg')
    // Departments the shop has no products in are not offered; nothing is made up.
    expect(within(panel).queryByRole('link', { name: /Kitchen|Wardrobe|Electrical/ })).not.toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(furniture).toHaveAttribute('aria-expanded', 'false')
    expect(document.getElementById(panelId)).toBeNull()
  })

  it('Tools & Safety lists its three departments; empty subcategories are hidden', async () => {
    mockApi({ get: approvedGet })
    const { user } = renderRoute('/')
    const main = await screen.findByRole('navigation', { name: 'Main' })
    const tools = await within(main).findByRole('button', { name: 'Tools & Safety' })
    await user.click(tools)
    const panel = document.getElementById(tools.getAttribute('aria-controls')!)!
    const departments = [...panel.querySelectorAll(':scope ul > li > a .font-bold')].map((el) => el.textContent)
    expect(departments).toEqual(['Power Tools & Accessories', 'General Hardware & Tools', 'Safety Tools & Workwear'])
    expect(within(panel).getByRole('link', { name: 'Drill Bits' })).toHaveAttribute('href', '/c/drill-bits')
    expect(within(panel).getByRole('link', { name: 'Gloves' })).toHaveAttribute('href', '/c/gloves')
    expect(within(panel).queryByRole('link', { name: 'Workwear' })).not.toBeInTheDocument()
  })

  it('the menu drawer lists the four groups with their subcategories', async () => {
    mockApi({ get: approvedGet })
    const { user } = renderRoute('/')
    await within(await screen.findByRole('navigation', { name: 'Main' })).findByRole('button', { name: 'Tools & Safety' })
    await user.click(screen.getByRole('button', { name: 'Open menu' }))
    const drawer = await screen.findByRole('navigation', { name: 'Mobile menu' })
    for (const name of groupNames) expect(within(drawer).getByText(name)).toBeInTheDocument()
    await user.click(within(drawer).getByText('Wood & Adhesives'))
    expect(within(drawer).getByRole('link', { name: 'Plywood, MDF & HDHMR' })).toHaveAttribute('href', '/c/plywood-mdf-hdhmr')
    expect(within(drawer).getByRole('link', { name: 'Fevicol' })).toHaveAttribute('href', '/c/fevicol')
    expect(within(drawer).getByRole('link', { name: 'View all Wood & Adhesives' })).toHaveAttribute('href', '/shop/wood-adhesives')
    expect(within(drawer).getByRole('link', { name: 'AI assistant' })).toHaveAttribute('href', '/ai-assistant')
  })
})

describe('header bands and delivery', () => {
  const fastCheck = {
    serviceable: true, postal_code: '411038', location_precision: 'pin', fast_delivery_available: true,
    label: 'Delivery in 18 minutes', fast_unavailable_reason: '', message: '⚡ Fast delivery available · Delivery in 18 minutes', stores: [],
  }
  const promise = { '/delivery/promise/': { fast_delivery_max_minutes: 60 } }

  it('has the opening-hours strip, then one row with logo, badge, Deliver to, search and icons', async () => {
    mockApi({ get: { ...shopGet, ...promise, '/categories/': approvedCategories } })
    renderRoute('/')
    expect(within(screen.getByRole('banner').previousElementSibling as HTMLElement).getByText('Open 8 am to 8 pm all days')).toBeInTheDocument()
    const banner = screen.getByRole('banner')
    const badge = await within(banner).findByTestId('fast-badge')
    expect(badge).toHaveTextContent('60 Mins')
    expect(badge).toHaveAttribute('data-state', 'neutral') // no PIN yet: a service indicator, not a promise
    expect(within(banner).getAllByRole('button', { name: /Deliver to/ })).toHaveLength(1)
    expect(within(banner).getAllByRole('combobox', { name: 'Search products' })).toHaveLength(1)
    expect(within(banner).getByRole('combobox', { name: 'Search products' })).toHaveAttribute('placeholder', 'Search plywood, hinges, locks, drills…')
    for (const name of ['Shop by voice', 'Search by photo']) {
      expect(within(banner).getByRole('link', { name })).toBeInTheDocument()
    }
    expect(within(banner).getByRole('link', { name: 'Wishlist' })).toHaveAttribute('href', '/wishlist')
    expect(within(banner).getByRole('link', { name: 'Cart' })).toHaveAttribute('href', '/cart')
    expect(within(banner).getByRole('link', { name: /Login \/ Register/ })).toHaveAttribute('href', '/login')
  })

  it('the badge follows the delivery engine for the chosen PIN', async () => {
    window.localStorage.setItem('boltrun.delivery-pincode', '411038')
    mockApi({ get: { ...shopGet, ...promise, '/delivery/check/': fastCheck } })
    renderRoute('/')
    await waitFor(() => expect(screen.getByTestId('fast-badge')).toHaveAttribute('data-state', 'available'))
    expect(screen.getByTestId('fast-badge')).toHaveTextContent('Delivery in 18 minutes')
  })

  it('dims the badge where fast delivery is not available right now', async () => {
    window.localStorage.setItem('boltrun.delivery-pincode', '411038')
    mockApi({
      get: {
        ...shopGet,
        ...promise,
        '/delivery/check/': { ...fastCheck, fast_delivery_available: false, label: 'Delivery tomorrow', fast_unavailable_reason: 'no rider free' },
      },
    })
    renderRoute('/')
    await waitFor(() => expect(screen.getByTestId('fast-badge')).toHaveAttribute('data-state', 'unavailable'))
    expect(screen.getByTestId('fast-badge')).toHaveTextContent('isn’t available to 411038 right now (no rider free)')
  })

  it('a failed delivery check stays quiet: no error bar, neutral badge', async () => {
    window.localStorage.setItem('boltrun.delivery-pincode', '411038')
    mockApi({ get: { ...shopGet, ...promise, '/delivery/check/': httpError(503, 'Unavailable.') } })
    renderRoute('/')
    expect(await screen.findByTestId('fast-badge')).toHaveAttribute('data-state', 'neutral')
    await waitFor(() => expect(screen.getByRole('button', { name: /Deliver to\s*411038/ })).toBeInTheDocument())
    expect(screen.queryByText(/Couldn’t check delivery/)).not.toBeInTheDocument()
  })

  it('no badge when the shop’s promise cannot be loaded', async () => {
    mockApi({ get: shopGet })
    renderRoute('/')
    await screen.findByRole('navigation', { name: 'Main' })
    await waitFor(() => expect(screen.queryByTestId('fast-badge')).not.toBeInTheDocument())
  })
})

describe('home page categories', () => {
  it('shows the four groups as cards with real product photos', async () => {
    mockApi({ get: { ...shopGet, '/categories/': approvedCategories } })
    renderRoute('/')
    const section = await screen.findByRole('region', { name: 'Shop by category' })
    const cards = within(section).getAllByRole('article')
    expect(cards.map((card) => within(card).getByRole('heading').textContent)).toEqual([
      'Wood & Adhesives',
      'Furniture Hardware',
      'Door & Glass Hardware',
      'Tools & Safety',
    ])
    const wood = cards[0]!
    expect(within(wood).getByRole('link', { name: 'Wood & Adhesives' })).toHaveAttribute('href', '/shop/wood-adhesives')
    expect(within(wood).getByRole('link', { name: 'Plywood, MDF & HDHMR' })).toHaveAttribute('href', '/c/plywood-mdf-hdhmr')
    expect(within(wood).getByRole('link', { name: 'Fevicol' })).toHaveAttribute('href', '/c/fevicol')
    const photos = [...wood.querySelectorAll('img')].map((img) => img.getAttribute('src'))
    expect(photos).toEqual(['/media/products/plywood.jpg', '/media/products/fevicol.jpg', '/media/products/mdf.jpg'])
  })
})

describe('group page', () => {
  it('shows the group’s departments with their own subcategories and a rail per department', async () => {
    const api = mockApi({ get: { ...shopGet, '/categories/': approvedCategories } })
    renderRoute('/shop/tools-safety')
    expect(await screen.findByRole('heading', { level: 1, name: 'Tools & Safety' })).toBeInTheDocument()
    const tiles = screen.getByRole('navigation', { name: 'Shop Tools & Safety' })
    expect(within(tiles).getByRole('link', { name: 'Power Tools & Accessories' })).toHaveAttribute('href', '/c/power-tools')
    const hardware = within(tiles).getByRole('list', { name: 'In General Hardware & Tools' })
    expect(within(hardware).getByRole('link', { name: 'Screwdrivers' })).toHaveAttribute('href', '/c/screwdrivers')
    expect(within(hardware).getByRole('link', { name: 'Hammers' })).toHaveAttribute('href', '/c/hammers')
    await waitFor(() =>
      expect(paramsSent(api.get, '/products/')).toContainEqual(expect.objectContaining({ category: 'general-hardware' })),
    )
  })

  it('an unknown group is a 404', async () => {
    mockApi({ get: { ...shopGet, '/categories/': approvedCategories } })
    renderRoute('/shop/electrical')
    expect(await screen.findByRole('heading', { name: /not found/i })).toBeInTheDocument()
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
