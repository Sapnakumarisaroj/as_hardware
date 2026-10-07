import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AssistantAnswer, Report } from '@/features/analytics/api'
import { adminSession, managerSession, staffGet } from '@/test/adminFixtures'
import { mockApi, paramsSent, type RequestInfo } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

/* Phase 24: the reports page (periods, store filter, KPIs, tables, CSV) and the business assistant. */

const session = { ...adminSession, sections: [...adminSession.sections, 'reports' as const, 'assistant' as const] }
const list = {
  results: [
    { key: 'sales', title: 'Sales and revenue', description: 'Revenue and more.' },
    { key: 'products', title: 'Products', description: 'Best and slowest sellers.' },
  ],
}

function report(key = 'sales', overrides: Partial<Report> = {}): Report {
  return {
    key,
    title: key === 'sales' ? 'Sales and revenue' : 'Products',
    description: 'Revenue and more.',
    period: { from: '2026-09-08', to: '2026-10-07', days: 30, group_by: 'day' },
    kpis: [
      { key: 'revenue', label: 'Revenue', value: '125000.00', format: 'money', hint: 'Paid orders placed in the period' },
      { key: 'paid_orders', label: 'Paid orders', value: 42, format: 'count' },
      { key: 'gross_margin', label: 'Gross margin', value: null, format: 'text' },
    ],
    series: null,
    tables: [
      {
        key: 'top',
        title: 'Products by sales',
        columns: [
          { key: 'name', label: 'Product', format: 'text' },
          { key: 'sales', label: 'Sales', format: 'money' },
        ],
        rows: [
          { name: 'BWP Marine Plywood', sales: '41900.00' },
          { name: 'Soft-Close Hinge', sales: '3290.00' },
        ],
        chart: { type: 'bar', label: 'name', value: 'sales' },
      },
    ],
    notes: ['Profit needs purchase costs.'],
    ...overrides,
  }
}

describe('reports page', () => {
  it('shows the KPIs and tables of the chosen report for the chosen period', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        '/admin/session/': session,
        '/notifications/summary/': { unread: 0 },
        '/admin/reports/': list,
        '/admin/reports/sales/': report('sales'),
        '/admin/reports/products/': report('products'),
      }),
    })
    const { user } = renderRoute('/admin/reports')
    expect(await screen.findByText('₹1,25,000.00')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('Profit needs purchase costs.')).toBeInTheDocument()
    const chart = screen.getByRole('list', { name: 'Products by sales chart' })
    expect(within(chart).getByText('BWP Marine Plywood')).toBeInTheDocument()
    expect(paramsSent(api.get, '/admin/reports/sales/').at(-1)).toMatchObject({ from: expect.any(String), to: expect.any(String) })

    await user.selectOptions(screen.getByLabelText('Period'), 'today')
    await waitFor(() => {
      const sent = paramsSent(api.get, '/admin/reports/sales/').at(-1)!
      expect(sent.from).toBe(sent.to)
    })
    await user.click(screen.getByRole('tab', { name: 'Products' }))
    await waitFor(() => expect(paramsSent(api.get, '/admin/reports/products/').length).toBeGreaterThan(0))
  })

  it('opens a report link from the assistant with its dates and downloads CSV', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        '/admin/session/': session,
        '/notifications/summary/': { unread: 0 },
        '/admin/reports/': list,
        '/admin/reports/sales/': report('sales'),
        '/admin/reports/sales/export/': new Blob(['a,b']),
      }),
    })
    const { user } = renderRoute('/admin/reports?report=sales&from=2026-09-01&to=2026-09-30')
    await screen.findByText('₹1,25,000.00')
    expect(paramsSent(api.get, '/admin/reports/sales/').at(-1)).toMatchObject({ from: '2026-09-01', to: '2026-09-30' })
    expect(screen.getByLabelText('Period')).toHaveValue('custom')
    await user.click(screen.getByRole('button', { name: 'Download CSV: Products by sales' }))
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith('/admin/reports/sales/export/', {
        params: { from: '2026-09-01', to: '2026-09-30', table: 'top' },
        responseType: 'blob',
      }),
    )
  })

  it('appears in the menu for store managers too', async () => {
    signIn()
    mockApi({
      get: staffGet('manager', {
        '/admin/session/': { ...managerSession, sections: [...managerSession.sections, 'reports', 'assistant'] },
        '/notifications/summary/': { unread: 0 },
      }),
    })
    renderRoute('/admin')
    const menu = await screen.findByRole('navigation', { name: 'Admin sections' })
    expect(within(menu).getByRole('link', { name: 'Reports' })).toHaveAttribute('href', '/admin/reports')
    expect(within(menu).getByRole('link', { name: 'Business assistant' })).toHaveAttribute('href', '/admin/assistant')
  })
})

function answer(overrides: Partial<AssistantAnswer> = {}): AssistantAnswer {
  return {
    question: 'How much did we sell last month?',
    understood: true,
    intent: 'revenue',
    intent_label: 'Sales and revenue',
    report: 'sales',
    period: { from: '2026-09-01', to: '2026-09-30', label: 'September 2026' },
    store: null,
    text: 'Sales and revenue for September 2026 — Revenue: ₹1,25,000.00; Paid orders: 42.',
    kpis: [{ key: 'revenue', label: 'Revenue', value: '125000.00', format: 'money' }],
    comparison: {
      kpi: 'revenue',
      label: 'Revenue',
      current: '125000.00',
      previous: '100000.00',
      change_percent: 25,
      format: 'money',
      previous_period: { from: '2026-08-02', to: '2026-08-31' },
    },
    table: null,
    notes: [],
    link: '/admin/reports?report=sales&from=2026-09-01&to=2026-09-30',
    source: 'rules',
    suggestions: [],
    ...overrides,
  }
}

describe('business assistant', () => {
  it('answers from the numbers, compares periods and links to the report', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', {
        '/admin/session/': session,
        '/notifications/summary/': { unread: 0 },
        '/admin/assistant/': {
          ai: { provider: 'none', model: '', available: false },
          suggestions: ['How much did we sell last month?', 'Which items are low on stock?'],
          topics: [],
          stores: [],
        },
        '/admin/assistant/history/': { results: [] },
      }),
      post: { '/admin/assistant/': ({ body }: RequestInfo) => answer({ question: (body as { question: string }).question }) },
    })
    const { user } = renderRoute('/admin/assistant')
    await user.click(await screen.findByRole('button', { name: 'How much did we sell last month?' }))
    expect(screen.getByText(/by the built-in rules/)).toBeInTheDocument()
    const card = await screen.findByTestId('answer')
    expect(card).toHaveTextContent('Revenue: ₹1,25,000.00')
    expect(within(card).getByTestId('comparison')).toHaveTextContent('+25%')
    expect(within(card).getByText('From the numbers')).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: 'Open the full report' })).toHaveAttribute(
      'href',
      '/admin/reports?report=sales&from=2026-09-01&to=2026-09-30',
    )
    await user.type(screen.getByLabelText('Your question'), 'top 5 products')
    await user.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(() => expect(api.post).toHaveBeenLastCalledWith('/admin/assistant/', { question: 'top 5 products' }, { params: {} }))
    expect(screen.getAllByTestId('answer')).toHaveLength(2)
  })

  it('says when a local model words the answers', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', {
        '/admin/session/': session,
        '/notifications/summary/': { unread: 0 },
        '/admin/assistant/': { ai: { provider: 'ollama', model: 'qwen2.5:3b', available: true }, suggestions: [], topics: [], stores: [] },
        '/admin/assistant/history/': { results: [{ id: 1, question: 'Old question', answer: 'x', report: 'sales', period: { from: null, to: null }, store: null, source: 'ai', created_at: '2026-10-07T10:00:00+05:30' }] },
      }),
    })
    renderRoute('/admin/assistant')
    expect(await screen.findByText(/worded by the local model \(qwen2.5:3b\)/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Old question' })).toBeInTheDocument()
  })
})
