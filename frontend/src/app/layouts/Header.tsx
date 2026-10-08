import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useSearchParams } from 'react-router'

import { Drawer } from '@/components/Drawer'
import { CameraIcon, CartIcon, ChevronDownIcon, ChevronRightIcon, ClockIcon, HeartIcon, ImageIcon, MenuIcon, MicIcon, SparkIcon, UserIcon } from '@/components/icons'
import { useAuth } from '@/features/auth/context'
import { useCartCount } from '@/features/cart/api'
import { useNavGroups, type NavGroup } from '@/features/catalog/navGroups'
import { FastDeliveryBadge } from '@/features/delivery/FastDeliveryBadge'
import { LocationSelector } from '@/features/location/LocationSelector'
import { NotificationBell } from '@/features/notifications/NotificationBell'
import { SearchBar } from '@/features/search/SearchBar'
import { useWishlistIds } from '@/features/wishlist/api'
import { env } from '@/lib/env'
import { pluralize } from '@/lib/format'

const ACCOUNT_LINKS: [string, string][] = [
  ['My account', '/account'],
  ['Orders', '/account/orders'],
  ['Wishlist', '/wishlist'],
  ['Wallet', '/account/wallet'],
  ['Notifications', '/notifications'],
]

/** Kept out of the main navigation (it is for products only); listed in the menu drawer and the footer. */
const MORE_LINKS: [string, string, ReactNode?][] = [
  ['AI assistant', '/ai-assistant', <SparkIcon key="s" className="size-4" />],
  ['Search with a photo', '/image-search', <CameraIcon key="c" className="size-4" />],
  ['Shop by voice', '/voice', <MicIcon key="m" className="size-4" />],
  ['Project builder', '/projects'],
  ['Quantity calculator', '/quantity'],
  ['All products', '/products'],
  ['Brands', '/brands'],
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
    <Link to="/" className="flex shrink-0 items-center gap-2 text-base font-extrabold tracking-tight sm:text-lg">
      <img src="/favicon.svg" alt="" className="size-7 sm:size-8" />
      <span className="whitespace-nowrap">{env.appName}</span>
    </Link>
  )
}

function Thumb({ src, size = 'size-9' }: { src: string | null; size?: string }) {
  return src ? (
    <img src={src} alt="" loading="lazy" className={`${size} shrink-0 rounded-md bg-steel-100 object-cover`} />
  ) : (
    <span aria-hidden className={`${size} grid shrink-0 place-items-center rounded-md bg-steel-100 text-steel-400`}>
      <ImageIcon className="size-4" />
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
        <UserIcon className="size-6 shrink-0" />
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
        <UserIcon className="size-6 shrink-0" />
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
function NavMenu({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  // Pointing at the menu opens it; the click that usually follows must not close it again.
  const hoverOpenedAt = useRef(0)
  const box = useRef<HTMLLIElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const id = useId()
  const { pathname, search, hash } = useLocation()
  // Close after navigating (reset during render, as elsewhere in the app, instead of in an effect).
  const route = pathname + search + hash
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
        className={`flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-2 text-[13px] font-semibold hover:text-amber-500 lg:px-3 lg:text-sm ${open ? 'text-amber-500' : ''}`}
      >
        {label}
        <ChevronDownIcon className={`size-3.5 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        // Centred under the navigation row (the <ul> is the positioning box), so wide menus stay on screen.
        <div id={id} className="absolute left-1/2 top-full z-40 w-max max-w-[calc(100vw-2rem)] -translate-x-1/2 pt-1">
          <div className="rounded-xl bg-white p-4 text-ink-900 shadow-xl ring-1 ring-steel-200">{children}</div>
        </div>
      )}
    </li>
  )
}

/** The dropdown of one group: one column per department (its exact catalogue name), each with a real
 * product photo and its own subcategories from the catalogue. */
function GroupPanel({ group }: { group: NavGroup }) {
  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between gap-6 border-b border-steel-100 pb-2">
        <p className="whitespace-nowrap font-bold text-ink-950">{group.name}</p>
        <Link to={group.href} className="flex items-center gap-0.5 whitespace-nowrap text-sm font-semibold text-amber-600 hover:underline">
          View all
          <ChevronRightIcon className="size-4" />
        </Link>
      </div>
      <ul className="flex flex-wrap gap-x-8 gap-y-5">
        {group.entries.map((entry) => (
          <li key={entry.slug} className="min-w-44">
            <Link to={entry.href} className="group flex items-center gap-2.5 rounded-lg">
              <Thumb src={entry.image} size="size-10" />
              <span>
                <span className="block whitespace-nowrap text-sm font-bold leading-snug group-hover:text-amber-600">{entry.name}</span>{' '}
                {entry.productCount !== null && <span className="block text-xs text-ink-600">{pluralize(entry.productCount, 'product')}</span>}
              </span>
            </Link>
            {entry.subcategories.length > 0 && (
              <ul className="mt-2 space-y-1 pl-[50px]" aria-label={`In ${entry.name}`}>
                {entry.subcategories.slice(0, 5).map((sub) => (
                  <li key={sub.slug}>
                    <Link to={sub.href} className="block whitespace-nowrap text-sm text-ink-700 hover:text-amber-600">
                      {sub.name}
                    </Link>
                  </li>
                ))}
                {entry.subcategories.length > 5 && (
                  <li>
                    <Link to={entry.href} className="block whitespace-nowrap text-sm font-semibold text-amber-600 hover:underline">
                      +{entry.subcategories.length - 5} more
                    </Link>
                  </li>
                )}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Row 2 (from 768px): Home and the four product groups, centred. */
function MainNav({ groups }: { groups: NavGroup[] }) {
  const link = ({ isActive }: { isActive: boolean }) =>
    `block whitespace-nowrap rounded-md px-2 py-2 text-[13px] font-semibold hover:text-amber-500 lg:px-3 lg:text-sm ${isActive ? 'text-amber-500' : ''}`
  return (
    <div className="hidden border-t border-ink-800 bg-ink-900 md:block">
      <div className="container-page flex h-11 items-center justify-center">
        <nav aria-label="Main" className="min-w-0">
          <ul className="relative flex items-center gap-0.5 lg:gap-2 xl:gap-4">
            <li>
              <NavLink to="/" end className={link}>
                Home
              </NavLink>
            </li>
            {groups.map((group) => (
              <NavMenu key={group.slug} label={group.name}>
                <GroupPanel group={group} />
              </NavMenu>
            ))}
          </ul>
        </nav>
      </div>
    </div>
  )
}

function MobileMenu({ open, onClose, groups }: { open: boolean; onClose: () => void; groups: NavGroup[] }) {
  const { status, logout } = useAuth()
  const link = 'flex items-center gap-2 rounded-md px-2 py-2 text-sm hover:bg-steel-50'
  const heading = 'px-2 text-xs font-bold uppercase tracking-wide text-ink-600'
  return (
    <Drawer open={open} onClose={onClose} title="Menu">
      <nav aria-label="Mobile menu" className="space-y-5">
        <div>
          <h3 className={heading}>Shop by category</h3>
          <ul className="mt-1 space-y-1">
            <li>
              <Link to="/" onClick={onClose} className={`${link} font-semibold`}>
                Home
              </Link>
            </li>
            {groups.map((group) => (
              <li key={group.slug}>
                <details className="group/acc rounded-md">
                  <summary className="flex cursor-pointer list-none items-center gap-2.5 rounded-md px-2 py-2 text-sm font-semibold hover:bg-steel-50 [&::-webkit-details-marker]:hidden">
                    <Thumb src={group.images[0] ?? null} size="size-8" />
                    <span className="flex-1">{group.name}</span>
                    <ChevronDownIcon className="size-4 shrink-0 transition-transform group-open/acc:rotate-180" />
                  </summary>
                  <ul className="mb-1 ml-[52px] mt-0.5 space-y-0.5 border-l border-steel-200 pl-2">
                    {group.entries.map((entry) => (
                      <li key={entry.slug}>
                        <Link to={entry.href} onClick={onClose} className="block rounded px-2 py-1.5 text-sm text-ink-800 hover:bg-steel-50 hover:text-amber-600">
                          {entry.name}
                        </Link>
                      </li>
                    ))}
                    <li>
                      <Link to={group.href} onClick={onClose} className="block rounded px-2 py-1.5 text-sm font-semibold text-amber-600 hover:bg-steel-50">
                        View all {group.name}
                      </Link>
                    </li>
                  </ul>
                </details>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className={heading}>More ways to shop</h3>
          {MORE_LINKS.map(([label, to, icon]) => (
            <Link key={label} to={to} onClick={onClose} className={link}>
              {icon && <span className="text-amber-600">{icon}</span>}
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

/** The slim strip above the header (opening hours; VITE_STORE_HOURS, empty hides it). */
function TopStrip() {
  if (!env.storeHours) return null
  return (
    <div className="bg-amber-500 text-ink-950">
      <p className="container-page flex items-center justify-center gap-1.5 py-1.5 text-center text-xs font-semibold sm:text-sm">
        <ClockIcon className="size-4 shrink-0" />
        {env.storeHours}
      </p>
    </div>
  )
}

/**
 * The storefront header, three bands: a slim strip (opening hours, scrolls away), then the sticky
 * header. Row 1: logo, the fast-delivery badge and Deliver to, the one product search, wishlist, cart
 * and account. Below 768px the search and then the badge + Deliver to take their own full-width lines
 * (one element each, reordered with flex `order`, so nothing is rendered twice). Row 2 (from 768px):
 * Home and the four product groups with dropdowns. Below 1024px the menu drawer holds the groups too.
 */
export function Header() {
  const [menuOpen, setMenuOpen] = useState(false)
  const cartCount = useCartCount()
  const wishlistCount = useWishlistIds().size
  const location = useLocation()
  const [params] = useSearchParams()
  const urlQuery = location.pathname === '/search' ? (params.get('q') ?? '') : ''
  const { status } = useAuth()
  const { groups } = useNavGroups()
  const icon = 'relative grid size-10 shrink-0 place-items-center rounded-md hover:text-amber-500'

  return (
    <>
      <TopStrip />
      <header className="sticky top-0 z-30 bg-ink-900 text-white shadow">
        <div className="container-page flex flex-wrap items-center gap-x-1.5 gap-y-2 py-2.5 sm:gap-x-3 md:h-16 md:flex-nowrap md:py-0 lg:gap-x-5">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            className="order-1 -ml-2 grid size-10 shrink-0 place-items-center rounded-md lg:hidden"
            aria-label="Open menu"
          >
            <MenuIcon className="size-6" />
          </button>
          <div className="order-2">
            <Logo />
          </div>
          <div className="order-6 flex w-full items-center gap-3 md:order-3 md:w-auto md:shrink-0 lg:gap-4">
            {/* 768–1023px: no room for the badge in row 1; the PIN panel still says how fast. */}
            <span className="md:hidden lg:contents">
              <FastDeliveryBadge />
            </span>
            <LocationSelector />
          </div>
          <div className="order-5 w-full md:order-4 md:w-auto md:min-w-0 md:flex-1">
            <SearchBar key={urlQuery} initialQuery={urlQuery} />
          </div>
          <div className="order-4 ml-auto flex shrink-0 items-center gap-0.5 sm:gap-1 md:order-5 md:ml-0">
            {status === 'authenticated' && (
              <div className="grid size-10 place-items-center">
                <NotificationBell />
              </div>
            )}
            <Link to="/wishlist" className={icon} aria-label="Wishlist" title="Wishlist">
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
        <MainNav groups={groups} />
      </header>
      {/* Outside the header so the drawer does not inherit its white text. */}
      <MobileMenu open={menuOpen} onClose={() => setMenuOpen(false)} groups={groups} />
    </>
  )
}
