import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { RecommendedProduct } from '@/features/ai/types'
import type { VoiceLine, VoiceResult, VoiceStatus } from '@/features/voice/types'
import { cart, cartLine, customer, productSummary } from '@/test/fixtures'
import { mockApi, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results })
const shopGet = { '/categories/': [], '/wishlist/': [], '/cart/': cart(), '/search/recent/': [] }

const status: VoiceStatus = {
  languages: [
    { code: 'en', label: 'English', speech: 'en-IN', voice: 'en-IN' },
    { code: 'hi', label: 'हिन्दी', speech: 'hi-IN', voice: 'hi-IN' },
    { code: 'hinglish', label: 'Hinglish', speech: 'hi-IN', voice: 'en-IN' },
  ],
  examples: { en: ['10 bags of 53 grade cement'], hi: ['दस बोरी सीमेंट कार्ट में डालो'], hinglish: ['Das bori cement cart mein daalo'] },
  browser_recognition: true,
  server_recognition: { provider: 'none', model: '', enabled: false, available: false },
  server_voice: { provider: 'none', model: '', enabled: false, available: false },
  max_audio_bytes: 2097152,
  max_audio_seconds: 20,
  max_lines: 5,
  max_speak_chars: 400,
}

const cement: RecommendedProduct = {
  ...productSummary({ id: 29, name: 'OPC 53 Grade Cement', slug: 'opc-cement', price: '410.00', mrp: '450.00', default_variant_id: 77 }),
  variant_id: 77,
  reason: '',
}

function line(overrides: Partial<VoiceLine> = {}): VoiceLine {
  return {
    heard: '10 bags of 53 grade cement',
    query: '53 grade cement',
    quantity: 10,
    quantity_given: true,
    spoken_unit: 'bag',
    status: 'ready',
    match: 'exact',
    message: '10 bags OPC 53 Grade Cement: bulk price ₹399 each (for 10 or more), total ₹3,990.',
    note: '',
    product_id: 29,
    variant_id: 77,
    product_name: 'OPC 53 Grade Cement',
    unit: 'bag',
    filters: [{ param: 'opt_grade', value: '53-grade', label: 'Grade: 53 Grade' }],
    quote: {
      quantity: 10,
      sku: 'CEM-53',
      options: { grade: '53-grade' },
      mrp: '450.00',
      base_unit_price: '410.00',
      unit_price: '399.00',
      applied_tier: { min_quantity: 10 },
      next_tier: { min_quantity: 30, unit_price: '389.00', units_more: 20, reachable: true },
      line_total: '3990.00',
      bulk_saving: '110.00',
      offer_discount: '0.00',
      offers: [],
      total: '3990.00',
      stock_status: 'in_stock',
      within_stock: true,
      max_order_quantity: 50,
    },
    product: cement,
    alternatives: [],
    ...overrides,
  }
}

function result(overrides: Partial<VoiceResult> = {}): VoiceResult {
  return {
    conversation_id: null,
    transcript: '10 bags of 53 grade cement',
    language: 'en',
    intent: 'add_to_cart',
    reply: '10 bags OPC 53 Grade Cement: bulk price ₹399 each (for 10 or more), total ₹3,990. Add 20 more to pay ₹389 each. Say “yes” or tap Add to cart.',
    speech: '10 bags OPC 53 Grade Cement: bulk price 399 rupees each, total 3990 rupees.',
    lines: [line()],
    products: [],
    navigate: null,
    search_path: '',
    needs_confirmation: true,
    add_now: false,
    ai_mode: 'basic',
    questions: [],
    notice: '',
    ...overrides,
  }
}

/** A stand-in for the browser's SpeechRecognition that "hears" `heard` (or fails with `error`). */
function installRecognition(heard: string, error?: string) {
  const instances: { lang: string }[] = []
  class FakeRecognition {
    lang = ''
    interimResults = false
    continuous = false
    maxAlternatives = 1
    onresult: ((event: unknown) => void) | null = null
    onerror: ((event: { error: string }) => void) | null = null
    onend: (() => void) | null = null
    constructor() {
      instances.push(this)
    }
    start() {
      setTimeout(() => {
        if (error) this.onerror?.({ error })
        else {
          this.onresult?.({ resultIndex: 0, results: { length: 1, 0: Object.assign([{ transcript: heard, confidence: 0.92 }], { isFinal: true }) } })
        }
        this.onend?.()
      }, 0)
    }
    stop() {}
    abort() {}
  }
  ;(window as unknown as { webkitSpeechRecognition: unknown }).webkitSpeechRecognition = FakeRecognition
  return instances
}

function installSynthesis() {
  const spoken: { text: string; lang: string }[] = []
  class Utterance {
    lang = ''
    voice: unknown = null
    rate = 1
    constructor(public text: string) {}
  }
  const synthesis = {
    getVoices: () => [{ lang: 'en-IN', name: 'English India' }, { lang: 'hi-IN', name: 'Hindi' }],
    speak: (u: Utterance) => spoken.push({ text: u.text, lang: u.lang }),
    cancel: vi.fn(),
  }
  Object.assign(window, { speechSynthesis: synthesis, SpeechSynthesisUtterance: Utterance })
  return spoken
}

afterEach(() => {
  const w = window as unknown as Record<string, unknown>
  delete w.webkitSpeechRecognition
  delete w.speechSynthesis
  delete w.SpeechSynthesisUtterance
})

describe('shop by voice', () => {
  it('is reachable from the search bar', async () => {
    mockApi({ get: { ...shopGet, '/products/': page([]), '/ai/voice/': status } })
    const { user, router } = renderRoute('/')
    await user.click(await within(screen.getByRole('banner')).findByRole('link', { name: 'Shop by voice' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/voice'))
    expect(await screen.findByRole('heading', { name: 'Shop by voice', level: 1 })).toBeInTheDocument()
  })

  it('listens in the chosen language and shows the price for the spoken quantity', async () => {
    const recognitions = installRecognition('दस बोरी 53 ग्रेड सीमेंट')
    const spoken = installSynthesis()
    let sent: Record<string, unknown> = {}
    mockApi({
      get: { ...shopGet, '/ai/voice/': status },
      post: {
        '/ai/voice/command/': ({ body }: RequestInfo) => {
          sent = body as Record<string, unknown>
          return result({ transcript: 'दस बोरी 53 ग्रेड सीमेंट', language: 'hi', reply: '10 बोरी OPC 53 Grade Cement: थोक दर ₹399', speech: '10 बोरी, 399 रुपये' })
        },
      },
    })
    const { user } = renderRoute('/voice')
    await user.click(await screen.findByRole('radio', { name: 'हिन्दी' }))
    expect(screen.getByRole('radio', { name: 'हिन्दी' })).toHaveAttribute('aria-checked', 'true')
    await user.click(screen.getByRole('button', { name: 'Start speaking' }))

    expect(await screen.findByTestId('voice-transcript')).toHaveTextContent('“दस बोरी 53 ग्रेड सीमेंट”')
    expect(recognitions[0]?.lang).toBe('hi-IN')
    expect(sent).toMatchObject({ transcript: 'दस बोरी 53 ग्रेड सीमेंट', language: 'hi', pending: [], conversation_id: null })
    const card = within(screen.getByTestId('voice-line'))
    expect(card.getByRole('link', { name: 'OPC 53 Grade Cement' })).toHaveAttribute('href', '/p/opc-cement')
    expect(card.getByText('Bulk price from 10')).toBeInTheDocument()
    expect(card.getByText('Understood: Grade: 53 Grade')).toBeInTheDocument()
    expect(screen.getByTestId('voice-line-total')).toHaveTextContent('₹3,990')
    expect(card.getByRole('button', { name: 'Add 20 more for ₹389 each (make it 30)' })).toBeInTheDocument()
    // the answer is read aloud in Hindi
    expect(spoken).toEqual([{ text: '10 बोरी, 399 रुपये', lang: 'hi-IN' }])
    expect(screen.getByText(/Waiting for your “yes”/)).toBeInTheDocument()
  })

  it('remembers the language and the read-aloud choice', async () => {
    const spoken = installSynthesis()
    mockApi({ get: { ...shopGet, '/ai/voice/': status }, post: { '/ai/voice/command/': result() } })
    const first = renderRoute('/voice')
    await first.user.click(await screen.findByRole('radio', { name: 'Hinglish' }))
    await first.user.click(screen.getByRole('checkbox', { name: /Read answers aloud/ }))
    first.unmount()

    const { user } = renderRoute('/voice')
    expect(await screen.findByRole('radio', { name: 'Hinglish' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('checkbox', { name: /Read answers aloud/ })).not.toBeChecked()
    await user.type(screen.getByLabelText('Type what you need'), 'das bori cement{Enter}')
    expect(await screen.findByTestId('voice-transcript')).toBeInTheDocument()
    expect(spoken).toEqual([])
  })

  it('explains a blocked microphone and offers typing', async () => {
    installRecognition('', 'not-allowed')
    mockApi({ get: { ...shopGet, '/ai/voice/': status } })
    const { user } = renderRoute('/voice')
    await user.click(await screen.findByRole('button', { name: 'Start speaking' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Microphone access was blocked')
    expect(screen.getByLabelText('Type what you need')).toBeInTheDocument()
  })

  it('works by typing when the browser cannot listen', async () => {
    mockApi({ get: { ...shopGet, '/ai/voice/': status }, post: { '/ai/voice/command/': result() } })
    const { user } = renderRoute('/voice')
    expect(await screen.findByText('Voice input isn’t available in this browser')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Start speaking' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Your browser can’t listen')
    await user.click(screen.getByRole('button', { name: '10 bags of 53 grade cement' }))
    expect(await screen.findByTestId('voice-line')).toBeInTheDocument()
  })

  it('changes the quantity to reach the next bulk price', async () => {
    const bodies: Record<string, unknown>[] = []
    mockApi({
      get: { ...shopGet, '/ai/voice/': status },
      post: {
        '/ai/voice/command/': ({ body }: RequestInfo) => {
          bodies.push(body as Record<string, unknown>)
          return bodies.length === 1
            ? result()
            : result({
                intent: 'set_quantity',
                lines: [line({ quantity: 30, quote: { ...line().quote!, quantity: 30, unit_price: '389.00', total: '11670.00', applied_tier: { min_quantity: 30 }, next_tier: null } })],
              })
        },
      },
    })
    const { user } = renderRoute('/voice')
    await user.type(await screen.findByLabelText('Type what you need'), '10 bags of 53 grade cement{Enter}')
    await user.click(await screen.findByRole('button', { name: /make it 30/ }))
    await waitFor(() => expect(screen.getByTestId('voice-line-total')).toHaveTextContent('₹11,670'))
    expect(bodies[1]).toMatchObject({ transcript: '30', pending: [{ product_id: 29, variant_id: 77, quantity: 10 }] })
  })

  it('adds to the cart only after “yes”, through the cart API', async () => {
    signIn()
    const bodies: Record<string, unknown>[] = []
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/voice/': status, '/ai/voice-sessions/': page([]) },
      post: {
        '/ai/voice/command/': ({ body }: RequestInfo) => {
          bodies.push(body as Record<string, unknown>)
          return bodies.length === 1
            ? result({ conversation_id: 5 })
            : result({ conversation_id: 5, intent: 'confirm', transcript: 'yes', reply: 'Adding it to your cart.', needs_confirmation: false, add_now: true })
        },
        '/cart/items/': ({ body }: RequestInfo) => cart({ items: [cartLine({ variant_id: (body as { variant_id: number }).variant_id, quantity: 10 })] }),
      },
    })
    const { user } = renderRoute('/voice')
    const input = await screen.findByLabelText('Type what you need')
    await user.type(input, '10 bags of 53 grade cement{Enter}')
    await screen.findByTestId('voice-line')
    expect(api.post).not.toHaveBeenCalledWith('/cart/items/', expect.anything())

    await user.type(input, 'yes{Enter}')
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/', { variant_id: 77, quantity: 10 }))
    expect(bodies[1]).toMatchObject({ transcript: 'yes', conversation_id: 5, pending: [{ product_id: 29, variant_id: 77, quantity: 10 }] })
    expect(await screen.findByText(/Added to cart: OPC 53 Grade Cement/)).toBeInTheDocument()
  })

  it('adds one line with its button', async () => {
    signIn()
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/voice/': status, '/ai/voice-sessions/': page([]) },
      post: { '/ai/voice/command/': result(), '/cart/items/': cart({ items: [cartLine({ variant_id: 77, quantity: 10 })] }) },
    })
    const { user } = renderRoute('/voice')
    await user.type(await screen.findByLabelText('Type what you need'), 'cement{Enter}')
    await user.click(await screen.findByRole('button', { name: 'Add 10 to cart' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/', { variant_id: 77, quantity: 10 }))
  })

  it('asks a signed-out shopper to sign in and keeps the item', async () => {
    mockApi({ get: { ...shopGet, '/ai/voice/': status }, post: { '/ai/voice/command/': result() } })
    const { user, router } = renderRoute('/voice')
    await user.type(await screen.findByLabelText('Type what you need'), 'cement{Enter}')
    await user.click(await screen.findByRole('button', { name: 'Add 10 to cart' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/login?next=%2Fvoice'))
    expect(JSON.parse(window.sessionStorage.getItem('boltrun.pending-action') ?? '{}')).toMatchObject({ type: 'cart', variantId: 77, quantity: 10 })
  })

  it('shows lines that cannot be added and never offers to add them', async () => {
    mockApi({
      get: { ...shopGet, '/ai/voice/': status },
      post: {
        '/ai/voice/command/': result({
          needs_confirmation: false,
          lines: [line({ status: 'too_many', message: 'OPC 53 Grade Cement: at most 50 per order.', quote: null, quantity: 60 })],
        }),
      },
    })
    const { user } = renderRoute('/voice')
    await user.type(await screen.findByLabelText('Type what you need'), '60 bags cement{Enter}')
    expect(await screen.findByRole('note')).toHaveTextContent('at most 50 per order')
    expect(screen.queryByRole('button', { name: /to cart/ })).not.toBeInTheDocument()
  })

  it('links a spoken quantity request to the quantity calculator', async () => {
    mockApi({
      get: { ...shopGet, '/ai/voice/': status },
      post: {
        '/ai/voice/command/': result({
          intent: 'quantity',
          reply: 'Plastering · 500 sq ft — estimated quantity: 4 bags…',
          quantity: { calculator: 'plastering', title: 'Plastering · 500 sq ft', complete: true, path: '/quantity?q=500%20sq%20ft%20plastering' },
        }),
      },
    })
    const { user } = renderRoute('/voice')
    await user.type(await screen.findByLabelText('Type what you need'), '500 sq ft plastering ka saman{Enter}')
    expect(await screen.findByRole('link', { name: 'Open the quantity calculator: Plastering · 500 sq ft' })).toHaveAttribute(
      'href',
      '/quantity?q=500%20sq%20ft%20plastering',
    )
  })

  it('opens the page that was asked for', async () => {
    mockApi({
      get: { ...shopGet, '/ai/voice/': status },
      post: { '/ai/voice/command/': result({ intent: 'navigate', lines: [], reply: 'Opening your cart.', navigate: { page: 'cart', path: '/cart' } }) },
    })
    const { user, router } = renderRoute('/voice')
    await user.type(await screen.findByLabelText('Type what you need'), 'open my cart{Enter}')
    await waitFor(() => expect(currentUrl(router)).toBe('/cart'))
  })

  it('lists products for a spoken search', async () => {
    mockApi({
      get: { ...shopGet, '/ai/voice/': status },
      post: {
        '/ai/voice/command/': result({
          intent: 'search',
          lines: [],
          reply: 'Here’s what we have for “drills”.',
          needs_confirmation: false,
          products: [{ ...cement, id: 20, name: 'Impact Drill', slug: 'impact-drill', reason: 'voice search' }],
          search_path: '/search?q=drills',
        }),
      },
    })
    const { user } = renderRoute('/voice')
    await user.type(await screen.findByLabelText('Type what you need'), 'show me drills{Enter}')
    const products = within(await screen.findByRole('list', { name: 'Products' }))
    expect(products.getByRole('link', { name: 'Impact Drill' })).toHaveAttribute('href', '/p/impact-drill')
    expect(screen.getByRole('link', { name: 'See all results' })).toHaveAttribute('href', '/search?q=drills')
  })

  it('shows and clears the signed-in history', async () => {
    signIn()
    const api = mockApi({
      get: {
        ...shopGet,
        '/auth/me/': customer,
        '/ai/voice/': status,
        '/ai/voice-sessions/': page([{ id: 4, title: '10 bags cement', language: 'en', turns: 2, created_at: '2026-10-06T10:00:00Z', updated_at: '2026-10-06T10:05:00Z' }]),
      },
      post: { '/ai/voice-sessions/clear/': null },
    })
    const { user } = renderRoute('/voice')
    const history = within(await screen.findByRole('region', { name: 'Your recent voice sessions' }))
    expect(history.getByText('10 bags cement')).toBeInTheDocument()
    expect(history.getByText(/2 requests/)).toBeInTheDocument()
    await user.click(history.getByRole('button', { name: 'Clear all' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ai/voice-sessions/clear/', {}))
  })

  it('shows the server error message', async () => {
    const { httpError } = await import('@/test/mockApi')
    mockApi({ get: { ...shopGet, '/ai/voice/': status }, post: { '/ai/voice/command/': httpError(429, 'Too many requests. Wait a minute.') } })
    const { user } = renderRoute('/voice')
    await user.type(await screen.findByLabelText('Type what you need'), 'cement{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests. Wait a minute.')
  })
})
