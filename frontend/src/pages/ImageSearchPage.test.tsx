import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ImageProduct, ImageSearchResult, ImageSearchStatus } from '@/features/imageSearch/types'
import { cart, cartLine, customer, productSummary } from '@/test/fixtures'
import { httpError, mockApi, type RequestInfo } from '@/test/mockApi'
import { currentUrl, renderRoute, signIn } from '@/test/utils'

const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results })
const shopGet = { '/categories/': [], '/wishlist/': [], '/cart/': cart(), '/search/recent/': [] }

const status: ImageSearchStatus = {
  enabled: true,
  available: true,
  provider: 'clip',
  model: 'clip-ViT-L-14',
  calibrated: true,
  max_bytes: 8 * 1024 * 1024,
  max_megabytes: 8,
  accepted_types: ['image/jpeg', 'image/png', 'image/webp'],
}

const hammer: ImageProduct = {
  ...productSummary({ id: 3, name: 'Claw Hammer', slug: 'claw-hammer', price: '450.00', mrp: '499.00', default_variant_id: 33, variant_count: 1 }),
  variant_id: 33,
  reason: 'Matches “claw hammer”',
  match_label: 'claw hammer',
  match_confidence: 0.91,
}

function result(overrides: Partial<ImageSearchResult> = {}): ImageSearchResult {
  return {
    id: null,
    status: 'identified',
    status_text: 'Identified',
    explanation: 'This looks like a claw hammer. We’re 91% sure.',
    identification: { label: 'claw hammer', confidence: 0.91, percent: 91, level: 'high', calibrated: true, description: '' },
    alternatives: [{ label: 'spanner', confidence: 0.04, percent: 4, search: 'spanner' }],
    search_query: 'hammer',
    notice: '',
    ai: { mode: 'vision', provider: 'clip', model: 'clip-ViT-L-14', calibrated: true },
    image: { format: 'JPEG', width: 800, height: 600 },
    products: [hammer],
    ...overrides,
  }
}

const jpeg = () => new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3])], 'hammer.jpg', { type: 'image/jpeg' })

describe('search by photo', () => {
  it('is reachable from the search bar', async () => {
    mockApi({ get: { ...shopGet, '/products/': page([]), '/ai/image-search/': status } })
    const { user, router } = renderRoute('/')
    await user.click(await screen.findByRole('link', { name: 'Search by photo' }))
    await waitFor(() => expect(currentUrl(router)).toBe('/image-search'))
    expect(await screen.findByRole('heading', { name: 'Search by photo', level: 1 })).toBeInTheDocument()
  })

  it('uploads a photo and shows what it is, how sure we are and real products to add to the cart', async () => {
    signIn()
    let sent: FormData | undefined
    const api = mockApi({
      get: { ...shopGet, '/auth/me/': customer, '/ai/image-search/': status, '/ai/image-searches/': page([]) },
      post: {
        '/ai/image-search/': ({ body }: RequestInfo) => {
          sent = body as FormData
          return result({ id: 12 })
        },
        '/cart/items/': ({ body }: RequestInfo) => cart({ items: [cartLine({ variant_id: (body as { variant_id: number }).variant_id })] }),
      },
    })
    const { user } = renderRoute('/image-search')
    const camera = await screen.findByLabelText('Take a photo', { selector: 'input' })
    expect(camera).toHaveAttribute('capture', 'environment') // opens the rear camera on phones
    await user.upload(screen.getByLabelText('Choose a photo', { selector: 'input' }), jpeg())

    expect(await screen.findByRole('heading', { name: 'Looks like: claw hammer' })).toBeInTheDocument()
    expect(sent?.get('image')).toBeInstanceOf(File)
    expect(screen.getByTestId('confidence')).toHaveTextContent('Very likely · 91%')
    expect(screen.getByRole('meter', { name: 'Confidence' })).toHaveAttribute('aria-valuenow', '91')
    expect(screen.getByText('This looks like a claw hammer. We’re 91% sure.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'spanner (4%)' })).toHaveAttribute('href', '/search?q=spanner')
    expect(screen.getByRole('link', { name: 'Search the shop for “hammer”' })).toHaveAttribute('href', '/search?q=hammer')

    const cards = within(screen.getByRole('list', { name: 'Matching products' }))
    expect(cards.getByRole('link', { name: 'Claw Hammer' })).toHaveAttribute('href', '/p/claw-hammer')
    expect(cards.getByText('Matches “claw hammer”')).toBeInTheDocument()
    await user.click(cards.getByRole('button', { name: /Add to cart/i }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/cart/items/', expect.objectContaining({ variant_id: 33 })))
  })

  it('says clearly when it is not sure, and calls the products possible matches', async () => {
    mockApi({
      get: { ...shopGet, '/ai/image-search/': status },
      post: {
        '/ai/image-search/': result({
          status: 'uncertain',
          status_text: 'Not sure',
          explanation: 'We’re not sure what this is. It might be: pipe wrench, hacksaw.',
          identification: { label: 'pipe wrench', confidence: 0.29, percent: 29, level: 'low', calibrated: true, description: '' },
          alternatives: [{ label: 'hacksaw', confidence: 0.12, percent: 12, search: 'hacksaw' }],
          products: [{ ...hammer, name: 'Adjustable Pipe Wrench', slug: 'pipe-wrench', reason: 'Possible match: pipe wrench (29%)' }],
        }),
      },
    })
    const { user } = renderRoute('/image-search')
    await user.upload(await screen.findByLabelText('Choose a photo', { selector: 'input' }), jpeg())
    expect(await screen.findByRole('heading', { name: 'We’re not sure what this is' })).toBeInTheDocument()
    expect(screen.getByTestId('confidence')).toHaveTextContent('Unsure · 29%')
    expect(screen.getByText(/we couldn’t be sure from the photo/)).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Possible matches' })).getByText('Possible match: pipe wrench (29%)')).toBeInTheDocument()
    expect(screen.getByText('Other possibilities:')).toBeInTheDocument()
  })

  it.each([
    ['no_match', 'Padlock isn’t in our catalogue', 'padlock'],
    ['not_hardware', 'This doesn’t look like a hardware item', null],
    ['unavailable', 'Photo search isn’t available right now', null],
  ] as const)('offers a word search when the outcome is %s', async (outcome, heading, label) => {
    mockApi({
      get: { ...shopGet, '/ai/image-search/': status },
      post: {
        '/ai/image-search/': result({
          status: outcome,
          explanation: 'explained',
          identification: label ? { label, confidence: 0.97, percent: 97, level: 'high', calibrated: true, description: '' } : null,
          alternatives: [],
          search_query: label ?? '',
          products: [],
        }),
      },
    })
    const { user, router } = renderRoute('/image-search')
    await user.upload(await screen.findByLabelText('Choose a photo', { selector: 'input' }), jpeg())
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: /matches|Matching/ })).not.toBeInTheDocument()
    expect(screen.queryByTestId('confidence')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Describe the item'), 'brass lock{Enter}')
    await waitFor(() => expect(currentUrl(router)).toBe('/search?q=brass%20lock'))
  })

  it('marks a model’s own estimate as such and shows its warning', async () => {
    mockApi({
      get: { ...shopGet, '/ai/image-search/': { ...status, provider: 'ollama', calibrated: false } },
      post: {
        '/ai/image-search/': result({
          identification: { label: 'claw hammer', confidence: 0.8, percent: 80, level: 'high', calibrated: false, description: 'A steel hammer.' },
          notice: 'Identified by an AI model, which can be wrong. Check the product details before you buy.',
        }),
      },
    })
    const { user } = renderRoute('/image-search')
    await user.upload(await screen.findByLabelText('Choose a photo', { selector: 'input' }), jpeg())
    expect(await screen.findByTestId('confidence')).toHaveTextContent('AI estimate · 80%')
    expect(screen.getByRole('note')).toHaveTextContent('can be wrong')
    expect(screen.getByText('A steel hammer.')).toBeInTheDocument()
  })

  it.each([
    [new File(['%PDF'], 'manual.pdf', { type: 'application/pdf' }), 'Choose a JPEG, PNG or WebP photo.'],
    [new File(['x'], 'IMG_0001.HEIC', { type: 'image/heic' }), /HEIC photos can’t be read here/],
    [new File([], 'empty.jpg', { type: 'image/jpeg' }), 'That file is empty.'],
  ])('checks the file in the browser first (%#)', async (file, message) => {
    const api = mockApi({ get: { ...shopGet, '/ai/image-search/': status } })
    renderRoute('/image-search')
    fireEvent.change(await screen.findByLabelText('Choose a photo', { selector: 'input' }), { target: { files: [file] } })
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(api.post).not.toHaveBeenCalled()
  })

  it('refuses a photo above the size limit without uploading it', async () => {
    const api = mockApi({ get: { ...shopGet, '/ai/image-search/': { ...status, max_bytes: 4 } } })
    const { user } = renderRoute('/image-search')
    await user.upload(await screen.findByLabelText('Choose a photo', { selector: 'input' }), jpeg())
    expect(await screen.findByRole('alert')).toHaveTextContent('That photo is too large')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('shows the server’s reason when it refuses the photo', async () => {
    mockApi({
      get: { ...shopGet, '/ai/image-search/': status },
      post: { '/ai/image-search/': httpError(400, 'That file is not a photo we can read.', 'image_invalid') },
    })
    const { user } = renderRoute('/image-search')
    await user.upload(await screen.findByLabelText('Choose a photo', { selector: 'input' }), jpeg())
    expect(await screen.findByRole('alert')).toHaveTextContent('That file is not a photo we can read.')
  })

  it('explains when photo search is switched off and offers the word search instead', async () => {
    mockApi({ get: { ...shopGet, '/ai/image-search/': { ...status, enabled: false, available: false, provider: 'none' } } })
    renderRoute('/image-search')
    expect(await screen.findByRole('heading', { name: 'Photo search isn’t switched on in this shop yet' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Take a photo' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Describe the item')).toBeInTheDocument()
  })

  it('signed-in customers can reopen and delete earlier photo searches', async () => {
    signIn()
    const row = { id: 12, title: 'Photo: claw hammer', status: 'identified', label: 'claw hammer', percent: 91, product_count: 1, created_at: '2026-10-01T10:00:00Z' }
    const api = mockApi({
      get: {
        ...shopGet,
        '/auth/me/': customer,
        '/ai/image-search/': status,
        '/ai/image-searches/': page([row]),
        '/ai/image-searches/12/': result({ id: 12 }),
      },
      delete: { '/ai/image-searches/12/': {} },
      post: { '/ai/image-searches/clear/': {} },
    })
    const { user, router } = renderRoute('/image-search')
    const history = within(await screen.findByRole('region', { name: 'Your recent photo searches' }))
    await user.click(history.getByRole('button', { name: /Claw hammer/ }))
    await waitFor(() => expect(currentUrl(router)).toBe('/image-search?id=12'))
    expect(await screen.findByRole('heading', { name: 'Looks like: claw hammer' })).toBeInTheDocument()
    await user.click(history.getByRole('button', { name: 'Delete photo search claw hammer' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/ai/image-searches/12/'))
    await user.click(history.getByRole('button', { name: 'Clear all' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ai/image-searches/clear/', {}))
  })

  it('visitors are invited to sign in for a history and nothing private is requested', async () => {
    const api = mockApi({ get: { ...shopGet, '/ai/image-search/': status } })
    renderRoute('/image-search')
    expect(await screen.findByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login?next=%2Fimage-search')
    expect(api.get.mock.calls.map(([url]) => url)).not.toContain('/ai/image-searches/')
  })
})
