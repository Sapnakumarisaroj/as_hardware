import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router'

import { Footer } from './Footer'
import { Header } from './Header'

export function CustomerLayout() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0) // new page starts at the top (query-string changes keep position)
  }, [pathname])

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <Header />
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <Footer />
    </div>
  )
}
