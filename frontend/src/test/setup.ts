import '@testing-library/jest-dom/vitest'

import { cleanup, configure } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

import { tokenStore } from '@/lib/api/tokens'

// Checkout/account routes are lazy-loaded; the first dynamic import can exceed the 1 s default
// (and 5 s when every test file starts at once on a busy machine).
configure({ asyncUtilTimeout: 10_000 })

// jsdom does not implement scrolling.
window.scrollTo = vi.fn() as unknown as typeof window.scrollTo

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  tokenStore.clear()
  window.sessionStorage.clear()
  window.localStorage.clear()
})
