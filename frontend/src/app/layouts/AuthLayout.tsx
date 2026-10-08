import { useEffect } from 'react'
import { Link, Outlet, useLocation } from 'react-router'

import { env } from '@/lib/env'

/**
 * A focused shell for login, register and password reset: the brand, the form and a way back to the
 * shop. No storefront header, navigation or search.
 */
export function AuthLayout() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])

  return (
    <div className="flex min-h-dvh flex-col bg-steel-50 bg-[radial-gradient(ellipse_at_top,_var(--color-amber-100),_transparent_55%)]">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-4 py-5 sm:px-6">
        <Link to="/" className="flex items-center gap-2 text-lg font-extrabold tracking-tight text-ink-950">
          <img src="/favicon.svg" alt="" className="size-8" />
          <span>{env.appName}</span>
        </Link>
        <Link to="/" className="text-sm font-semibold text-ink-600 hover:text-ink-950">
          ← Back to the shop
        </Link>
      </header>
      <main id="main" className="flex flex-1 items-start justify-center px-4 pb-12 pt-4 sm:items-center sm:pt-0">
        <Outlet />
      </main>
      <footer className="pb-6 text-center text-xs text-ink-600">
        Secure sign-in · Your password is never shown to anyone, including us.
      </footer>
    </div>
  )
}
