import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AssistantMessage, AssistantStatus, Conversation } from '@/features/ai/types'
import type { CompatibilityProblem, CompatibilityResult, ProductCompatibility, Verdict } from '@/features/compatibility/types'
import type { ProjectPlan } from '@/features/projects/types'
import { cart, cartLine, customer, productPage, productSummary, variant, wireDetail } from '@/test/fixtures'
import { mockApi, type RequestInfo } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

const reviews = { count: 0, next: null, previous: null, results: [] }
const shopGet = { '/categories/': [], '/wishlist/': [], '/cart/': cart(), '/search/recent/': [] }
const wire = wireDetail()
const mcbSummary = productSummary({ id: 4, name: 'MCB Single Pole', slug: 'mcb-single-pole', default_variant_id: 301 })
const mcbDetail = wireDetail({
  id: 4,
  name: 'MCB Single Pole',
  slug: 'mcb-single-pole',
  variants: [variant({ id: 301, name: '16 A', is_default: true }), variant({ id: 302, name: '32 A' })],
})
const thickWire = productSummary({ id: 9, name: 'Copper Wire 4 sq mm', slug: 'wire-4', default_variant_id: 90 })

function result(verdict: Verdict, overrides: Partial<CompatibilityResult> = {}): CompatibilityResult {
  return {
    verdict,
    reason: 'A 32 A MCB needs 6 sq mm wire or thicker; this is 1.5 sq mm.',
    product_a: { id: wire.id, name: wire.name, slug: wire.slug, kind: 'wire' },
    product_b: { id: 4, name: 'MCB Single Pole', slug: 'mcb-single-pole', kind: 'mcb' },
    variant_a: null,
    variant_b: 302,
    checks: [{ name: 'wire size', status: verdict === 'COMPATIBLE' ? 'pass' : 'fail', detail: 'A 32 A MCB needs 6 sq mm wire or thicker.' }],
    matching_variants: [],
    sources: ['rule:mcb+wire'],
    options: [],
    ...overrides,
  }
}

const groups: ProductCompatibility = {
  product_id: wire.id,
  kind: 'wire',
  groups: {
    required: [],
    compatible: [{ product_id: 4, note: '', source: 'rules', verdict: 'COMPATIBLE', reason: 'The wire is thick enough for the MCB rating.', product: mcbSummary }],
    accessories: [{ product_id: 9, note: 'For joints', source: 'shop', verdict: null, reason: 'For joints', product: thickWire }],
    alternatives: [],
  },
}

function pdpRoutes(extra: Record<string, unknown> = {}) {
  return {
    ...shopGet,
    [`/products/${wire.slug}/`]: wire,
    [`/products/${wire.slug}/reviews/`]: reviews,
    '/products/': productPage([mcbSummary]),
    '/products/mcb-single-pole/': mcbDetail,
    [`/products/${wire.id}/compatibility/`]: groups,
    ...extra,
  }
}

const bodies = (spy: ReturnType<typeof mockApi>['post'], url: string) =>
  spy.mock.calls.filter(([called]) => called === url).map(([, body]) => body as Record<string, unknown>)

describe('Compatibility on the product page', () => {
  it('checks this product against another one and its variant, and shows the verdict with options', async () => {
    const api = mockApi({
      get: pdpRoutes(),
      post: { '/compatibility/check/': result('NOT_COMPATIBLE', { options: [{ product_id: 9, variant_id: 90, verdict: 'COMPATIBLE', reason: 'ok', product: thickWire }] }) },
    })
    const { user } = renderRoute(`/p/${wire.slug}`)
    const section = within(await screen.findByRole('region', { name: 'Compatibility' }))
    expect(section.getByRole('button', { name: 'Check compatibility' })).toBeDisabled()
    await user.type(section.getByLabelText('Check with another product'), 'mcb')
    await user.click(await section.findByRole('button', { name: 'MCB Single Pole' }))
    await user.selectOptions(await section.findByLabelText("Other product's variant"), '302')
    await user.click(section.getByRole('button', { name: 'Check compatibility' }))
    await waitFor(() => expect(bodies(api.post, '/compatibility/check/')[0]).toMatchObject({ product_a: wire.id, product_b: 4, variant_b: 302 }))
    const verdict = await section.findByRole('status')
    expect(verdict).toHaveTextContent('Not compatible')
    expect(verdict).toHaveTextContent('Reason: A 32 A MCB needs 6 sq mm wire or thicker')
    expect(within(verdict).getByRole('link', { name: /Copper Wire 4 sq mm/ })).toHaveAttribute('href', '/p/wire-4')
    expect(section.getByRole('link', { name: 'Ask the assistant' })).toHaveAttribute('href', expect.stringContaining(`product=${wire.id}`))
  })

  it.each([
    ['COMPATIBLE', 'Compatible'],
    ['POSSIBLY_COMPATIBLE', 'Possibly compatible'],
    ['INSUFFICIENT_INFORMATION', 'Not enough information'],
  ] as const)('shows the %s state', async (verdict, text) => {
    mockApi({ get: pdpRoutes(), post: { '/compatibility/check/': result(verdict) } })
    const { user } = renderRoute(`/p/${wire.slug}`)
    const section = within(await screen.findByRole('region', { name: 'Compatibility' }))
    await user.type(section.getByLabelText('Check with another product'), 'mcb')
    await user.click(await section.findByRole('button', { name: 'MCB Single Pole' }))
    await user.click(section.getByRole('button', { name: 'Check compatibility' }))
    expect(await section.findByRole('status')).toHaveTextContent(text)
  })

  it('groups the recommended accessories', async () => {
    mockApi({ get: pdpRoutes() })
    renderRoute(`/p/${wire.slug}`)
    expect(await screen.findByRole('heading', { name: 'Recommended accessories' })).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Works with it' })).getByText('The wire is thick enough for the MCB rating.')).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Goes well with' })).getByText('For joints')).toBeInTheDocument()
  })
})

const status: AssistantStatus = {
  ai_mode: 'basic',
  provider: 'none',
  model: '',
  languages: ['en', 'hi', 'hinglish'],
  suggested_prompts: { en: ['Find a drill'], hinglish: ['Drill dhoondho'], hi: ['ड्रिल ढूँढें'] },
  greeting: { en: 'Hello!', hinglish: 'Namaste!', hi: 'नमस्ते!' },
  max_products: 6,
}

function assistantMessage(overrides: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: 2,
    role: 'assistant',
    content: '✅ Compatible: Masonry Drill Bit Set with Impact Drill.\n\nThe 13 mm chuck takes every bit.',
    created_at: '2026-10-06T06:00:00Z',
    products: [],
    questions: [],
    actions: [],
    intent: 'PRODUCT_SEARCH',
    ai_mode: 'basic',
    notice: '',
    knowledge: [],
    safety: [],
    estimate: null,
    compatibility: { verdict: 'COMPATIBLE', reason: 'The 13 mm chuck takes every bit.' },
    ...overrides,
  }
}

describe('Compatibility in the assistant', () => {
  it('sends the viewed product and shows the verdict from the listings', async () => {
    signIn()
    const conversation: Conversation = {
      id: 9,
      kind: 'assistant',
      language: 'en',
      title: 'Will this work',
      message_count: 2,
      created_at: '2026-10-06T06:00:00Z',
      updated_at: '2026-10-06T06:00:00Z',
      messages: [assistantMessage({ id: 1, role: 'user', content: 'Will this work with the impact drill?', compatibility: null }), assistantMessage()],
    }
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/assistant/': status, '/ai/conversations/': { count: 0, next: null, previous: null, results: [] }, '/ai/conversations/9/': conversation },
      post: { '/ai/conversations/': conversation },
    })
    const { user } = renderRoute(`/ai-assistant?product=22&ask=${encodeURIComponent('Will this work with the impact drill?')}`)
    await user.click(await screen.findByRole('button', { name: /^Send/ }))
    await waitFor(() => expect(bodies(api.post, '/ai/conversations/')[0]).toMatchObject({ message: 'Will this work with the impact drill?', product_id: 22 }))
    expect(await screen.findByLabelText('Compatibility verdict')).toHaveTextContent('Compatible · from the product listings')
  })
})

function problem(overrides: Partial<CompatibilityProblem> = {}): CompatibilityProblem {
  return {
    ...result('NOT_COMPATIBLE'),
    message: 'Your selected Core Drill Bit Set won’t work with Cordless Drill 12V. The smallest bit (16 mm) is bigger than the 10 mm chuck.',
    options: [{ product_id: 23, variant_id: 77, verdict: 'COMPATIBLE', reason: 'fits', product: productSummary({ id: 23, name: 'HSS Drill Bit Set', slug: 'hss' }) }],
    ...overrides,
  }
}

describe('Compatibility in the cart and in kits', () => {
  it('warns about cart lines that don’t fit and replaces one only after the customer confirms', async () => {
    signIn()
    const lines = [cartLine({ id: 1, variant_id: 11, product_name: 'Cordless Drill 12V' }), cartLine({ id: 2, variant_id: 12, product_name: 'Core Drill Bit Set' })]
    const smart = {
      empty: false,
      summary: null,
      titles: {},
      top_actions: [],
      sections: [
        {
          key: 'warnings',
          title: 'Cart warnings',
          items: [
            {
              type: 'compatibility',
              message: 'Core Drill Bit Set won’t work with Cordless Drill 12V. Masonry Drill Bit 6mm fits.',
              action: 'replace',
              priority: 100,
              cart_item_id: 2,
              product_id: 7,
              variant_id: 77,
              product: productSummary({ id: 7, name: 'Masonry Drill Bit 6mm', slug: 'masonry-bit' }),
            },
          ],
        },
      ],
    }
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/cart/': cart({ items: lines }), '/shopping/cart/': smart, '/addresses/': [] },
      post: { '/cart/items/2/replace/': ({ body }: RequestInfo) => cart({ items: [lines[0]!, cartLine({ id: 3, variant_id: (body as { variant_id: number }).variant_id })] }) },
    })
    const { user } = renderRoute('/cart')
    expect(await screen.findByText(/won’t work with Cordless Drill 12V/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace' }))
    expect(api.post).not.toHaveBeenCalledWith('/cart/items/2/replace/', expect.anything())
    expect(screen.getByText('Replace with Masonry Drill Bit 6mm?')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Yes, replace' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/2/replace/', { variant_id: 77 }))
  })

  it('offers compatible options in a project kit and uses one', async () => {
    signIn()
    const plan = {
      id: 7,
      title: 'Wall drilling',
      project_type: 'wall_drilling',
      type_name: 'Wall drilling',
      status: 'ready',
      description: '',
      language: 'en',
      summary: '',
      answers: {},
      from_description: [],
      questions: [],
      missing: [],
      assumptions: [],
      complete: true,
      safety: [],
      professional: '',
      not_sold: '',
      estimate_notice: '',
      created_at: '2026-10-06T06:00:00Z',
      updated_at: '2026-10-06T06:00:00Z',
      kit: {
        items: [],
        postal_code: '',
        totals: { item_count: 0, mrp_total: '0', subtotal: '0', bulk_savings: '0', offer_discount: '0', delivery_fee: '0', tax_included: '0', grand_total: '0', savings_vs_mrp: '0' },
        offers: [],
        offers_in_reach: [],
        delivery: { checked: false, available: false, message: '', label: '', delivery_type: null, eta_minutes: null, fee: '0', free_delivery_reason: '', amount_to_free_delivery: '0', free_delivery_hint: '', shipments: [] },
        issues: [],
        can_add_to_cart: false,
        not_found_count: 0,
        included_count: 0,
        compatibility: [problem({ keys: [31, 32], verdict: 'POSSIBLY_COMPATIBLE', message: 'Your selected drill bit may not work with this drill.' })],
      },
    } as unknown as ProjectPlan
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/projects/7/': plan },
      patch: { '/ai/projects/7/items/32/': plan },
    })
    const { user } = renderRoute('/projects/7')
    expect(await screen.findByText('Your selected drill bit may not work with this drill.')).toBeInTheDocument()
    await user.click(screen.getByText('View compatible options'))
    await user.click(screen.getByRole('button', { name: 'Use this instead' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/ai/projects/7/items/32/', expect.objectContaining({ variant_id: 77 })))
  })
})
