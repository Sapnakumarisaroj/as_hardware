import '@testing-library/jest-dom/vitest'

import { cleanup, configure } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

import { tokenStore } from '@/lib/api/tokens'

// Checkout/account routes are lazy-loaded; the first dynamic import can exceed the 1 s default
// (and 5 s when every test file starts at once on a busy machine).
configure({ asyncUtilTimeout: 10_000 })

// jsdom does not implement scrolling.
window.scrollTo = vi.fn() as unknown as typeof window.scrollTo

// ...nor element sizes, which the dashboard charts observe. Charts render empty in tests; the
// numbers are checked in the table each chart comes with.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  tokenStore.clear()
  window.sessionStorage.clear()
  window.localStorage.clear()
})
