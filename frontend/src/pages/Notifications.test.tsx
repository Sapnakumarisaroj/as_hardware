import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ChannelStatus, EventSpec, LogRow, Notification, Preferences } from '@/features/notifications/api'
import { adminSession, staffGet } from '@/test/adminFixtures'
import { checkoutPreview, customer } from '@/test/fixtures'
import { mockApi, paramsSent, type RequestInfo } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

/* Phase 23: the bell and inbox, each person's message choices, and the administrator's
   notification centre (channels, events and words, delivery log). */

function note(overrides: Partial<Notification> = {}): Notification {
  return {
    id: 1,
    event: 'order.confirmed',
    category: 'orders',
    title: 'Order OD1 confirmed',
    body: 'Thank you! Your order of ₹600.00 (cash on delivery) is confirmed.',
    link: '/account/orders/OD1',
    is_read: false,
    read_at: null,
    created_at: '2026-10-06T10:00:00+05:30',
    ...overrides,
  }
}

function prefs(overrides: Partial<Preferences> = {}): Preferences {
  return {
    email: true,
    sms: false,
    whatsapp: false,
    muted_categories: [],
    has_email: true,
    phone: '98•••••678',
    channels: {
      in_app: { available: true, always_on: true },
      email: { available: true },
      whatsapp: { available: true, needs_phone: false },
      sms: { available: false, needs_phone: false },
    },
    categories: [
      { key: 'orders', label: 'Order updates' },
      { key: 'delivery', label: 'Delivery progress (rider, ETA, picked up)' },
    ],
    ...overrides,
  }
}

const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results })
const shopGet = { '/categories/': [], '/auth/me/': customer, '/wishlist/': [], '/search/recent/': [], '/cart/': checkoutPreview().cart }

describe('inbox', () => {
  it('shows the unread count on the bell, lists messages and filters them', async () => {
    signIn()
    const api = mockApi({
      get: {
        ...shopGet,
        '/notifications/summary/': { unread: 2 },
        '/notifications/preferences/': prefs(),
        '/notifications/': ({ params }: RequestInfo) =>
          page(params.unread ? [note()] : [note(), note({ id: 2, title: 'Refund of ₹600 processed', is_read: true, link: '' })]),
      },
    })
    renderRoute('/notifications')
    expect(await screen.findByRole('link', { name: 'Notifications, 2 unread' })).toHaveAttribute('href', '/notifications')
    const rows = await screen.findAllByTestId('notification')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('Order OD1 confirmed (unread)')
    expect(within(rows[0]!).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/account/orders/OD1')
    expect(within(rows[1]!).queryByRole('link', { name: 'Open' })).not.toBeInTheDocument()

    screen.getByRole('button', { name: 'Unread' }).click()
    await waitFor(() => expect(paramsSent(api.get, '/notifications/').at(-1)).toMatchObject({ unread: '1', page: '1' }))
    screen.getByRole('button', { name: 'Order updates' }).click()
    await waitFor(() => expect(paramsSent(api.get, '/notifications/').at(-1)).toMatchObject({ category: 'orders' }))
  })

  it('marks one or all messages read', async () => {
    signIn()
    const api = mockApi({
      get: { ...shopGet, '/notifications/summary/': { unread: 1 }, '/notifications/preferences/': prefs(), '/notifications/': page([note()]) },
      post: { '/notifications/1/read/': { unread: 0 }, '/notifications/read-all/': { marked: 1, unread: 0 } },
    })
    const { user } = renderRoute('/notifications')
    await user.click(await screen.findByRole('button', { name: 'Mark as read: Order OD1 confirmed' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/1/read/'))
    await user.click(screen.getByRole('button', { name: 'Mark all as read' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/read-all/', {}))
    expect(await screen.findByText('All messages marked as read.')).toBeInTheDocument()
  })

  it('asks visitors to sign in', async () => {
    mockApi({ get: { '/categories/': [], '/search/recent/': [] } })
    renderRoute('/notifications')
    expect(await screen.findByText('Sign in to see your messages.')).toBeInTheDocument()
  })
})

describe('message settings', () => {
  it('turns WhatsApp on and a topic off', async () => {
    signIn()
    const api = mockApi({
      get: { ...shopGet, '/notifications/summary/': { unread: 0 }, '/notifications/preferences/': prefs(), '/notifications/': page([]) },
      patch: { '/notifications/preferences/': ({ body }: RequestInfo) => prefs(body as Partial<Preferences>) },
    })
    const { user } = renderRoute('/notifications')
    expect(await screen.findByText('No messages yet')).toBeInTheDocument()
    const whatsapp = await screen.findByRole('checkbox', { name: /WhatsApp/ })
    expect(whatsapp).not.toBeChecked()
    expect(screen.getByText(/Sent to 98•••••678/)).toBeInTheDocument()
    await user.click(whatsapp)
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/notifications/preferences/', { whatsapp: true }))
    await user.click(screen.getByRole('checkbox', { name: /Delivery progress/ }))
    await waitFor(() => expect(api.patch).toHaveBeenLastCalledWith('/notifications/preferences/', { muted_categories: ['delivery'] }))
    expect(screen.queryByRole('checkbox', { name: /SMS/ })).not.toBeInTheDocument() // no SMS gateway
  })

  it('needs a mobile number for WhatsApp', async () => {
    signIn()
    mockApi({
      get: {
        ...shopGet,
        '/notifications/summary/': { unread: 0 },
        '/notifications/': page([]),
        '/notifications/preferences/': prefs({ phone: '', channels: { ...prefs().channels, whatsapp: { available: true, needs_phone: true } } }),
      },
    })
    renderRoute('/notifications')
    const whatsapp = await screen.findByRole('checkbox', { name: /WhatsApp/ })
    expect(whatsapp).toBeDisabled()
    expect(screen.getByText(/Add a mobile number to your account first/)).toBeInTheDocument()
  })
})

// --- Administration --------------------------------------------------------------------------------

const session = { ...adminSession, sections: [...adminSession.sections, 'notifications' as const] }

function channel(overrides: Partial<ChannelStatus> = {}): ChannelStatus {
  return {
    channel: 'whatsapp',
    enabled: true,
    provider: 'mock',
    configured: true,
    mock: true,
    live: false,
    last_24h: { pending: 0, sent: 12, failed: 2, skipped: 1 },
    last_sent_at: '2026-10-06T10:00:00+05:30',
    last_error: 'Mock: this number can’t receive messages.',
    ...overrides,
  }
}

const delivered: EventSpec = {
  key: 'order.delivered',
  label: 'Delivered',
  category: 'orders',
  category_label: 'Order updates',
  audience: 'customer',
  critical: false,
  variables: ['customer_name', 'shop_name', 'link', 'order_number'],
  secret_variables: [],
  channels: [
    { channel: 'in_app', enabled: true, default_enabled: true, default_title: 'Order {order_number} delivered', default_body: 'Your order has been delivered.', default_provider_template: '', templates: [] },
    { channel: 'whatsapp', enabled: false, default_enabled: true, default_title: 'Order {order_number} delivered', default_body: 'Hi {customer_name}, {order_number} delivered.', default_provider_template: 'order_delivered', templates: [] },
  ],
}

function logRow(overrides: Partial<LogRow> = {}): LogRow {
  return {
    id: 5,
    created_at: '2026-10-06T10:00:00+05:30',
    user: 7,
    user_email: 'asha@example.com',
    user_name: 'Asha Kulkarni',
    channel: 'whatsapp',
    event: 'order.delivered',
    language: 'en',
    title: 'Order OD1 delivered',
    body: 'Hi Asha, OD1 delivered.',
    status: 'failed',
    provider: 'mock',
    provider_status: '',
    template_name: 'order_delivered',
    recipient: '+91 98•••••000',
    attempts: 1,
    error: 'Mock: this number can’t receive messages.',
    sent_at: null,
    delivered_at: null,
    read_at: null,
    can_retry: true,
    ...overrides,
  }
}

function adminGet(extra: Record<string, unknown> = {}) {
  return staffGet('admin', {
    '/admin/session/': session,
    '/notifications/summary/': { unread: 0 },
    '/admin/notifications/channels/': { results: [channel({ channel: 'in_app', provider: 'in_app', mock: false, live: true, last_error: '' }), channel()] },
    '/admin/notifications/events/': { results: [delivered], languages: ['en', 'hi', 'hi-latn'] },
    '/admin/notifications/log/': page([logRow()]),
    ...extra,
  })
}

describe('notification centre', () => {
  it('shows each channel with its provider and turns WhatsApp off after asking', async () => {
    signIn()
    const api = mockApi({ get: adminGet(), patch: { '/admin/notifications/channels/whatsapp/': { channel: 'whatsapp', enabled: false } } })
    const { user } = renderRoute('/admin/notifications')
    expect(await screen.findByText('Test mode: nothing really sent')).toBeInTheDocument()
    expect(screen.getByText('Always on')).toBeInTheDocument()
    expect(screen.getByText(/Last failure: Mock/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Turn off WhatsApp' }))
    const dialog = await screen.findByRole('dialog', { name: 'Turn WhatsApp off?' })
    await user.click(within(dialog).getByRole('button', { name: 'Turn off' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/notifications/channels/whatsapp/', { enabled: false }))
  })

  it('switches an event on for a channel, previews and saves its own words', async () => {
    signIn()
    const api = mockApi({
      get: adminGet(),
      patch: { '/admin/notifications/events/order.delivered/whatsapp/': { enabled: true } },
      post: {
        '/admin/notifications/preview/': { ok: true, problems: {}, title: '', body: 'Namaste Asha, OD2610060001 aa gaya!', parameters: ['Asha'] },
        '/admin/notifications/templates/': { id: 3 },
      },
    })
    const { user } = renderRoute('/admin/notifications?tab=messages')
    const event = await screen.findByTestId('event-order.delivered')
    await user.click(within(event).getByRole('checkbox', { name: 'WhatsApp' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/notifications/events/order.delivered/whatsapp/', { enabled: true }))

    await user.click(within(event).getByRole('button', { name: 'Words for Delivered by WhatsApp' }))
    const dialog = await screen.findByRole('dialog')
    const message = within(dialog).getByLabelText(/Message/)
    expect(message).toHaveValue('Hi {customer_name}, {order_number} delivered.')
    expect(within(dialog).getByLabelText('Approved WhatsApp template name')).toHaveValue('order_delivered')
    await user.clear(message)
    await user.type(message, 'Namaste {{customer_name}, {{order_number} aa gaya!')
    await user.selectOptions(within(dialog).getByLabelText('Language'), 'hi-latn')
    await user.clear(within(dialog).getByLabelText(/Message/))
    await user.type(within(dialog).getByLabelText(/Message/), 'Namaste {{customer_name}, {{order_number} aa gaya!')
    await user.click(within(dialog).getByRole('button', { name: 'Preview' }))
    expect(await within(dialog).findByTestId('preview')).toHaveTextContent('Namaste Asha, OD2610060001 aa gaya!')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/admin/notifications/templates/', {
        id: undefined,
        event: 'order.delivered',
        channel: 'whatsapp',
        language: 'hi-latn',
        title: 'Order {order_number} delivered',
        body: 'Namaste {customer_name}, {order_number} aa gaya!',
        provider_template: 'order_delivered',
      }),
    )
  })

  it('lists the delivery log with masked numbers and sends a failed message again', async () => {
    signIn()
    const api = mockApi({ get: adminGet(), post: { '/admin/notifications/log/5/retry/': logRow({ status: 'pending', can_retry: false }) } })
    const { user } = renderRoute('/admin/notifications?tab=log&status=failed')
    expect(await screen.findByText('+91 98•••••000')).toBeInTheDocument()
    expect(paramsSent(api.get, '/admin/notifications/log/').at(-1)).toMatchObject({ status: 'failed' })
    await user.click(screen.getByRole('button', { name: 'Send again' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/notifications/log/5/retry/'))
  })

  it('is for administrators only', async () => {
    signIn()
    const api = mockApi({ get: staffGet('manager', { '/notifications/summary/': { unread: 0 } }) })
    renderRoute('/admin/notifications')
    expect(await screen.findByText('For administrators only')).toBeInTheDocument()
    expect(api.get.mock.calls.map(([url]) => url)).not.toContain('/admin/notifications/channels/')
  })
})
