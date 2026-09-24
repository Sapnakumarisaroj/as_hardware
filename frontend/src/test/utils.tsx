import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'

import { routes } from '@/app/routes'
import { tokenStore } from '@/lib/api/tokens'

/** Renders the real route table (layout, header, providers) at `path`. */
export function renderRoute(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const user = userEvent.setup()
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { ...view, router, user, client }
}

/** Starts a session; mock GET /auth/me/ to decide who is signed in. */
export function signIn() {
  tokenStore.set({ access: 'test-access', refresh: 'test-refresh' })
}

export function currentUrl(router: ReturnType<typeof renderRoute>['router']): string {
  const { pathname, search } = router.state.location
  return pathname + search
}
