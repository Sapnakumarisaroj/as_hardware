import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { Drawer } from '@/components/Drawer'
import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { useAdminSession, useSummary } from '@/features/admin/api'
import type { AdminSession, Section } from '@/features/admin/types'
import { useAuth } from '@/features/auth/context'
import { env } from '@/lib/env'

const MENU: { title: string; items: [Section, string, string][] }[] = [
  { title: 'Overview', items: [['dashboard', 'Dashboard', '/admin'], ['analytics', 'Analytics', '/admin/analytics']] },
  {
    title: 'Sales',
    items: [
      ['orders', 'Orders', '/admin/orders'],
      ['returns', 'Returns', '/admin/returns'],
      ['refunds', 'Refunds', '/admin/refunds'],
      ['customers', 'Customers', '/admin/customers'],
      ['support', 'Support', '/admin/support'],
    ],
  },
  {
    title: 'Catalogue',
    items: [
      ['products', 'Products', '/admin/products'],
      ['categories', 'Categories', '/admin/categories'],
      ['brands', 'Brands', '/admin/brands'],
      ['options', 'Product options', '/admin/options'],
      ['collections', 'Curated lists', '/admin/collections'],
      ['search', 'Search', '/admin/search'],
    ],
  },
  {
    title: 'Pricing',
    items: [
      ['offers', 'Offers', '/admin/offers'],
      ['coupons', 'Coupons', '/admin/coupons'],
      ['free-delivery', 'Free delivery', '/admin/free-delivery'],
      ['payment-settings', 'Cash on delivery', '/admin/payment-settings'],
    ],
  },
  {
    title: 'Operations',
    items: [
      ['inventory', 'Inventory', '/admin/inventory'],
      ['delivery', 'Delivery', '/admin/delivery'],
      ['stores', 'Stores', '/admin/stores'],
      ['warehouses', 'Warehouses', '/admin/warehouses'],
    ],
  },
]

function Menu({ session, onNavigate }: { session: AdminSession; onNavigate?: () => void }) {
  return (
    <nav aria-label="Admin sections" className="space-y-4">
      {MENU.map((group) => {
        const items = group.items.filter(([section]) => session.sections.includes(section))
        if (items.length === 0) return null
        return (
          <div key={group.title}>
            <p className="px-3 text-xs font-semibold uppercase tracking-wide text-steel-400">{group.title}</p>
            <ul className="mt-1 space-y-0.5">
              {items.map(([section, label, to]) => (
                <li key={section}>
                  <NavLink
                    to={to}
                    end={to === '/admin'}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      `block rounded-md px-3 py-2 text-sm font-medium ${isActive ? 'bg-amber-500 text-ink-950' : 'text-steel-100 hover:bg-ink-800'}`
                    }
                  >
                    {label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </nav>
  )
}

/** Things waiting for someone, from the same live numbers as the dashboard. */
function Notifications() {
  const summary = useSummary()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const items = summary.data?.attention ?? []
  const total = items.reduce((sum, item) => sum + item.count, 0)

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    const onClick = (event: MouseEvent) => !box.current?.contains(event.target as Node) && setOpen(false)
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="admin-notifications"
        onClick={() => setOpen((value) => !value)}
        className="relative rounded-md px-3 py-2 text-sm font-semibold hover:bg-steel-100"
      >
        To do
        <span className="sr-only">: {total === 0 ? 'nothing waiting' : `${total} waiting`}</span>
        {total > 0 && (
          <span aria-hidden className="ml-1.5 rounded-full bg-danger-600 px-1.5 py-0.5 text-xs font-bold text-white">
            {total > 99 ? '99+' : total}
          </span>
        )}
      </button>
      {open && (
        <div
          id="admin-notifications"
          className="absolute right-0 z-40 mt-1 w-80 max-w-[90vw] rounded-lg bg-white p-2 text-sm shadow-xl ring-1 ring-steel-200"
        >
          {items.length === 0 ? (
            <p className="px-3 py-4 text-center text-ink-600">Nothing is waiting. All caught up.</p>
          ) : (
            <ul>
              {items.map((item) => (
                <li key={item.code}>
                  <Link
                    to={item.link}
                    onClick={() => setOpen(false)}
                    className="flex items-center justify-between gap-3 rounded-md px-3 py-2 hover:bg-steel-50"
                  >
                    <span>{item.label}</span>
                    <span className="font-bold tabular-nums">{item.count}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

/** Jumps to the order search; order numbers, customers and products are all found there. */
function QuickSearch() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  function submit(event: FormEvent) {
    event.preventDefault()
    const term = text.trim()
    if (!term) return
    void navigate(`/admin/orders?q=${encodeURIComponent(term)}`)
    setText('')
  }
  return (
    <form role="search" onSubmit={submit} className="hidden min-w-0 flex-1 sm:block sm:max-w-sm">
      <label htmlFor="admin-quick-search" className="sr-only">
        Find an order
      </label>
      <input
        id="admin-quick-search"
        type="search"
        className="input"
        placeholder="Find an order: number, customer, phone…"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
    </form>
  )
}

function Frame({ session }: { session: AdminSession }) {
  const { logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const brand = (
    <Link to="/admin" className="flex items-center gap-2 font-extrabold tracking-tight text-white">
      <img src="/favicon.svg" alt="" className="size-7" />
      <span>
        {env.appName} <span className="font-normal text-steel-200">Admin</span>
      </span>
    </Link>
  )

  return (
    <div className="min-h-dvh bg-steel-50 lg:pl-60">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col overflow-y-auto bg-ink-900 lg:flex">
        <div className="flex h-14 shrink-0 items-center px-4">{brand}</div>
        <div className="flex-1 px-2 py-3">
          <Menu session={session} />
        </div>
        <Link to="/" className="m-3 rounded-md px-3 py-2 text-sm text-steel-200 hover:bg-ink-800">
          ← Back to the shop
        </Link>
      </aside>

      <Drawer open={menuOpen} onClose={() => setMenuOpen(false)} title="Menu">
        <div className="-mx-4 -my-4 min-h-full bg-ink-900 px-2 py-4">
          <Menu session={session} onNavigate={() => setMenuOpen(false)} />
          <Link to="/" className="mt-4 block rounded-md px-3 py-2 text-sm text-steel-200 hover:bg-ink-800">
            ← Back to the shop
          </Link>
        </div>
      </Drawer>

      <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-steel-200 bg-white px-3 sm:px-5">
        <button
          type="button"
          className="rounded-md px-3 py-2 text-sm font-semibold ring-1 ring-steel-200 lg:hidden"
          onClick={() => setMenuOpen(true)}
          aria-haspopup="dialog"
        >
          Menu
        </button>
        <QuickSearch />
        <div className="ml-auto flex items-center gap-1">
          <Notifications />
          <div className="hidden text-right text-xs leading-tight sm:block">
            <p className="font-semibold">{session.user.full_name || session.user.email}</p>
            <p className="text-ink-600">
              {session.is_admin ? 'Administrator' : `Store manager · ${session.stores.map((s) => s.name).join(', ') || 'no store yet'}`}
            </p>
          </div>
          <button type="button" onClick={() => void logout()} className="rounded-md px-3 py-2 text-sm font-semibold hover:bg-steel-100">
            Logout
          </button>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-[1400px] px-3 py-5 sm:px-5">
        <Outlet context={session} />
      </main>
    </div>
  )
}

function Message({ children }: { children: React.ReactNode }) {
  return <div className="container-page py-10">{children}</div>
}

/**
 * The business dashboard shell. It shows the sections the signed-in role may use; the API checks
 * the role and the store on every request, so hiding a link is a convenience, never the protection.
 */
export function AdminLayout() {
  const { pathname, search } = useLocation()
  const { status, user } = useAuth()
  const staff = user?.role === 'admin' || user?.role === 'store_manager'
  const session = useAdminSession()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])

  if (status === 'loading') return <PageSpinner />
  if (!user) {
    return (
      <Message>
        <SignInPrompt message="Sign in with your staff account to open the dashboard." next={pathname + search} />
      </Message>
    )
  }
  if (!staff) {
    const rider = user.role === 'delivery_partner'
    return (
      <Message>
        <EmptyState
          title="For store staff only"
          action={
            <Link to={rider ? '/rider' : '/'} className="btn-primary">
              {rider ? 'Go to the rider app' : 'Go to the shop'}
            </Link>
          }
        >
          This account can’t open the business dashboard.
        </EmptyState>
      </Message>
    )
  }
  if (session.isPending) return <PageSpinner label="Opening the dashboard…" />
  if (session.isError) {
    return (
      <Message>
        <ErrorState error={session.error} onRetry={() => void session.refetch()} title="Couldn’t open the dashboard" />
      </Message>
    )
  }
  return <Frame session={session.data} />
}
