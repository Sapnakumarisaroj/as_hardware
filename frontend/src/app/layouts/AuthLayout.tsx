import { useEffect } from 'react'
import { Link, Outlet, useLocation } from 'react-router'

import { BrandLogo } from '@/components/BrandLogo'
import { business } from '@/lib/business'

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
    <div className="flex min-h-dvh flex-col bg-steel-50">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-4 py-5 sm:px-6">
        <Link
          to="/"
          aria-label={`${business.name} home`}
          className="flex min-w-0 items-center gap-2.5 font-extrabold tracking-tight text-ink-950"
        >
          <BrandLogo size="h-12 sm:h-14" />
        </Link>
        <Link to="/" className="shrink-0 text-sm font-semibold text-ink-600 hover:text-ink-950">
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
