import { Link, Outlet } from 'react-router'

import { env } from '@/lib/env'

export function CustomerLayout() {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="bg-ink-900 text-white">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
          <Link to="/" className="flex items-center gap-2 text-lg font-bold tracking-tight">
            <img src="/favicon.svg" alt="" className="size-7" />
            {env.appName}
          </Link>
        </div>
      </header>
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <footer className="border-t border-steel-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-6 text-sm text-ink-600">
          © {new Date().getFullYear()} {env.appName}
        </div>
      </footer>
    </div>
  )
}
