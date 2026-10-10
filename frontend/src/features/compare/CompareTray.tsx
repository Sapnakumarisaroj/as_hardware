import { Link, useLocation } from 'react-router'

import { CloseIcon, CompareIcon, ImageIcon } from '@/components/icons'

import { clearCompare, COMPARE_MAX, removeFromCompare, useCompareItems } from './store'

/** Pages where the tray would get in the way (they have their own sticky bars or are about paying). */
const HIDDEN = [/^\/compare/, /^\/cart/, /^\/checkout/, /^\/orders\//, /^\/order-confirmation/, /^\/account/, /^\/quotes?(\/|$)/]

/**
 * The sticky compare tray: shown once something is picked for comparison. It sits above the product
 * page's mobile purchase bar instead of over it, and a spacer of the same height keeps the end of
 * the page (footer links) reachable.
 */
export function CompareTray() {
  const items = useCompareItems()
  const { pathname } = useLocation()
  if (!items.length || HIDDEN.some((re) => re.test(pathname))) return null
  const onProductPage = pathname.startsWith('/p/')
  const ready = items.length >= 2
  return (
    <>
      <div aria-hidden className={onProductPage ? 'h-40 lg:h-20' : 'h-20'} />
      <section
        aria-label="Compare products"
        data-testid="compare-tray"
        className={`fixed inset-x-0 z-20 px-3 sm:px-4 ${onProductPage ? 'bottom-[5.25rem] lg:bottom-4' : 'bottom-3 sm:bottom-4'}`}
      >
        <div className="mx-auto flex max-w-3xl items-center gap-2 rounded-2xl bg-ink-950 p-2 pl-3 text-white shadow-(--shadow-lift) ring-1 ring-white/10 sm:gap-3 sm:p-2.5 sm:pl-4">
          <CompareIcon className="hidden size-5 shrink-0 text-amber-400 sm:block" />
          <p className="min-w-0 shrink text-sm font-semibold">
            <span className="whitespace-nowrap">
              Compare {items.length}/{COMPARE_MAX}
            </span>
            {!ready && <span className="block text-xs font-normal text-steel-400">Add one more product</span>}
          </p>
          <ul className="hidden min-w-0 flex-1 items-center gap-2 sm:flex" aria-label="Picked for comparison">
            {items.map((item) => (
              <li key={item.slug} className="relative">
                {item.image ? (
                  <img src={item.image} alt={item.name} title={item.name} className="size-10 rounded-lg bg-white object-contain p-0.5" />
                ) : (
                  <span title={item.name} className="grid size-10 place-items-center rounded-lg bg-ink-800 text-steel-400">
                    <ImageIcon className="size-4" />
                    <span className="sr-only">{item.name}</span>
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => removeFromCompare(item.slug)}
                  aria-label={`Remove ${item.name} from compare`}
                  className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full bg-white text-ink-900 ring-1 ring-steel-200 after:absolute after:-inset-2 after:content-[''] hover:bg-amber-400"
                >
                  <CloseIcon className="size-3" />
                </button>
              </li>
            ))}
          </ul>
          <div className="ml-auto flex shrink-0 items-center gap-1 sm:gap-2">
            <button
              type="button"
              onClick={clearCompare}
              className="min-h-11 rounded-lg px-2.5 text-sm font-semibold text-steel-200 hover:bg-white/10 hover:text-white"
            >
              Clear
            </button>
            {ready ? (
              <Link to="/compare" className="btn-primary min-h-11 whitespace-nowrap px-4">
                Compare now
              </Link>
            ) : (
              <Link to="/compare" className="btn-secondary min-h-11 whitespace-nowrap bg-white/10 px-3 text-white ring-white/20 hover:bg-white/15">
                View
              </Link>
            )}
          </div>
        </div>
      </section>
    </>
  )
}
