import { Link, useParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { ErrorState, PageSpinner } from '@/components/feedback'
import { useCategories, useCategory } from '@/features/catalog/api'
import { ProductBrowser } from '@/features/catalog/components/ProductBrowser'
import type { SubCategory } from '@/features/catalog/types'
import { isNotFound } from '@/lib/api/errors'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

/** /c/:slug — a top-level category or a subcategory, loaded from the API by slug. */
export function CategoryPage() {
  const { slug = '' } = useParams()
  const category = useCategory(slug)
  const tree = useCategories()

  const data = category.data
  const parent = data?.parent_detail
  // Subcategory pages show their siblings so shoppers can move sideways.
  const siblings: SubCategory[] = parent
    ? (tree.data?.find((c) => c.id === parent.id)?.children ?? [])
    : (data?.children ?? [])

  usePageMeta(
    data ? (parent ? `${data.name} — ${parent.name}` : data.name) : null,
    data
      ? data.description ||
          `Shop ${data.name.toLowerCase()}${parent ? ` in ${parent.name.toLowerCase()}` : ''}: compare prices, specifications and stock.`
      : undefined,
  )

  if (category.isPending) return <PageSpinner label="Loading category…" />
  if (category.isError) {
    if (isNotFound(category.error)) return <NotFoundPage />
    return (
      <div className="container-page py-10">
        <ErrorState error={category.error} onRetry={() => category.refetch()} title="Couldn’t load this category" />
      </div>
    )
  }

  return (
    <>
      <div className="border-b border-steel-200 bg-white">
        <div className="container-page py-4">
          <Breadcrumbs
            items={[
              ...(parent ? [{ label: parent.name, to: `/c/${parent.slug}` }] : []),
              { label: category.data.name },
            ]}
          />
          {siblings.length > 0 && (
            <nav aria-label={`${parent?.name ?? category.data.name} subcategories`} className="mt-3">
              <ul className="scrollbar-none -mx-4 flex gap-2 overflow-x-auto px-4">
                {parent && (
                  <li>
                    <Link
                      to={`/c/${parent.slug}`}
                      className="inline-block whitespace-nowrap rounded-full px-3 py-1.5 text-sm ring-1 ring-steel-200 hover:ring-amber-500"
                    >
                      All {parent.name}
                    </Link>
                  </li>
                )}
                {siblings.map((child) => {
                  const current = child.slug === slug
                  return (
                    <li key={child.id}>
                      <Link
                        to={`/c/${child.slug}`}
                        aria-current={current ? 'page' : undefined}
                        className={`inline-block whitespace-nowrap rounded-full px-3 py-1.5 text-sm ring-1 ${current ? 'bg-ink-900 text-white ring-ink-900' : 'ring-steel-200 hover:ring-amber-500'}`}
                      >
                        {child.name}
                        {child.product_count !== null && (
                          <span className={`ml-1 text-xs ${current ? 'text-steel-200' : 'text-ink-600'}`}>
                            ({child.product_count})
                          </span>
                        )}
                      </Link>
                    </li>
                  )
                })}
              </ul>
            </nav>
          )}
        </div>
      </div>
      <ProductBrowser
        key={slug}
        fixed={{ category: slug }}
        categoryLinks
        heading={<h1 className="text-2xl font-bold text-ink-950">{category.data.name}</h1>}
        emptyHint="No products are listed in this category yet. Try another category or search."
      />
    </>
  )
}
