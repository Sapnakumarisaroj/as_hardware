import { Link } from 'react-router'

import { ImageIcon } from '@/components/icons'
import { pluralize } from '@/lib/format'

import type { NavGroup } from '../navGroups'

/** A navigation group's departments as cards: photo, name, product count and subcategory chips. */
export function GroupDepartments({ group, className = '' }: { group: NavGroup; className?: string }) {
  return (
    <nav aria-label={`Shop ${group.name}`} className={className}>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {group.entries.map((entry) => (
          <li key={entry.slug} className="flex overflow-hidden rounded-xl bg-white ring-1 ring-steel-200 hover:ring-amber-500">
            <Link to={entry.href} className="group block w-28 shrink-0 overflow-hidden bg-steel-100 sm:w-36" tabIndex={-1} aria-hidden>
              {entry.image ? (
                <img src={entry.image} alt="" loading="lazy" className="size-full object-cover transition-transform duration-200 group-hover:scale-[1.03]" />
              ) : (
                <span className="grid size-full place-items-center text-steel-400">
                  <ImageIcon className="size-8" />
                </span>
              )}
            </Link>
            <div className="min-w-0 flex-1 p-3">
              <Link to={entry.href} className="block font-bold leading-tight text-ink-950 hover:text-amber-700">
                {entry.name}
              </Link>
              {entry.productCount !== null && <p className="mt-0.5 text-xs text-ink-600">{pluralize(entry.productCount, 'product')}</p>}
              {entry.subcategories.length > 0 && (
                <ul className="mt-2 flex flex-wrap gap-1.5" aria-label={`In ${entry.name}`}>
                  {entry.subcategories.map((sub) => (
                    <li key={sub.slug}>
                      <Link
                        to={sub.href}
                        className="inline-block whitespace-nowrap rounded-full bg-steel-50 px-2.5 py-1 text-xs text-ink-800 ring-1 ring-steel-200 hover:text-amber-700 hover:ring-amber-500"
                      >
                        {sub.name}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        ))}
      </ul>
    </nav>
  )
}
