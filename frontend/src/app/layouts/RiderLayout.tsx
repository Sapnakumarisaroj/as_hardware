import { useEffect } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'

import { BrandLogo } from '@/components/BrandLogo'
import { useAuth } from '@/features/auth/context'
import { NotificationBell } from '@/features/notifications/NotificationBell'

/** A plain shell for delivery partners: large targets, no shop navigation to get lost in. */
export function RiderLayout() {
  const { pathname } = useLocation()
  const { status, logout } = useAuth()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded px-2 py-2 text-sm font-semibold hover:text-amber-500 ${isActive ? 'text-amber-500' : ''}`

  return (
    <div className="flex min-h-dvh flex-col bg-steel-50">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 bg-ink-900 text-white shadow">
        <div className="container-page flex h-14 max-w-3xl items-center gap-3">
          <Link to="/rider" className="flex items-center gap-2 font-extrabold tracking-tight">
            <BrandLogo size="size-8" suffix="Rider" short />
          </Link>
          <nav aria-label="Rider app" className="ml-auto flex items-center gap-1">
            <NavLink to="/rider" end className={link}>
              Jobs
            </NavLink>
            <NavLink to="/rider/history" className={link}>
              History
            </NavLink>
            {status === 'authenticated' && <NotificationBell className="mx-2" />}
            {status === 'authenticated' && (
              <button type="button" onClick={() => void logout()} className="rounded px-2 py-2 text-sm font-semibold hover:text-amber-500">
                Logout
              </button>
            )}
          </nav>
        </div>
      </header>
      <main id="main" className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
