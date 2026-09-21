import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api/client'
import { ApiError } from '@/lib/api/errors'
import { renderRoute } from '@/test/utils'

afterEach(() => vi.restoreAllMocks())

describe('app routes', () => {
  it('home shows live service status from the health API', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: { status: 'ok', app: 'BoltRun', version: '0.1.0', database: 'ok' },
    })
    renderRoute('/')
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument()
    expect(await screen.findByText(/All systems operational · v0\.1\.0/)).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/health/')
  })

  it('home shows an error state with retry when the API is unreachable', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(
      new ApiError({ message: 'Cannot reach the server.', code: 'network_error', status: null }),
    )
    renderRoute('/')
    expect(await screen.findByText('Service unreachable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled()
  })

  it('unknown paths render the 404 page', () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: {} })
    renderRoute('/definitely-not-a-page')
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
