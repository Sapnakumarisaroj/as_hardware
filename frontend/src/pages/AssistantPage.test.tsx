import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AssistantMessage, AssistantStatus, Conversation, RecommendedProduct } from '@/features/ai/types'
import { cart, cartLine, customer, productSummary } from '@/test/fixtures'
import { httpError, mockApi, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const status: AssistantStatus = {
  ai_mode: 'basic',
  provider: 'none',
  model: '',
  languages: ['en', 'hi', 'hinglish'],
  suggested_prompts: {
    en: ['Find a drill for concrete', 'Help me repair a leaking tap', 'Build a painting kit', 'Find hardware under ₹1000'],
    hinglish: ['Concrete ke liye drill dhoondho', 'Tapakta nal theek karne mein madad karo', 'Painting ka kit banao', '₹1000 ke andar hardware dikhao'],
    hi: ['कंक्रीट के लिए ड्रिल ढूँढें', 'टपकता नल ठीक करने में मदद करें', 'पुताई का किट बनाएँ', '₹1000 के भीतर सामान दिखाएँ'],
  },
  greeting: {
    en: 'Hello! Tell me what you’re fixing, building or looking for and I’ll find the right products from our catalogue.',
    hinglish: 'Namaste! Batayein aap kya theek kar rahe hain.',
    hi: 'नमस्ते! बताइए आप क्या ठीक कर रहे हैं।',
  },
  max_products: 6,
}

const tap: RecommendedProduct = {
  ...productSummary({ id: 5, name: 'Brass Pillar Tap', slug: 'brass-pillar-tap', price: '899.00', mrp: '999.00', discount_percent: '10.00', default_variant_id: 55, variant_count: 1 }),
  variant_id: 55,
  reason: 'Matches “tap”',
}
const tape: RecommendedProduct = {
  ...productSummary({ id: 6, name: 'PTFE Thread Seal Tape', slug: 'ptfe-tape', price: '69.00', mrp: '79.00', default_variant_id: 66, variant_count: 1, stock_status: 'out_of_stock' }),
  variant_id: 66,
  reason: 'Matches “ptfe tape”',
}

function message(overrides: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: 2,
    role: 'assistant',
    content: 'A dripping tap usually needs a new washer.\n\nHere is what we have in the catalogue for that:',
    created_at: '2026-09-30T06:00:00Z',
    products: [tap, tape],
    questions: [],
    actions: [
      { type: 'add_to_cart', variant_id: 55, product_id: 5, quantity: 1 },
      { type: 'add_to_cart', variant_id: 66, product_id: 6, quantity: 1 },
      { type: 'add_all', label: 'Add recommended items to cart', variant_ids: [55, 66] },
    ],
    intent: 'REPAIR_HELP',
    ai_mode: 'basic',
    notice: '',
    knowledge: [],
    safety: [],
    estimate: null,
    ...overrides,
  }
}

const userMessage = (content: string, id = 1): AssistantMessage =>
  message({ id, role: 'user', content, products: [], actions: [], intent: '', ai_mode: '' })

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: 9,
    kind: 'assistant',
    language: 'en',
    title: 'fix a leaking tap',
    message_count: 2,
    created_at: '2026-09-30T06:00:00Z',
    updated_at: '2026-09-30T06:00:00Z',
    messages: [userMessage('fix a leaking tap'), message()],
    ...overrides,
  }
}

const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results })

const shopGet = { '/categories/': [], '/wishlist/': [], '/cart/': cart(), '/search/recent/': [] }

describe('AI assistant page', () => {
  it('welcomes a visitor with suggested prompts and asks them to sign in when they ask', async () => {
    mockApi({ get: { ...shopGet, '/ai/assistant/': status } })
    const { user, router } = renderRoute('/ai-assistant')
    expect(await screen.findByRole('heading', { name: 'AI hardware assistant' })).toBeInTheDocument()
    expect(await screen.findByText(/Tell me what you’re fixing/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Find a drill for concrete' })).toBeInTheDocument()
    expect(screen.getByText(/Basic mode: answers use keyword matching/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Help me repair a leaking tap' }))
    await waitFor(
      () => expect(currentUrl(router)).toBe(`/login?next=${encodeURIComponent('/ai-assistant?ask=Help%20me%20repair%20a%20leaking%20tap')}`),
      { timeout: 5000 }, // the login page is a separate chunk, loaded on first visit
    )
  })

  it('sends a question, shows the typing state, then the answer with real product cards', async () => {
    signIn()
    let resolve: (value: Conversation) => void = () => undefined
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/assistant/': status, '/ai/conversations/': page([]), '/ai/conversations/9/': conversation() },
      post: { '/ai/conversations/': () => new Promise<Conversation>((r) => (resolve = r)) },
    })
    const { user, router } = renderRoute('/ai-assistant')
    const input = await screen.findByLabelText('Your question')
    await user.type(input, 'fix a leaking tap{Enter}')

    expect(await screen.findByRole('status')).toHaveTextContent('The assistant is thinking…')
    expect(screen.getByText('fix a leaking tap')).toBeInTheDocument() // the question shows at once
    expect(api.post).toHaveBeenCalledWith('/ai/conversations/', { message: 'fix a leaking tap', language: 'en' })

    resolve(conversation())
    await waitFor(() => expect(currentUrl(router)).toBe('/ai-assistant?c=9'))
    expect(await screen.findByText('A dripping tap usually needs a new washer.')).toBeInTheDocument()
    const cards = within(screen.getByRole('list', { name: 'Recommended products' }))
    expect(cards.getAllByRole('listitem')).toHaveLength(2)
    expect(cards.getByRole('link', { name: 'Brass Pillar Tap' })).toHaveAttribute('href', '/p/brass-pillar-tap')
    expect(cards.getByText('₹899')).toBeInTheDocument()
    expect(cards.getByText('₹999')).toBeInTheDocument()
    expect(cards.getByText('Matches “tap”')).toBeInTheDocument()
    expect(cards.getByRole('button', { name: 'Out of stock' })).toBeDisabled() // the tape
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(input).toHaveValue('')
  })

  it('adds a recommended product, and all of them, through the cart API', async () => {
    signIn()
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/assistant/': status, '/ai/conversations/': page([conversation()]), '/ai/conversations/9/': conversation() },
      post: { '/cart/items/': ({ body }: RequestInfo) => cart({ items: [cartLine({ variant_id: (body as { variant_id: number }).variant_id })] }) },
    })
    const { user } = renderRoute('/ai-assistant?c=9')
    const cards = within(await screen.findByRole('list', { name: 'Recommended products' }))
    await user.click(cards.getByRole('button', { name: 'Add to cart' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/', { variant_id: 55, quantity: 1 }))
    expect(await screen.findByText('Added to cart: Brass Pillar Tap')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add recommended items to cart' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/', { variant_id: 66, quantity: 1 }))
    expect(await screen.findByText('Added 2 items to your cart.')).toBeInTheDocument()
  })

  it('continues a conversation and shows the follow-up question, knowledge and safety text', async () => {
    signIn()
    const answer = message({
      id: 4,
      content: 'Bathroom mein kya theek karna hai?',
      products: [],
      actions: [],
      questions: ['Bathroom mein kya theek karna hai — tap, pipe ya tiles?'],
      safety: ['Safety: switch off the MCB first.'],
      knowledge: [{ title: 'PTFE tape', text: 'Thin white tape.' }],
    })
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/assistant/': status, '/ai/conversations/': page([conversation()]), '/ai/conversations/9/': conversation() },
      post: {
        '/ai/conversations/9/messages/': { conversation_id: 9, title: 'fix a leaking tap', user_message: userMessage('bathroom ka saman', 3), assistant_message: answer },
      },
    })
    const { user } = renderRoute('/ai-assistant?c=9')
    await screen.findByText('A dripping tap usually needs a new washer.')
    await user.selectOptions(screen.getByLabelText('Language'), 'Hinglish')
    await user.type(screen.getByLabelText('Your question'), 'bathroom ka saman')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/ai/conversations/9/messages/', { message: 'bathroom ka saman', language: 'hinglish' }),
    )
    expect(await screen.findByText('Bathroom mein kya theek karna hai?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Bathroom mein kya theek karna hai — tap, pipe ya tiles\?/ })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Messages' }).children).toHaveLength(4) // two turns, each question + answer
  })

  it('shows the fallback notice when the model was unavailable', async () => {
    signIn()
    mockApi({
      get: {
        ...shopGet,
        '/auth/me/': customer,
        '/ai/assistant/': { ...status, ai_mode: 'llm', provider: 'ollama', model: 'qwen2.5:3b' },
        '/ai/conversations/': page([]),
        '/ai/conversations/9/': conversation({ messages: [userMessage('tap'), message({ notice: 'AI is temporarily unavailable. You can search products normally.' })] }),
      },
    })
    renderRoute('/ai-assistant?c=9')
    expect(await screen.findByText('AI is temporarily unavailable. You can search products normally.')).toBeInTheDocument()
    expect(screen.queryByText(/Basic mode: answers use keyword matching/)).not.toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Recommended products' })).toBeInTheDocument() // products still shown
  })

  it('shows an error with a retry when the request fails, keeping the question', async () => {
    signIn()
    let attempts = 0
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/assistant/': status, '/ai/conversations/': page([]), '/ai/conversations/9/': conversation() },
      post: { '/ai/conversations/': () => (++attempts === 1 ? httpError(503, 'The assistant is busy.', 'unavailable') : conversation()) },
    })
    const { user } = renderRoute('/ai-assistant')
    await user.type(await screen.findByLabelText('Your question'), 'fix a leaking tap{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('The assistant is busy.')
    expect(screen.getByLabelText('Your question')).toHaveValue('fix a leaking tap')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('A dripping tap usually needs a new washer.')).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledTimes(2)
  })

  it('lists past conversations, opens one, clears and deletes it', async () => {
    signIn()
    const older = conversation({ id: 8, title: 'drill for concrete', messages: [userMessage('drill for concrete'), message({ content: 'You need an impact drill.', products: [] })] })
    const api = mockApi({
      get: {
        ...shopGet,
        '/auth/me/': customer,
        '/ai/assistant/': status,
        '/ai/conversations/': page([conversation(), older]),
        '/ai/conversations/9/': conversation(),
        '/ai/conversations/8/': older,
      },
      post: { '/ai/conversations/8/clear/': { ...older, title: '', messages: [] } },
      delete: { '/ai/conversations/8/': '' },
    })
    const { user, router } = renderRoute('/ai-assistant?c=9')
    const history = within(await screen.findByRole('navigation', { name: 'Your conversations' }))
    expect(history.getByRole('button', { name: /fix a leaking tap/ })).toHaveAttribute('aria-current', 'true')
    await user.click(history.getByRole('button', { name: /drill for concrete/ }))
    await waitFor(() => expect(currentUrl(router)).toBe('/ai-assistant?c=8'))
    expect(await screen.findByText('You need an impact drill.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Clear' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ai/conversations/8/clear/', {}))
    expect(await screen.findByText(/Tell me what you’re fixing/)).toBeInTheDocument()
    expect(screen.queryByText('You need an impact drill.')).not.toBeInTheDocument()

    await user.click(history.getByRole('button', { name: /fix a leaking tap/ }))
    await screen.findByText('A dripping tap usually needs a new washer.')
    await user.click(screen.getByRole('button', { name: 'New conversation' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/ai-assistant'))
    expect(screen.getByRole('button', { name: 'Find a drill for concrete' })).toBeInTheDocument()
  })

  it('deletes the open conversation', async () => {
    signIn()
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/assistant/': status, '/ai/conversations/': page([conversation()]), '/ai/conversations/9/': conversation() },
      delete: { '/ai/conversations/9/': '' },
    })
    const { user, router } = renderRoute('/ai-assistant?c=9')
    await user.click(await screen.findByRole('button', { name: 'Delete conversation' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/ai/conversations/9/'))
    await waitFor(() => expect(currentUrl(router)).toBe('/ai-assistant'))
    expect(await screen.findByText('Conversation deleted.')).toBeInTheDocument()
  })

  it('opens the history in a drawer on small screens', async () => {
    signIn()
    mockApi({ get: { ...shopGet, '/auth/me/': customer, '/ai/assistant/': status, '/ai/conversations/': page([conversation()]) } })
    const { user } = renderRoute('/ai-assistant')
    await user.click(await screen.findByRole('button', { name: 'History' }))
    const drawer = within(screen.getByRole('dialog', { name: 'Conversations' }))
    expect(await drawer.findByRole('button', { name: /fix a leaking tap/ })).toBeInTheDocument()
  })

  it('the menu links to the assistant (it is not a product navigation item)', async () => {
    mockApi({ get: { ...shopGet, '/ai/assistant/': status } })
    const { user } = renderRoute('/')
    await user.click(screen.getByRole('button', { name: 'Open menu' }))
    const menu = await screen.findByRole('navigation', { name: 'Mobile menu' })
    expect(within(menu).getByRole('link', { name: 'AI assistant' })).toHaveAttribute('href', '/ai-assistant')
  })
})
