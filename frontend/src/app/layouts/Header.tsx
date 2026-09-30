import { useRef, useState } from 'react'
import { Link, NavLink, useLocation, useSearchParams } from 'react-router'

import { Drawer } from '@/components/Drawer'
import { CartIcon, ChevronDownIcon, HeartIcon, MenuIcon, SparkIcon, UserIcon } from '@/components/icons'
import { useAuth } from '@/features/auth/context'
import { useCartCount } from '@/features/cart/api'
import { useCategories } from '@/features/catalog/api'
import { LocationSelector } from '@/features/location/LocationSelector'
import { SearchBar } from '@/features/search/SearchBar'
import { useWishlistIds } from '@/features/wishlist/api'
import { env } from '@/lib/env'

function CountBadge({ count, label }: { count: number; label: string }) {
  if (!count) return null
  return (
    <span className="absolute -right-1.5 -top-1.5 grid min-w-5 place-items-center rounded-full bg-amber-500 px-1 text-[11px] font-bold leading-5 text-ink-950">
      {count > 99 ? '99+' : count}
      <span className="sr-only"> {label}</span>
    </span>
  )
}

function Logo() {
  return (
    <Link to="/" className="flex shrink-0 items-center gap-2 text-lg font-extrabold tracking-tight">
      <img src="/favicon.svg" alt="" className="size-8" />
      <span>{env.appName}</span>
    </Link>
  )
}

function AccountMenu() {
  const { status, user, logout } = useAuth()
  const detailsRef = useRef<HTMLDetailsElement>(null)
  const close = () => detailsRef.current?.removeAttribute('open')

  if (status === 'loading') {
    return <span className="h-8 w-20 animate-pulse rounded bg-ink-800" aria-label="Loading account" />
  }
  if (status !== 'authenticated' || !user) {
    return (
      <Link to="/login" className="flex items-center gap-1.5 text-sm font-semibold hover:text-amber-500">
        <UserIcon className="size-5" />
        <span className="hidden sm:inline">Login / Register</span>
        <span className="sm:hidden">Login</span>
      </Link>
    )
  }
  const firstName = user.full_name.split(' ')[0] || 'Account'
  return (
    <details ref={detailsRef} className="relative">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold hover:text-amber-500 [&::-webkit-details-marker]:hidden">
        <UserIcon className="size-5" />
        <span className="hidden max-w-28 truncate sm:inline">{firstName}</span>
        <ChevronDownIcon className="size-3.5" />
        <span className="sr-only">Account menu</span>
      </summary>
      <div className="absolute right-0 top-full z-40 mt-2 w-52 rounded-lg bg-white py-1 text-sm text-ink-900 shadow-lg ring-1 ring-steel-200">
        <p className="truncate border-b border-steel-100 px-4 py-2 text-xs text-ink-600">{user.email}</p>
        {user.role === 'delivery_partner' && (
          <Link to="/rider" onClick={close} className="block px-4 py-2 font-semibold hover:bg-steel-50">
            Rider app
          </Link>
        )}
        {(user.role === 'admin' || user.role === 'store_manager') && (
          <Link to="/admin" onClick={close} className="block px-4 py-2 font-semibold hover:bg-steel-50">
            Business dashboard
          </Link>
        )}
        <Link to="/account" onClick={close} className="block px-4 py-2 hover:bg-steel-50">
          My account
        </Link>
        <Link to="/account/orders" onClick={close} className="block px-4 py-2 hover:bg-steel-50">
          Orders
        </Link>
        <Link to="/wishlist" onClick={close} className="block px-4 py-2 hover:bg-steel-50">
          Wishlist
        </Link>
        <button
          type="button"
          onClick={() => {
            close()
            void logout()
          }}
          className="block w-full px-4 py-2 text-left hover:bg-steel-50"
        >
          Logout
        </button>
      </div>
    </details>
  )
}

function CategoryNav() {
  const categories = useCategories()
  if (!categories.data?.length) return <div className="hidden h-10 bg-ink-800 md:block" />
  return (
    <nav aria-label="Product categories" className="hidden bg-ink-800 md:block">
      <ul className="container-page flex h-10 items-center gap-1 text-sm">
        <li>
          <NavLink to="/products" className="rounded px-3 py-2 font-semibold hover:text-amber-500">
            All products
          </NavLink>
        </li>
        {categories.data.map((category) => (
          <li key={category.id} className="group relative">
            <NavLink
              to={`/c/${category.slug}`}
              className={({ isActive }) =>
                `flex items-center gap-1 rounded px-3 py-2 hover:text-amber-500 ${isActive ? 'text-amber-500' : ''}`
              }
            >
              {category.name}
              {category.children.length > 0 && <ChevronDownIcon className="size-3" />}
            </NavLink>
            {category.children.length > 0 && (
              <div className="invisible absolute left-0 top-full z-40 w-64 rounded-b-lg bg-white py-2 text-ink-900 opacity-0 shadow-lg ring-1 ring-steel-200 transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100">
                {category.children.map((child) => (
                  <Link
                    key={child.id}
                    to={`/c/${child.slug}`}
                    className="flex justify-between px-4 py-1.5 hover:bg-steel-50 hover:text-amber-600"
                  >
                    <span>{child.name}</span>
                    {child.product_count !== null && <span className="text-xs text-ink-600">{child.product_count}</span>}
                  </Link>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </nav>
  )
}

function MobileMenu({ open, onClose }: { open: boolean; onClose: () => void }) {
  const categories = useCategories()
  const { status, logout } = useAuth()
  const link = 'block rounded px-2 py-2 text-sm hover:bg-steel-50'
  return (
    <Drawer open={open} onClose={onClose} title="Menu">
      <nav aria-label="Mobile menu" className="space-y-4">
        <div className="rounded-md bg-steel-50 p-3">
          <LocationSelector tone="light" />
        </div>
        <div>
          <h3 className="px-2 text-xs font-bold uppercase tracking-wide text-ink-600">Shop by category</h3>
          <Link to="/products" onClick={onClose} className={link}>
            All products
          </Link>
          {categories.data?.map((category) => (
            <details key={category.id} className="group">
              <summary className="flex cursor-pointer list-none items-center justify-between rounded px-2 py-2 text-sm font-semibold hover:bg-steel-50">
                {category.name}
                <ChevronDownIcon className="size-4 transition group-open:rotate-180" />
              </summary>
              <div className="ml-3 border-l border-steel-200 pl-2">
                <Link to={`/c/${category.slug}`} onClick={onClose} className={link}>
                  All {category.name}
                </Link>
                {category.children.map((child) => (
                  <Link key={child.id} to={`/c/${child.slug}`} onClick={onClose} className={link}>
                    {child.name}
                  </Link>
                ))}
              </div>
            </details>
          ))}
        </div>
        <div className="border-t border-steel-200 pt-3">
          <h3 className="px-2 text-xs font-bold uppercase tracking-wide text-ink-600">Your account</h3>
          {status === 'authenticated' ? (
            <>
              <Link to="/account" onClick={onClose} className={link}>
                My account
              </Link>
              <Link to="/account/orders" onClick={onClose} className={link}>
                Orders
              </Link>
              <Link to="/wishlist" onClick={onClose} className={link}>
                Wishlist
              </Link>
              <button
                type="button"
                onClick={() => {
                  onClose()
                  void logout()
                }}
                className={`${link} w-full text-left`}
              >
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login" onClick={onClose} className={link}>
                Login
              </Link>
              <Link to="/register" onClick={onClose} className={link}>
                Create an account
              </Link>
            </>
          )}
        </div>
      </nav>
    </Drawer>
  )
}

export function Header() {
  const [menuOpen, setMenuOpen] = useState(false)
  const cartCount = useCartCount()
  const wishlistCount = useWishlistIds().size
  const location = useLocation()
  const [params] = useSearchParams()
  const urlQuery = location.pathname === '/search' ? (params.get('q') ?? '') : ''

  const aiButton = (
    <Link
      to="/ai-assistant"
      className="hidden shrink-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-steel-200 ring-1 ring-ink-600 hover:text-amber-500 lg:flex"
    >
      <SparkIcon className="size-4" />
      Ask AI
    </Link>
  )

  return (
    <header className="sticky top-0 z-30 bg-ink-900 text-white shadow">
      {/* One row on desktop; on mobile the search box wraps onto its own full-width row. */}
      <div className="container-page flex flex-wrap items-center gap-x-3 gap-y-2 py-3 sm:gap-x-4 md:h-16 md:flex-nowrap md:py-0">
        <button type="button" onClick={() => setMenuOpen(true)} className="-ml-1 p-1 md:hidden" aria-label="Open menu">
          <MenuIcon className="size-6" />
        </button>
        <Logo />
        <div className="hidden md:block">
          <LocationSelector />
        </div>
        <div className="order-last w-full md:order-none md:w-auto md:flex-1">
          <SearchBar key={urlQuery} initialQuery={urlQuery} />
        </div>
        {aiButton}
        <div className="ml-auto flex items-center gap-4 sm:gap-5 md:ml-0">
          <Link to="/wishlist" className="relative hidden hover:text-amber-500 sm:block" aria-label="Wishlist">
            <HeartIcon className="size-6" />
            <CountBadge count={wishlistCount} label="saved items" />
          </Link>
          <Link to="/cart" className="relative hover:text-amber-500" aria-label="Cart">
            <CartIcon className="size-6" />
            <CountBadge count={cartCount} label="items in cart" />
          </Link>
          <AccountMenu />
        </div>
      </div>
      <CategoryNav />
      <MobileMenu open={menuOpen} onClose={() => setMenuOpen(false)} />
    </header>
  )
}
