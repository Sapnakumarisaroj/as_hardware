import { Link, useParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { ErrorState, PageSpinner } from '@/components/feedback'
import { ImageIcon } from '@/components/icons'
import { ProductRail } from '@/features/catalog/components/ProductCollections'
import { NAV_GROUPS, useNavGroups } from '@/features/catalog/navGroups'
import { pluralize } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

/** /shop/:group — one of the four navigation groups: its departments (the real catalogue categories,
 * with their own subcategories) and a product rail for each. */
export function ShopGroupPage() {
  const { group: slug = '' } = useParams()
  const { groups, categories } = useNavGroups()
  const known = NAV_GROUPS.find((g) => g.slug === slug)
  const group = groups.find((g) => g.slug === slug)
  usePageMeta(known?.name ?? null, known?.blurb)

  if (!known) return <NotFoundPage />
  if (categories.isPending) return <PageSpinner label="Loading categories…" />
  if (categories.isError) {
    return (
      <div className="container-page py-10">
        <ErrorState error={categories.error} onRetry={() => categories.refetch()} title="Couldn’t load this section" />
      </div>
    )
  }
  if (!group) return <NotFoundPage />

  return (
    <>
      <div className="border-b border-steel-200 bg-white">
        <div className="container-page py-5">
          <Breadcrumbs items={[{ label: group.name }]} />
          <h1 className="mt-2 text-2xl font-extrabold text-ink-950 sm:text-3xl">{group.name}</h1>
          <p className="mt-1 max-w-3xl text-sm text-ink-800">
            {group.blurb}
            {group.productCount !== null && <span className="text-ink-600"> · {pluralize(group.productCount, 'product')}</span>}
          </p>
          <nav aria-label={`Shop ${group.name}`} className="mt-5">
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
        </div>
      </div>
      <div className="container-page">
        {group.entries.map((entry) => (
          <ProductRail
            key={entry.slug}
            title={entry.name}
            params={{ category: entry.slug, ordering: 'popular', in_stock: 'true' }}
            viewAllHref={entry.href}
          />
        ))}
      </div>
    </>
  )
}
