import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useSearchParams } from 'react-router'

import { Drawer } from '@/components/Drawer'
import {
  CameraIcon,
  CartIcon,
  ChevronDownIcon,
  HeartIcon,
  ImageIcon,
  MenuIcon,
  MicIcon,
  SparkIcon,
  UserIcon,
} from '@/components/icons'
import { useAuth } from '@/features/auth/context'
import { useCartCount } from '@/features/cart/api'
import { useCategories } from '@/features/catalog/api'
import type { Category } from '@/features/catalog/types'
import { LocationSelector } from '@/features/location/LocationSelector'
import { NotificationBell } from '@/features/notifications/NotificationBell'
import { SearchBar } from '@/features/search/SearchBar'
import { useWishlistIds } from '@/features/wishlist/api'
import { env } from '@/lib/env'

/** Compact menu label (from the API), the full name otherwise. */
const shortName = (c: { name: string; short_name?: string }) => c.short_name || c.name

const ACCOUNT_LINKS: [string, string][] = [
  ['My account', '/account'],
  ['Orders', '/account/orders'],
  ['Wishlist', '/wishlist'],
  ['Wallet', '/account/wallet'],
  ['Notifications', '/notifications'],
]

const TOOL_LINKS: [string, string, string][] = [
  ['Quantity calculator', '/quantity', 'How many screws, plugs and more you need'],
  ['Project builder', '/projects', 'A priced kit for your job'],
  ['Compatibility check', '/ai-assistant', 'Ask whether two parts work together'],
  ['Smart cart', '/cart', 'Tips, bulk prices and missing parts'],
  ['Kits & bundles', '/bundles', 'Ready-made kits of real products'],
  ['Shop within a budget', '/budget', 'A kit that fits your budget'],
]

const AI_LINKS: [string, string, string, ReactNode][] = [
  ['AI assistant', '/ai-assistant', 'Ask in English, Hindi or Hinglish', <SparkIcon key="s" className="size-4" />],
  ['Smart search', '/products', 'Search understands sizes, uses and Hindi words', <SparkIcon key="q" className="size-4" />],
  ['Search with a photo', '/image-search', 'Take a photo of a part to find it', <CameraIcon key="c" className="size-4" />],
  ['Shop by voice', '/voice', 'Say what you need and the quantity', <MicIcon key="m" className="size-4" />],
]

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

function CategoryThumb({ category, size = 'size-10' }: { category: { name: string; cover_image?: string | null }; size?: string }) {
  return category.cover_image ? (
    <img src={category.cover_image} alt="" loading="lazy" className={`${size} shrink-0 rounded-md bg-steel-100 object-cover`} />
  ) : (
    <span aria-hidden className={`${size} grid shrink-0 place-items-center rounded-md bg-steel-100 text-steel-400`}>
      <ImageIcon className="size-5" />
    </span>
  )
}

function AccountMenu() {
  const { status, user, logout } = useAuth()
  const detailsRef = useRef<HTMLDetailsElement>(null)
  const close = () => detailsRef.current?.removeAttribute('open')

  if (status === 'loading') {
    return <span className="h-8 w-9 animate-pulse rounded bg-ink-800 sm:w-20" aria-label="Loading account" />
  }
  if (status !== 'authenticated' || !user) {
    return (
      <Link
        to="/login"
        aria-label="Login / Register"
        className="flex items-center gap-1.5 whitespace-nowrap rounded-md px-1.5 py-1.5 text-sm font-semibold hover:text-amber-500"
      >
        <UserIcon className="size-5 shrink-0" />
        <span className="hidden xl:inline">Login / Register</span>
        <span className="hidden sm:inline xl:hidden">Login</span>
      </Link>
    )
  }
  const firstName = user.full_name.split(' ')[0] || 'Account'
  const item = 'block px-4 py-2 hover:bg-steel-50'
  return (
    <details ref={detailsRef} className="relative">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-md px-1.5 py-1.5 text-sm font-semibold hover:text-amber-500 [&::-webkit-details-marker]:hidden">
        <UserIcon className="size-5 shrink-0" />
        <span className="hidden max-w-28 truncate xl:inline">{firstName}</span>
        <ChevronDownIcon className="hidden size-3.5 sm:block" />
        <span className="sr-only">Account menu</span>
      </summary>
      <div className="absolute right-0 top-full z-40 mt-2 w-56 rounded-xl bg-white py-1 text-sm text-ink-900 shadow-lg ring-1 ring-steel-200">
        <p className="truncate border-b border-steel-100 px-4 py-2 text-xs text-ink-600">{user.email}</p>
        {user.role === 'delivery_partner' && (
          <Link to="/rider" onClick={close} className={`${item} font-semibold`}>
            Rider app
          </Link>
        )}
        {(user.role === 'admin' || user.role === 'store_manager') && (
          <Link to="/admin" onClick={close} className={`${item} font-semibold`}>
            Business dashboard
          </Link>
        )}
        {ACCOUNT_LINKS.map(([label, to]) => (
          <Link key={to} to={to} onClick={close} className={item}>
            {label}
          </Link>
        ))}
        <button
          type="button"
          onClick={() => {
            close()
            void logout()
          }}
          className={`${item} w-full text-left`}
        >
          Logout
        </button>
      </div>
    </details>
  )
}

/** A top-level menu with a dropdown: opens on hover, click or keyboard; Escape or a click outside closes it. */
function NavMenu({ label, children, panelClass }: { label: string; children: ReactNode; panelClass: string }) {
  const [open, setOpen] = useState(false)
  // Pointing at the menu opens it; the click that usually follows must not close it again.
  const hoverOpenedAt = useRef(0)
  const box = useRef<HTMLLIElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const id = useId()
  const { pathname, search } = useLocation()
  // Close after navigating (reset during render, as elsewhere in the app, instead of in an effect).
  const route = pathname + search
  const [seenRoute, setSeenRoute] = useState(route)
  if (seenRoute !== route) {
    setSeenRoute(route)
    setOpen(false)
  }
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    const onClick = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false)
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  return (
    <li
      ref={box}
      className="static"
      onMouseEnter={() => {
        if (!open) hoverOpenedAt.current = Date.now()
        setOpen(true)
      }}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => (v && Date.now() - hoverOpenedAt.current < 400 ? true : !v))}
        className={`flex items-center gap-1 whitespace-nowrap rounded-md px-3 py-2 text-sm font-semibold hover:text-amber-500 ${open ? 'text-amber-500' : ''}`}
      >
        {label}
        <ChevronDownIcon className={`size-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div id={id} className={`absolute top-full z-40 pt-1 ${panelClass}`}>
          <div className="rounded-xl bg-white p-4 text-ink-900 shadow-xl ring-1 ring-steel-200">{children}</div>
        </div>
      )}
    </li>
  )
}

function ShopPanel({ categories }: { categories: Category[] }) {
  return (
    <nav aria-label="Product categories">
      <ul className="grid grid-cols-2 gap-x-6 gap-y-4 xl:grid-cols-5">
        {categories.map((category) => (
          <li key={category.id} className="min-w-0">
            <Link to={`/c/${category.slug}`} className="group flex items-center gap-2.5" title={category.name}>
              <CategoryThumb category={category} />
              <span className="min-w-0">
                <span className="block truncate text-sm font-bold group-hover:text-amber-600">{shortName(category)}</span>
                {category.product_count !== null && category.product_count !== undefined && (
                  <span className="block text-xs text-ink-600">{category.product_count} products</span>
                )}
              </span>
            </Link>
            {category.children.length > 0 && (
              <ul className="mt-1.5 space-y-0.5 pl-[50px]">
                {category.children
                  .filter((child) => child.product_count !== 0)
                  .slice(0, 4)
                  .map((child) => (
                    <li key={child.id}>
                      <Link to={`/c/${child.slug}`} className="block truncate text-xs text-ink-600 hover:text-amber-600">
                        {child.name}
                      </Link>
                    </li>
                  ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 border-t border-steel-100 pt-3 text-sm font-semibold">
        <Link to="/products" className="text-amber-600 hover:underline">
          All products
        </Link>
        <Link to="/brands" className="text-amber-600 hover:underline">
          Shop by brand
        </Link>
      </div>
    </nav>
  )
}

function LinkList({ links }: { links: [string, string, string, ReactNode?][] }) {
  return (
    <ul className="space-y-1">
      {links.map(([label, to, hint, icon]) => (
        <li key={label}>
          <Link to={to} className="flex items-start gap-2.5 rounded-lg px-2 py-2 hover:bg-steel-50">
            {icon && <span className="mt-0.5 text-amber-600">{icon}</span>}
            <span>
              <span className="block text-sm font-semibold">{label}</span>
              <span className="block text-xs text-ink-600">{hint}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

function DesktopNav({ categories }: { categories: Category[] }) {
  const { status } = useAuth()
  const link = ({ isActive }: { isActive: boolean }) =>
    `block whitespace-nowrap rounded-md px-3 py-2 text-sm font-semibold hover:text-amber-500 ${isActive ? 'text-amber-500' : ''}`
  return (
    <div className="hidden border-t border-ink-800 bg-ink-900 lg:block">
      <div className="container-page relative flex h-11 items-center justify-between gap-4">
        <nav aria-label="Main">
          <ul className="flex items-center gap-0.5">
            <li>
              <NavLink to="/" end className={link}>
                Home
              </NavLink>
            </li>
            <NavMenu label="Shop" panelClass="left-0 right-0">
              <ShopPanel categories={categories} />
            </NavMenu>
            <li>
              <Link to="/products?ordering=discount" className={link({ isActive: false })}>
                Deals
              </Link>
            </li>
            <li>
              <Link to="/products?ordering=newest" className={link({ isActive: false })}>
                New
              </Link>
            </li>
            <li>
              <NavLink to="/brands" className={link}>
                Brands
              </NavLink>
            </li>
            <NavMenu label="Tools" panelClass="w-80">
              <LinkList links={TOOL_LINKS} />
            </NavMenu>
            <NavMenu label="AI" panelClass="w-80">
              <LinkList links={AI_LINKS} />
            </NavMenu>
            <li>
              <NavLink to={status === 'authenticated' ? '/account/orders' : '/login?next=%2Faccount%2Forders'} className={link}>
                Orders
              </NavLink>
            </li>
          </ul>
        </nav>
        <div className="shrink-0">
          <LocationSelector />
        </div>
      </div>
    </div>
  )
}

function MobileMenu({ open, onClose, categories }: { open: boolean; onClose: () => void; categories: Category[] }) {
  const { status, logout } = useAuth()
  const link = 'flex items-center gap-2 rounded-md px-2 py-2 text-sm hover:bg-steel-50'
  const heading = 'px-2 text-xs font-bold uppercase tracking-wide text-ink-600'
  return (
    <Drawer open={open} onClose={onClose} title="Menu">
      <nav aria-label="Mobile menu" className="space-y-5">
        <div className="rounded-lg bg-steel-50 p-3">
          <LocationSelector tone="light" />
        </div>
        <div>
          <h3 className={heading}>Shop by category</h3>
          <ul className="mt-1">
            {categories.map((category) => (
              <li key={category.id}>
                <Link to={`/c/${category.slug}`} onClick={onClose} className={link}>
                  <CategoryThumb category={category} size="size-8" />
                  <span className="font-semibold">{shortName(category)}</span>
                </Link>
              </li>
            ))}
            <li>
              <Link to="/products" onClick={onClose} className={link}>
                All products
              </Link>
            </li>
            <li>
              <Link to="/brands" onClick={onClose} className={link}>
                Brands
              </Link>
            </li>
          </ul>
        </div>
        <div>
          <h3 className={heading}>Offers</h3>
          <Link to="/products?ordering=discount" onClick={onClose} className={link}>
            Deals
          </Link>
          <Link to="/products?ordering=newest" onClick={onClose} className={link}>
            New arrivals
          </Link>
        </div>
        <div>
          <h3 className={heading}>Tools</h3>
          {TOOL_LINKS.map(([label, to]) => (
            <Link key={label} to={to} onClick={onClose} className={link}>
              {label}
            </Link>
          ))}
        </div>
        <div>
          <h3 className={heading}>AI</h3>
          {AI_LINKS.map(([label, to, , icon]) => (
            <Link key={label} to={to} onClick={onClose} className={link}>
              <span className="text-amber-600">{icon}</span>
              {label}
            </Link>
          ))}
        </div>
        <div className="border-t border-steel-200 pt-3">
          <h3 className={heading}>Your account</h3>
          {status === 'authenticated' ? (
            <>
              {ACCOUNT_LINKS.map(([label, to]) => (
                <Link key={to} to={to} onClick={onClose} className={link}>
                  {label}
                </Link>
              ))}
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

/**
 * The storefront header: one row with the logo, the (only) search and the account icons; below 768px
 * the same search moves to its own full-width row. From 1024px a compact navigation row with
 * dropdowns follows; below that the navigation lives in the menu drawer.
 */
export function Header() {
  const [menuOpen, setMenuOpen] = useState(false)
  const cartCount = useCartCount()
  const wishlistCount = useWishlistIds().size
  const location = useLocation()
  const [params] = useSearchParams()
  const urlQuery = location.pathname === '/search' ? (params.get('q') ?? '') : ''
  const { status } = useAuth()
  const categoriesQuery = useCategories()
  const categories = (categoriesQuery.data ?? []).filter((c) => c.product_count !== 0)
  const icon = 'relative grid size-10 shrink-0 place-items-center rounded-md hover:text-amber-500'

  return (
    <header className="sticky top-0 z-30 bg-ink-900 text-white shadow">
      <div className="container-page flex flex-wrap items-center gap-x-2 gap-y-2 py-2.5 sm:gap-x-3 md:h-16 md:flex-nowrap md:py-0 lg:gap-x-5">
        <button
          type="button"
          onClick={() => setMenuOpen(true)}
          className="-ml-2 grid size-10 shrink-0 place-items-center rounded-md lg:hidden"
          aria-label="Open menu"
        >
          <MenuIcon className="size-6" />
        </button>
        <Logo />
        <div className="order-last w-full md:order-none md:w-auto md:min-w-0 md:flex-1">
          <SearchBar key={urlQuery} initialQuery={urlQuery} />
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-0.5 sm:gap-1 md:ml-0">
          {status === 'authenticated' && (
            <div className="grid size-10 place-items-center">
              <NotificationBell />
            </div>
          )}
          <Link to="/wishlist" className={`${icon} hidden sm:grid`} aria-label="Wishlist" title="Wishlist">
            <HeartIcon className="size-6" />
            <CountBadge count={wishlistCount} label="saved items" />
          </Link>
          <Link to="/cart" className={icon} aria-label="Cart" title="Cart">
            <CartIcon className="size-6" />
            <CountBadge count={cartCount} label="items in cart" />
          </Link>
          <AccountMenu />
        </div>
      </div>
      <DesktopNav categories={categories} />
      <MobileMenu open={menuOpen} onClose={() => setMenuOpen(false)} categories={categories} />
    </header>
  )
}
